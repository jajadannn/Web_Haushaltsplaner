"""Lokale KI für die Prüfliste (Ollama oder OpenAI-kompatibler Server wie LM Studio).

Die KI schlägt für offene Buchungen ohne Kategorie eine Kategorie vor. Sie bestätigt nie
selbst: Ein Vorschlag setzt die Buchung auf „automatisch zugeordnet“ (Herkunft `ai`) mit
kurzer Begründung, bestätigt wird in der Prüfliste. Jede Buchung wird der KI nur einmal
vorgelegt (`ai_checked_at`); „Erneut prüfen“ setzt das für noch offene Buchungen zurück.

Der Import-Worker arbeitet die Warteschlange in einem eigenen Thread ab, damit lange
Antwortzeiten (auf schwacher Hardware 15–20 s je Buchung) keine Importe aufhalten.
"""

import json
import logging
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import exists, func, not_, or_
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.config import get_settings
from app.models import (
    Category,
    CategorySource,
    ReviewStatus,
    Transaction,
    TransactionKind,
    TransactionSplit,
    User,
)
from app.models.imports import ImportRow

log = logging.getLogger("finanzplaner.ki")

NO_MATCH = 0
IDLE_SECONDS = 10.0  # Warteschlange leer: so oft nachsehen
BACKOFF_SECONDS = 60.0  # Ollama nicht erreichbar: so lange warten
MAX_EXAMPLES = 5
CONFIDENCE = ("hoch", "mittel", "niedrig")

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "kategorie_id": {"type": "integer"},
        "sicherheit": {"type": "string", "enum": list(CONFIDENCE)},
        "begruendung": {"type": "string"},
    },
    "required": ["kategorie_id", "sicherheit", "begruendung"],
}

SYSTEM_PROMPT = (
    "Du ordnest Kontobewegungen eines deutschen Privathaushalts genau einer Kategorie zu. "
    "Wähle nur eine Nummer aus der Liste. Passt keine Kategorie sicher, wähle 0. "
    "Frühere, vom Nutzer bestätigte Buchungen derselben Gegenpartei sind ein starker Hinweis. "
    "Die Begründung ist ein kurzer deutscher Satz. Antworte nur mit JSON."
)


class AiUnavailable(Exception):
    """KI-Server nicht erreichbar oder Modell fehlt – später erneut versuchen, Buchung bleibt offen."""


@dataclass(frozen=True)
class Suggestion:
    category_id: int | None
    confidence: str
    reason: str

    @property
    def note(self) -> str:
        reason = self.reason.strip() or "ohne Begründung"
        if self.category_id is None:
            return f"Keine passende Kategorie: {reason}"[:300]
        return f"{reason} (Sicherheit: {self.confidence})"[:300]


# --- Warteschlange ---------------------------------------------------------------------------


def pending_query(user_id: int | None = None):
    """Offene Buchungen ohne Kategorie, die die KI noch nicht gesehen hat.

    Ausgenommen: Umbuchungen, ausgeschlossene und aufgeteilte Buchungen sowie Buchungen, die
    der Import als Kreditrate erkannt hat (dort ist „Als Rate buchen“ richtig).
    """
    query = select(Transaction).where(
        Transaction.ai_checked_at.is_(None),
        Transaction.review_status == ReviewStatus.NEEDS_REVIEW,
        Transaction.category_id.is_(None),
        Transaction.kind == TransactionKind.REGULAR,
        Transaction.excluded_at.is_(None),
        not_(exists().where(TransactionSplit.transaction_id == Transaction.id)),
        not_(
            exists().where(
                ImportRow.created_transaction_id == Transaction.id,
                ImportRow.suggested_loan_entry_id.is_not(None),
            )
        ),
    )
    return query if user_id is None else query.where(Transaction.user_id == user_id)


def pending_count(session: Session, user: User) -> int:
    return session.exec(select(func.count()).select_from(pending_query(user.id).subquery())).one()


def next_pending_id(session: Session) -> int | None:
    """Neueste zuerst – frisch importierte Buchungen sind am schnellsten dran."""
    query = pending_query().with_only_columns(Transaction.id).order_by(Transaction.id.desc()).limit(1)
    return session.exec(query).first()


def retry(session: Session, user: User) -> int:
    """Noch offene Buchungen der KI erneut vorlegen (z. B. nach neuen Kategorien)."""
    txs = session.exec(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.ai_checked_at.is_not(None),
            Transaction.review_status == ReviewStatus.NEEDS_REVIEW,
            Transaction.category_id.is_(None),
        )
    ).all()
    for tx in txs:
        tx.ai_checked_at, tx.ai_note = None, None
    session.flush()
    return len(txs)


# --- Eingabe für die KI ---------------------------------------------------------------------


def _full_names(categories: list[Category]) -> dict[int, str]:
    by_id = {c.id: c for c in categories}

    def name(c: Category) -> str:
        parent = by_id.get(c.parent_id) if c.parent_id else None
        return f"{parent.name} > {c.name}" if parent else c.name

    return {c.id: name(c) for c in categories}


