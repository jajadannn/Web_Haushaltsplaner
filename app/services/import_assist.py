"""Importassistent (Idee 11) und Importdiagnose (Idee 12).

- `draft`: Aufbau einer CSV-Datei erkennen; auf Wunsch ordnet die KI nur die unklaren Spalten
  einer Rolle aus einer festen Liste zu – das Ergebnis prüft danach wieder der echte Parser.
- `diagnose`: Fehler eines Imports in verständliche Sätze übersetzen (feste Texte je Fehlercode)
  und – wo die Erkennung ein besser passendes Profil findet – eine Profilkorrektur vorschlagen.
"""

import json
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.errors import Conflict, Invalid
from app.importers.base import ParseError
from app.importers.detect import ROLES, Detection, detect_csv, verify
from app.models import ImportBatch, ImportProfile, Suggestion, SuggestionKind, SuggestionStatus, User
from app.services import ai_gateway, import_profiles, suggestions
from app.services.import_jobs import stored_file
from app.services.suggestions import Handler

ROLE_LABELS = {
    "booking_date": "Buchungsdatum", "value_date": "Wertstellung", "amount": "Betrag", "debit": "Soll",
    "credit": "Haben", "indicator": "Soll/Haben-Kennzeichen", "counterparty": "Gegenpartei",
    "counterparty_iban": "IBAN der Gegenpartei", "description": "Verwendungszweck", "currency": "Währung",
    "own_account": "eigenes Konto", "status": "Status", "external_id": "Umsatz-ID", "ignore": "nicht verwenden",
}


def _ai_roles(detection: Detection, session: Session | None) -> dict[str, str]:
    """KI ordnet unklare Spalten zu – nur Spaltennamen aus der Datei, nur Rollen aus der festen Liste."""
    columns = [h for h in detection.header if h]
    schema = {
        "type": "object",
        "properties": {"zuordnung": {"type": "array", "items": {
            "type": "object",
            "properties": {"spalte": {"type": "string", "enum": columns},
                           "rolle": {"type": "string", "enum": list(ROLES)}},
            "required": ["spalte", "rolle"], "additionalProperties": False}}},
        "required": ["zuordnung"],
        "additionalProperties": False,
    }
    data = {
        "spalten": columns,
        # Rohwerte unter den Originalspalten – die Parser-Vorschau fehlt gerade, solange Rollen unklar sind
        "beispielzeilen": [{k: v[:80] for k, v in row.items()} for row in detection.sample_rows],
        "rollen": {k: v for k, v in ROLE_LABELS.items()},
    }
    answer = ai_gateway.ask(
        "Ordne jeder Spalte eines Bank-Kontoauszugs (CSV) genau eine Rolle zu. Unklare Spalten bekommen 'ignore'.",
        data, schema, session=session,
    )
    roles: dict[str, str] = {}
    for item in answer["zuordnung"]:
        if item["rolle"] != "ignore" and item["rolle"] not in roles:
            roles[item["rolle"]] = item["spalte"]
    return roles


def _detect(content: bytes, roles_override: dict | None = None) -> Detection:
    try:
        return detect_csv(content, roles_override=roles_override)
    except (ParseError, UnicodeDecodeError) as exc:
        raise Invalid(f"Die Datei lässt sich nicht als CSV-Tabelle lesen: {exc}",
                      code="import_file_unreadable") from exc


def draft(content: bytes, *, use_ai: bool = False, session: Session | None = None) -> dict:
    detection = _detect(content)
    ai_used = False
    if use_ai and not detection.safe and ai_gateway.enabled():
        try:
            override = _ai_roles(detection, session)
            if override:
                detection = _detect(content, roles_override=override)
                ai_used = True
        except (ai_gateway.AiUnavailable, ai_gateway.AiInvalidAnswer):
            pass
    return detection.as_dict() | {"ai_used": ai_used}


def preview(content: bytes, settings: str) -> dict:
    try:
        options = json.loads(settings)
    except ValueError as exc:
        raise Invalid(f"Profilangaben unlesbar: {exc}", code="preview_settings_invalid") from exc
    if not isinstance(options, dict) or not isinstance(options.get("column_map", {}), dict):
        raise Invalid("Profilangaben müssen ein Objekt mit column_map sein", code="preview_settings_invalid")
    try:
        detection = Detection(options=options, header=[], roles=options.get("column_map", {}))
        return verify(content, detection).as_dict() | {"ai_used": False}
    except (ValueError, TypeError) as exc:
        raise Invalid(f"Profilangaben unlesbar: {exc}", code="preview_settings_invalid") from exc


# --- 12 Diagnose ---------------------------------------------------------------------------------

