"""Belege, Rechnungen und Verträge (Ideen 14 und 15).

- Upload mit Größen- und Typprüfung (PDF, JPEG, PNG, WebP); Datei unter DOCUMENT_DIR, Pfad relativ
  gespeichert (wie bei Importdateien, damit ein Restore an anderen Ort funktioniert).
- Auslesen als KI-Auftrag: PDF mit Textebene als Text (pypdf), Bilder über das Bildmodell. Scans ohne
  Textebene werden mit Hinweis abgelehnt (kein lokales PDF-Rendering).
- Werte sind Vorschläge: Zuordnung zu einer Buchung (±5 Tage, ±1 % Betrag) als `receipt_match`;
  Vertragsdaten als `contract_draft` – jedes Vertragsfeld nur mit Fundstelle (Seite/Zitat), sonst
  verworfen. Eine Rechnung beweist keine Zahlung; aus einem Beleg wird nie eine Buchung angelegt.
"""

import hashlib
import io
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlmodel import Session, select

from app.config import get_settings
from app.errors import Conflict, Invalid, NotFound
from app.models import (
    AiJob,
    Contract,
    Document,
    DocumentLink,
    DocumentStatus,
    FixedCost,
    Merchant,
    Suggestion,
    SuggestionKind,
    SuggestionStatus,
    Transaction,
    User,
)
from app.schemas.budget import FixedCostCreate
from app.services import ai_jobs, budget, changes, merchants, recurring, suggestions
from app.services.common import get_owned
from app.services.suggestions import Handler, jsonable

ALLOWED = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAGIC = {b"%PDF": "application/pdf", b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"RIFF": "image/webp"}
MAX_TEXT = 8000
EXTRACT = "document_extract"


def document_dir() -> Path:
    path = Path(get_settings().document_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_path(doc: Document) -> Path:
    return document_dir() / doc.stored_path


def _sniff(content: bytes) -> str | None:
    return next((mime for magic, mime in MAGIC.items() if content.startswith(magic)), None)


def upload(session: Session, user: User, content: bytes, filename: str, kind: str) -> Document:
    mime = _sniff(content)
    if mime not in ALLOWED:
        raise Invalid("Nur PDF, JPEG, PNG oder WebP", code="document_type")
    digest = hashlib.sha256(content).hexdigest()
    existing = session.exec(select(Document).where(Document.user_id == user.id, Document.sha256 == digest)).first()
    if existing is not None:
        return existing
    name = f"{uuid.uuid4().hex}{ALLOWED[mime]}"
    (document_dir() / name).write_bytes(content)
    doc = Document(user_id=user.id, kind=kind, original_filename=Path(filename or "datei").name[:255],
                   stored_path=name, sha256=digest, mime=mime, size=len(content))
    session.add(doc)
    session.flush()
    ai_jobs.enqueue(session, user.id, EXTRACT, "document", doc.id)
    return doc


def get_document(session: Session, user: User, document_id: int) -> Document:
    return get_owned(session, Document, document_id, user.id, "Dokument")


def links(session: Session, doc: Document) -> list[DocumentLink]:
    return list(session.exec(select(DocumentLink).where(DocumentLink.document_id == doc.id)))


def add_link(session: Session, user: User, doc: Document, *, transaction_id=None, fixed_cost_id=None,
             contract_id=None) -> DocumentLink:
    targets = [(transaction_id, Transaction, "Buchung"), (fixed_cost_id, FixedCost, "Fixkost"),
               (contract_id, Contract, "Vertrag")]
    given = [(i, m, n) for i, m, n in targets if i is not None]
    if len(given) != 1:
        raise Invalid("Genau ein Ziel angeben", code="document_link_target")
    get_owned(session, given[0][1], given[0][0], user.id, given[0][2])
    link = DocumentLink(document_id=doc.id, transaction_id=transaction_id, fixed_cost_id=fixed_cost_id,
                        contract_id=contract_id)
    session.add(link)
    session.flush()
    return link


def delete_document(session: Session, doc: Document) -> None:
    path = file_path(doc)
    session.delete(doc)
    session.flush()
    path.unlink(missing_ok=True)


# --- Auslesen (KI-Auftrag) -----------------------------------------------------------------------

STRING_OR_NULL = {"type": ["string", "null"]}
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "art": {"type": "string", "enum": ["beleg", "rechnung", "vertrag", "sonstiges"]},
        "haendler": STRING_OR_NULL, "datum": STRING_OR_NULL, "betrag": STRING_OR_NULL, "waehrung": STRING_OR_NULL,
        "positionen": {"type": "array", "maxItems": 50, "items": {
            "type": "object", "properties": {"text": {"type": "string"}, "betrag": {"type": "string"}},
            "required": ["text", "betrag"], "additionalProperties": False}},
        "vertrag": {"type": ["object", "null"], "properties": {
            "anbieter": STRING_OR_NULL, "beitrag": STRING_OR_NULL, "rhythmus_monate": {"type": ["integer", "null"]},
            "naechste_faelligkeit": STRING_OR_NULL, "kuendigungsfrist": STRING_OR_NULL,
            "laufzeit_ende": STRING_OR_NULL},
            "required": ["anbieter", "beitrag", "rhythmus_monate", "naechste_faelligkeit", "kuendigungsfrist",
                         "laufzeit_ende"], "additionalProperties": False},
        "fundstellen": {"type": "array", "maxItems": 30, "items": {
            "type": "object", "properties": {"feld": {"type": "string"}, "seite": {"type": "integer"},
                                             "zitat": {"type": "string"}},
            "required": ["feld", "seite", "zitat"], "additionalProperties": False}},
    },
    "required": ["art", "haendler", "datum", "betrag", "waehrung", "positionen", "vertrag", "fundstellen"],
    "additionalProperties": False,
}
TASK = (
    "Lies das Dokument (Kassenbon, Rechnung oder Vertrag) aus. Beträge als Zahl mit Punkt (z. B. 45.60), Datum als "
    "JJJJ-MM-TT. Bei Verträgen: Beitrag, Zahlungsrhythmus in Monaten, nächste Fälligkeit, Kündigungsfrist und "
    "Laufzeitende NUR, wenn sie wörtlich im Dokument stehen – mit Fundstelle (Feldname, Seite, kurzes Zitat). "
    "Fehlende Angaben sind null; nichts ergänzen."
)


