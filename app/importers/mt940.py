"""MT940-Kontoauszüge (SWIFT) über die Bibliothek mt-940.

MT940 enthält keine verlässliche Buchungs-ID; Dubletten werden über den Fingerprint gesucht.
Jede Auszugsnachricht (`:20:`) wird einzeln gelesen, damit die Kontoangabe (`:25:`)
je Auszug erhalten bleibt (Dateien mit mehreren Konten).
"""

import re
from decimal import Decimal

import mt940

from app.importers.base import ParsedRow, ParseError, ParseResult, compact_account, looks_like_iban

_STATEMENT_START = re.compile(r"(?m)^:20:")
_SUBFIELD = re.compile(r"\?(\d{2})")
_TAG_LINE = re.compile(r"^(:\d{2}[A-Z]?:|-)")
# Platzhalter für Leerzeichen am Zeilenende im :86:-Feld – die Bibliothek entfernt sonst
# Leerzeichen am Zeilenende, und Wörter an Unterfeldgrenzen kleben zusammen
_LINE_END_SPACE = "\ue000"
_OPTIONS = mt940.Options(
    reversal_sign=True,  # RC (Storno einer Gutschrift) ist ein Abfluss
    unbounded_details=True,  # :86: nicht nach 9 × 65 Zeichen abschneiden
    case_insensitive_marks=True,
)
_SEPA_KEYS = re.compile(r"(EREF|KREF|MREF|CRED|DEBT|COAM|OAMT|SVWZ|ABWA|ABWE|IBAN|BIC)\+")


def parse_details(details: str) -> dict:
    """Zerlegt das deutsche :86:-Feld (?00 Buchungstext, ?20–?29/?60–?63 Verwendungszweck,
    ?31 IBAN, ?32/?33 Name). Bei SEPA-Schlüsseln zählt der Text hinter SVWZ+."""
    text = details.replace("\n", "").replace(_LINE_END_SPACE, " ")
    parts = _SUBFIELD.split(text)
    fields: dict[str, str] = {}
    for code, value in zip(parts[1::2], parts[2::2], strict=False):
        fields[code] = fields.get(code, "") + value
    purpose = "".join(fields.get(f"{n:02d}", "") for n in [*range(20, 30), *range(60, 64)])
    if "SVWZ+" in purpose:
        purpose = _SEPA_KEYS.split(purpose.split("SVWZ+", 1)[1])[0]
    return {
        "posting_text": fields.get("00", "").strip(),
        "purpose": " ".join(purpose.split()) or fields.get("00", "").strip(),
        "name": " ".join((fields.get("32", "") + fields.get("33", "")).split()) or None,
        "iban": compact_account(fields.get("31")),
    }


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError("MT940-Datei hat eine unbekannte Zeichenkodierung")


def _keep_line_end_spaces(text: str) -> str:
    """Leerzeichen am Zeilenende innerhalb von :86: durch einen Platzhalter sichern."""
    lines, in_details = [], False
    for line in text.split("\n"):
        if _TAG_LINE.match(line):
            in_details = line.startswith(":86:")
        stripped = line.rstrip(" ")
        if in_details and stripped != line:
            line = stripped + _LINE_END_SPACE
        lines.append(line)
    return "\n".join(lines)


def _statements(text: str) -> list[str]:
    starts = [m.start() for m in _STATEMENT_START.finditer(text)]
    if not starts:
        raise ParseError("Keine MT940-Auszüge (:20:) gefunden")
    return [text[a:b] for a, b in zip(starts, [*starts[1:], len(text)], strict=True)]


def parse_mt940(content: bytes) -> ParseResult:
    text = _keep_line_end_spaces(_decode(content).replace("\r\n", "\n"))
    result = ParseResult(rows=[], errors=[])
    accounts: set[str] = set()
    row_no = 0
    for chunk in _statements(text):
        try:
            # Eigene :86:-Auswertung statt der Bibliotheks-Nachverarbeitung
            statement = mt940.models.Transactions(
                processors={"post_transaction_details": []}, options=_OPTIONS
            )
            statement.parse(chunk)
        except Exception as exc:  # Bibliothek wirft unterschiedliche Fehlertypen
            raise ParseError(f"MT940-Auszug nicht lesbar: {exc}") from exc
        own = compact_account(statement.data.get("account_identification"))
        if own:
            accounts.add(own)
        for tx in statement:
            row_no += 1
            data = tx.data
            amount = data["amount"]
            if (amount.currency or "EUR").upper() != "EUR":
                raise ParseError(f"Währung {amount.currency} wird nicht unterstützt (nur EUR)")
            booking = data.get("entry_date") or data["date"]
            details = parse_details(data.get("transaction_details") or "")
            result.rows.append(
                ParsedRow(
                    row_no=row_no,
                    booking_date=booking,
                    value_date=data.get("date"),
                    amount=amount.amount.quantize(Decimal("0.01")),
                    description=details["purpose"] or "(ohne Verwendungszweck)",
                    counterparty=details["name"],
                    counterparty_iban=details["iban"] if looks_like_iban(details["iban"]) else None,
                    own_account=own,
                    raw={k: str(v) for k, v in data.items() if v is not None},
                )
            )
    if len(accounts) == 1:
        result.statement_account = next(iter(accounts))
    if not result.rows:
        raise ParseError("MT940-Datei enthält keine Umsätze")
    return result