def offered_categories(session: Session, tx: Transaction) -> dict[int, str]:
    """Aktive Kategorien passend zum Vorzeichen (Ausgabe/Einnahme), ohne Systemkategorien."""
    categories = list(session.exec(select(Category).where(Category.user_id == tx.user_id)))
    names = _full_names(categories)
    wanted = "expense" if tx.amount < 0 else "income"
    return {
        c.id: names[c.id]
        for c in sorted(categories, key=lambda c: names[c.id].lower())
        if c.active and not c.system_key and c.type == wanted
    }


def examples(session: Session, tx: Transaction, names: dict[int, str]) -> list[str]:
    """Bestätigte Buchungen derselben Gegenpartei (IBAN oder Name) mit ihrer Kategorie."""
    same = []
    if tx.counterparty_iban:
        same.append(Transaction.counterparty_iban == tx.counterparty_iban)
    if tx.counterparty:
        same.append(func.lower(Transaction.counterparty) == tx.counterparty.lower())
    if not same:
        return []
    rows = session.exec(
        select(Transaction)
        .where(
            Transaction.user_id == tx.user_id,
            Transaction.id != tx.id,
            Transaction.review_status == ReviewStatus.CONFIRMED,
            Transaction.category_id.is_not(None),
            or_(*same),
        )
        .order_by(Transaction.booking_date.desc())
        .limit(MAX_EXAMPLES)
    ).all()
    return [
        f"- {_euro(r.amount)} „{_short(r.description, 80)}“ → {names[r.category_id]}"
        for r in rows
        if r.category_id in names
    ]


def _euro(amount: Decimal) -> str:
    return f"{amount:+.2f} EUR".replace(".", ",")


def _short(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_messages(tx: Transaction, offered: dict[int, str], history: list[str]) -> list[dict]:
    kind = "Ausgabe" if tx.amount < 0 else "Einnahme"
    lines = [f"Kategorien für {kind}n (Nummer: Name):"]
    lines += [f"{cid}: {name}" for cid, name in offered.items()]
    lines.append(f"{NO_MATCH}: keine passt")
    if history:
        lines += ["", "Frühere, bestätigte Buchungen derselben Gegenpartei:", *history]
    lines += [
        "",
        "Buchung:",
        f"Datum: {tx.booking_date:%d.%m.%Y}",
        f"Betrag: {_euro(tx.amount)} ({kind})",
        f"Empfänger/Auftraggeber: {_short(tx.counterparty, 120) or '–'}",
        f"Verwendungszweck: {_short(tx.description, 300) or '–'}",
    ]
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


def parse_answer(content: str, offered: dict[int, str]) -> Suggestion:
    """Antwort prüfen; Unbrauchbares wird zu „keine passende Kategorie“, nie zu einer erfundenen."""
    try:
        data = json.loads(content)
        category_id = int(data["kategorie_id"])
        confidence = str(data.get("sicherheit", "niedrig"))
        reason = _short(str(data.get("begruendung", "")), 240)
    except (ValueError, TypeError, KeyError):
        return Suggestion(None, "niedrig", "Antwort der KI war nicht lesbar")
    if confidence not in CONFIDENCE:
        confidence = "niedrig"
    if category_id not in offered:
        return Suggestion(None, confidence, reason)
    return Suggestion(category_id, confidence, reason)


# --- KI-Server: Ollama oder OpenAI-kompatibel ---------------------------------------------------

# Nachdenken („Reasoning“) abschalten: kostet bei der Zuordnung nur Zeit. Ältere Server
# kennen die Felder nicht – dann einmal ohne versuchen und es danach weglassen.
_think_supported = True  # Ollama: „think“
_reasoning_supported = True  # OpenAI-kompatibel (z. B. LM Studio): „reasoning_effort“


def _post(path: str, body: dict | None, timeout: float) -> dict:
    url = get_settings().ai_url.rstrip("/") + path
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _ollama_chat(messages: list[dict]) -> str:
    global _think_supported
    settings = get_settings()
    body = {
        "model": settings.ai_model,
        "messages": messages,
        "stream": False,
        "format": RESPONSE_SCHEMA,
        "options": {"temperature": 0},
        "keep_alive": "15m",
    }
    if _think_supported:
        body["think"] = False
    try:
        return _post("/api/chat", body, settings.ai_timeout_seconds)["message"]["content"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        if exc.code == 400 and _think_supported and "think" in detail:
            _think_supported = False
            return _ollama_chat(messages)
        raise


def _openai_chat(messages: list[dict]) -> str:
    global _reasoning_supported
    settings = get_settings()
    body = {
        "model": settings.ai_model,
        "messages": messages,
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "kategorie", "strict": True, "schema": RESPONSE_SCHEMA},
        },
    }
    if _reasoning_supported:
        body["reasoning_effort"] = "none"
    try:
        return _post("/chat/completions", body, settings.ai_timeout_seconds)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        if exc.code in (400, 422) and _reasoning_supported and "reasoning" in detail:
            _reasoning_supported = False
            return _openai_chat(messages)
        raise