def _pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [f"[Seite {i}]\n{(page.extract_text() or '').strip()}" for i, page in enumerate(reader.pages[:10], 1)]
    except PdfReadError as exc:
        raise ValueError(f"PDF nicht lesbar: {exc}") from exc
    text = "\n\n".join(pages)
    return text if re.search(r"\w{3,}", re.sub(r"\[Seite \d+\]", "", text)) else ""


def _prepare(session: Session, job: AiJob):
    doc = session.get(Document, job.ref_id)
    if doc is None:
        return None
    content = file_path(doc).read_bytes()
    if doc.mime == "application/pdf":
        try:
            text = _pdf_text(content)
        except ValueError as exc:
            doc.status, doc.error = DocumentStatus.FAILED, str(exc)[:500]
            return None
        if not text:
            doc.status = DocumentStatus.FAILED
            doc.error = "PDF ohne Textebene (Scan) – bitte als Foto/Bild hochladen"
            return None
        return TASK, {"dokumenttext": text[:MAX_TEXT]}, EXTRACT_SCHEMA
    return TASK, ai_jobs.Image(content, doc.mime), EXTRACT_SCHEMA


def _amount(value) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01")) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _date(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _verified_contract(answer: dict) -> dict | None:
    contract = answer.get("vertrag")
    if not contract or all(v in (None, "") for v in contract.values()):
        return None  # Modelle liefern ohne Vertrag oft ein Objekt voller null
    sourced = {f["feld"] for f in answer.get("fundstellen", []) if f.get("zitat", "").strip()}
    cleaned = {k: (v if k in sourced or k == "anbieter" else None) for k, v in contract.items()}
    return cleaned if cleaned.get("beitrag") and cleaned.get("rhythmus_monate") else cleaned