EXPLANATIONS = {
    "file_missing": "Die Arbeitskopie der Datei fehlt im Importordner – nach einem Umzug oder Restore bitte die "
                    "Datei erneut hochladen.",
    "file_changed": "Die Arbeitskopie wurde nach dem Hochladen verändert und wird deshalb nicht gelesen.",
    "parse_error": "Die Datei passt nicht zum Importprofil.",
    "row_errors": "Einige Zeilen konnten nicht gelesen werden; es wurde nichts übernommen.",
    "account_unknown": "Das Konto aus der Datei ist keinem angelegten Konto zugeordnet – IBAN beim Konto "
                       "hinterlegen oder beim Hochladen ein Zielkonto wählen.",
    "account_archived": "Das Zielkonto ist archiviert.",
    "institution_mismatch": "Das Konto gehört zu einer anderen Bank als das Importprofil.",
    "loan_account_via_loans": "Buchungen auf Kreditkonten werden über die Kreditverwaltung erfasst.",
    "processing_aborted": "Die Verarbeitung wurde mehrfach abgebrochen – „Erneut versuchen“ startet sie neu.",
    "internal_error": "Interner Fehler bei der Verarbeitung.",
}
COMPARED = ("delimiter", "encoding", "date_format", "decimal_sep", "thousands_sep", "sign_mode")


def _detail(error: dict, profile: ImportProfile) -> str:
    text = EXPLANATIONS.get(error.get("code"), error.get("message", ""))
    details = error.get("details") or []
    if error.get("code") == "row_errors" and details:
        date_rows = [d for d in details if "Format" in str(d.get("message", ""))]
        if date_rows:
            text += (f" Das Datum in {len(date_rows)} Zeile(n) passt nicht zum Format "
                     f"„{profile.date_format}“ des Profils (z. B. Zeile {date_rows[0].get('row')}).")
        else:
            text += f" Erste betroffene Zeile: {details[0].get('row')} – {details[0].get('message')}"
    elif error.get("code") == "parse_error":
        text += f" {error.get('message', '')}"
    return text


def diagnose(session: Session, user: User, batch: ImportBatch) -> dict:
    profile = session.get(ImportProfile, batch.import_profile_id)
    items = [{"code": e.get("code"), "message": e.get("message"), "explanation": _detail(e, profile)}
             for e in (batch.errors or [])]
    fix = None
    codes = {e.get("code") for e in batch.errors or []}
    if profile.format == "csv" and codes & {"row_errors", "parse_error"}:
        try:
            content = stored_file(batch.stored_path).read_bytes()
            detected = detect_csv(content)
        except Exception:  # Diagnose darf nie selbst scheitern
            detected = None
        if detected is not None and detected.safe:
            changes = {k: detected.options[k] for k in COMPARED if getattr(profile, k) != detected.options[k]}
            missing = {c for spec in profile.column_map.values() for c in ([spec] if isinstance(spec, str) else [])}
            if missing - set(detected.header):
                changes["column_map"] = detected.options["column_map"]
            if changes:
                fix = {"changes": changes, "suggestion_id": _fix_suggestion(session, user, batch, profile, changes).id}
    return {"batch_id": batch.id, "status": batch.status, "items": items, "fix": fix}


def _fix_suggestion(session: Session, user: User, batch: ImportBatch, profile: ImportProfile, changes: dict):
    fingerprint = f"batch:{batch.id}|{json.dumps(changes, sort_keys=True)}"
    existing = session.exec(select(Suggestion).where(
        Suggestion.user_id == user.id, Suggestion.kind == SuggestionKind.IMPORT_PROFILE_FIX,
        Suggestion.fingerprint == fingerprint)).first()
    if existing is not None:
        return existing
    readable = ", ".join(f"{k}: {profile.column_map if k == 'column_map' else getattr(profile, k)!r} → {v!r}"
                         for k, v in changes.items())
    suggestion = Suggestion(
        user_id=user.id, kind=SuggestionKind.IMPORT_PROFILE_FIX, fingerprint=fingerprint,
        payload={"profile_id": profile.id, "profile_name": profile.name, "batch_id": batch.id, "changes": changes},
        evidence={"batch_id": batch.id}, reason=f"Die Datei liest sich fehlerfrei mit: {readable}",
        generator="detect-v1", data_as_of=datetime.now(UTC),
    )
    session.add(suggestion)
    session.flush()
    return suggestion


def _fix_apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    profile = import_profiles.get_profile(session, user, suggestion.payload["profile_id"])
    import_profiles.update_profile(session, profile, dict(suggestion.payload["changes"]))
    return "import_profile", profile.id


def _fix_validate(session: Session, user: User, suggestion: Suggestion) -> None:
    if session.get(ImportProfile, suggestion.payload["profile_id"]) is None:
        raise Conflict("Das Importprofil gibt es nicht mehr", code="suggestion_stale")


suggestions.register(SuggestionKind.IMPORT_PROFILE_FIX, Handler(validate=_fix_validate, apply=_fix_apply))
_ = SuggestionStatus