def chat(messages: list[dict]) -> str:
    """Eine Anfrage an den KI-Server; liefert den Text der Antwort (JSON nach RESPONSE_SCHEMA)."""
    settings = get_settings()
    try:
        return _openai_chat(messages) if settings.ai_api == "openai" else _ollama_chat(messages)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        if exc.code == 404:
            raise AiUnavailable(f"Modell „{settings.ai_model}“ nicht gefunden: {detail}") from exc
        raise AiUnavailable(f"KI-Server antwortet mit {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiUnavailable(str(exc)) from exc


def reachable() -> bool:
    path = "/models" if get_settings().ai_api == "openai" else "/api/version"
    try:
        _post(path, None, timeout=2)
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


# --- Eine Buchung prüfen ---------------------------------------------------------------------


def _still_pending(tx: Transaction | None) -> bool:
    return (
        tx is not None
        and tx.ai_checked_at is None
        and tx.review_status == ReviewStatus.NEEDS_REVIEW
        and tx.category_id is None
        and tx.kind == TransactionKind.REGULAR
        and tx.excluded_at is None
        and not tx.splits
    )


def review_one(session: Session, tx_id: int) -> Suggestion | None:
    """Eine Buchung der KI vorlegen und den Vorschlag eintragen.

    Während die KI rechnet, ist keine Datenbank-Transaktion offen; vor dem Schreiben wird die
    Buchung gesperrt und erneut geprüft – wer sie inzwischen bestätigt hat, gewinnt.
    """
    tx = session.get(Transaction, tx_id)
    if not _still_pending(tx):
        return None
    offered = offered_categories(session, tx)
    messages = build_messages(tx, offered, examples(session, tx, _all_names(session, tx.user_id)))
    stamp = tx.updated_at
    session.rollback()  # Lesetransaktion beenden, bevor die KI rechnet

    suggestion = parse_answer(chat(messages), offered) if offered else Suggestion(None, "niedrig", "keine Kategorien")

    tx = session.get(Transaction, tx_id, with_for_update=True, populate_existing=True)
    if not _still_pending(tx) or tx.updated_at != stamp:
        session.rollback()
        return None
    tx.ai_checked_at = datetime.now(UTC)
    tx.ai_note = suggestion.note
    if suggestion.category_id is not None:
        tx.category_id = suggestion.category_id
        tx.category_source = CategorySource.AI
        tx.applied_rule_id = None
        tx.review_status = ReviewStatus.AUTO_CATEGORIZED
    session.commit()
    log.info("Buchung %s: %s", tx_id, suggestion.note)
    return suggestion


def _all_names(session: Session, user_id: int) -> dict[int, str]:
    return _full_names(list(session.exec(select(Category).where(Category.user_id == user_id))))


# --- Hintergrund-Thread im Worker ------------------------------------------------------------


def _give_up(engine: Engine, tx_id: int) -> None:
    """Unerwarteter Fehler bei einer Buchung: als geprüft markieren, damit sie die Warteschlange nicht blockiert."""
    with Session(engine) as session:
        tx = session.get(Transaction, tx_id, with_for_update=True)
        if _still_pending(tx):
            tx.ai_checked_at, tx.ai_note = datetime.now(UTC), "KI-Prüfung fehlgeschlagen – bitte selbst zuordnen"
            session.commit()


def run_forever(engine: Engine, stop: threading.Event) -> None:
    settings = get_settings()
    log.info("Lokale KI aktiv: %s (%s) mit Modell %s", settings.ai_url, settings.ai_api, settings.ai_model)
    while not stop.is_set():
        tx_id = None
        try:
            with Session(engine) as session:
                tx_id = next_pending_id(session)
                session.rollback()
                if tx_id is None:
                    stop.wait(IDLE_SECONDS)
                    continue
                review_one(session, tx_id)
        except AiUnavailable as exc:
            log.warning("KI nicht verfügbar (%s) – neuer Versuch in %.0f s", exc, BACKOFF_SECONDS)
            stop.wait(BACKOFF_SECONDS)
        except Exception:
            log.exception("KI-Prüfung von Buchung %s fehlgeschlagen", tx_id)
            if tx_id is not None:
                try:
                    _give_up(engine, tx_id)
                except Exception:
                    log.exception("Buchung %s konnte nicht markiert werden", tx_id)
            stop.wait(IDLE_SECONDS)


def start_in_background(engine: Engine) -> threading.Event | None:
    """Startet den KI-Thread, falls AI_URL gesetzt ist; liefert das Stopp-Signal."""
    if not get_settings().ai_url:
        log.info("Lokale KI aus (AI_URL nicht gesetzt)")
        return None
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(engine, stop), name="ki-pruefung", daemon=True).start()
    return stop