def _finish(session: Session, job: AiJob, answer: dict):
    doc = session.get(Document, job.ref_id, with_for_update=True)
    if doc is None:
        return None
    contract = _verified_contract(answer)
    doc.extracted = answer | {"vertrag": contract}
    doc.status, doc.error = DocumentStatus.EXTRACTED, None
    user = session.get(User, doc.user_id)
    found = []
    amount, day = _amount(answer.get("betrag")), _date(answer.get("datum"))
    if amount and day:
        tolerance = max(amount * Decimal("0.01"), Decimal("0.01"))
        candidates = session.exec(select(Transaction).where(
            Transaction.user_id == user.id, Transaction.amount < 0, Transaction.excluded_at.is_(None),
            Transaction.booking_date.between(day - timedelta(days=5), day + timedelta(days=5)),
        )).all()
        candidates = [t for t in candidates if abs(-t.amount - amount) <= tolerance]
        for t in sorted(candidates, key=lambda t: abs((t.booking_date - day).days))[:3]:
            found.append(Suggestion(
                user_id=user.id, kind=SuggestionKind.RECEIPT_MATCH, fingerprint=f"doc:{doc.id}|tx:{t.id}",
                payload=jsonable({"document_id": doc.id, "transaction_id": t.id, "amount": amount, "date": day,
                                  "merchant": answer.get("haendler"), "positions": answer.get("positionen", [])}),
                evidence={}, generator="document-v1",
                reason=f"Beleg „{doc.original_filename}“ ({amount} €, {day:%d.%m.%Y}) passt zur Buchung vom "
                       f"{t.booking_date:%d.%m.%Y} ({-t.amount} €).",
            ))
    if contract and contract.get("beitrag") and contract.get("rhythmus_monate") in (1, 3, 6, 12):
        found.append(Suggestion(
            user_id=user.id, kind=SuggestionKind.CONTRACT_DRAFT, fingerprint=f"doc:{doc.id}|contract",
            payload=jsonable({"document_id": doc.id, "contract": contract,
                              "sources": answer.get("fundstellen", [])}),
            evidence={}, generator="document-v1",
            reason=f"Vertragsdaten aus „{doc.original_filename}“: {contract.get('anbieter')}, "
                   f"{contract.get('beitrag')} € alle {contract.get('rhythmus_monate')} Monat(e).",
        ))
    for suggestion in found:
        exists = session.exec(select(Suggestion.id).where(
            Suggestion.user_id == user.id, Suggestion.kind == suggestion.kind,
            Suggestion.fingerprint == suggestion.fingerprint)).first()
        if exists is None:
            session.add(suggestion)
    session.flush()
    return None


ai_jobs.register(EXTRACT, ai_jobs.Task(prepare=_prepare, finish=_finish))


# --- Handler -------------------------------------------------------------------------------------


def _receipt_apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    doc = get_document(session, user, suggestion.payload["document_id"])
    tx_id = suggestion.payload["transaction_id"]
    if session.exec(select(DocumentLink.id).where(DocumentLink.document_id == doc.id,
                                                  DocumentLink.transaction_id == tx_id)).first():
        raise Conflict("Beleg ist bereits zugeordnet", code="suggestion_stale")
    link = add_link(session, user, doc, transaction_id=tx_id)
    # andere Zuordnungsvorschläge für denselben Beleg sind damit erledigt
    for other in session.exec(select(Suggestion).where(
            Suggestion.user_id == user.id, Suggestion.kind == SuggestionKind.RECEIPT_MATCH,
            Suggestion.status == SuggestionStatus.OPEN, Suggestion.id != suggestion.id)):
        if other.payload.get("document_id") == doc.id:
            other.status = SuggestionStatus.STALE
    return "document_link", link.id


def _contract_apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    data = suggestion.payload["contract"] | {k: v for k, v in overrides.items() if k in suggestion.payload["contract"]}
    doc = get_document(session, user, suggestion.payload["document_id"])
    name = (data.get("anbieter") or "Vertrag")[:100]
    merchant = session.exec(select(Merchant).where(Merchant.user_id == user.id, Merchant.name == name)).first() \
        or merchants.create_merchant(session, user, name)
    contract = Contract(user_id=user.id, merchant_id=merchant.id, label=name,
                        notice_period=data.get("kuendigungsfrist"), term_end=data.get("laufzeit_ende"))
    session.add(contract)
    session.flush()
    result = ("contract", contract.id)
    amount, interval = _amount(data.get("beitrag")), data.get("rhythmus_monate")
    if overrides.get("create_fixed_cost", True) and amount and interval in (1, 3, 6, 12):
        first_due = _date(data.get("naechste_faelligkeit"))
        if interval != 1 and first_due is None:
            raise Invalid("Für einen nicht monatlichen Vertrag fehlt die nächste Fälligkeit",
                          code="first_due_date_required")
        fixed = budget.create_fixed_cost(session, user, FixedCostCreate(
            name=name, amount=amount, due_day=(first_due.day if first_due else 1), interval_months=interval,
            first_due_date=first_due if interval != 1 else None,
        ))
        contract.fixed_cost_id = fixed.id
        changes.record(session, user.id, fixed, recurring.FIXED_FIELDS, action="create", before=None,
                       suggestion_id=suggestion.id, actor=actor)
        result = ("fixed_cost", fixed.id)
    add_link(session, user, doc, contract_id=contract.id)
    session.flush()
    return result


suggestions.register(SuggestionKind.RECEIPT_MATCH, Handler(validate=lambda s, u, x: None, apply=_receipt_apply))
suggestions.register(SuggestionKind.CONTRACT_DRAFT, Handler(validate=lambda s, u, x: None, apply=_contract_apply))
_ = NotFound
