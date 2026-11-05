"""Aufbau einer CSV-Datei erkennen und daraus einen Importprofil-Entwurf machen (Idee 11).

Deterministisch: Kodierung, Trennzeichen, Kopfzeile (Vorspann wird übersprungen), Spaltenrollen
über Namen deutscher/englischer Bankexporte und Inhaltsprüfung, Datums- und Zahlenformat aus
Stichproben, Vorzeichenmodus (Vorzeichen, Soll/Haben-Spalten oder S/H-Kennzeichen), vorgemerkte
Umsätze. Der Entwurf wird anschließend mit dem echten Parser gegen die ganze Datei geprüft –
nur ein fehlerfrei lesbarer Entwurf gilt als sicher. Spalten, deren Rolle unklar bleibt, werden
als `uncertain` gemeldet (dort kann die KI oder der Nutzer helfen).
"""

import csv
import io
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.importers.base import ParseError, compact_account, looks_like_iban
from app.importers.csv_profile import CsvOptions, parse_csv

DELIMITERS = (";", ",", "\t", "|")
DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d")
ROLES = ("booking_date", "value_date", "amount", "debit", "credit", "indicator", "counterparty",
         "counterparty_iban", "description", "currency", "own_account", "status", "external_id", "ignore")

# Normalisierte Spaltennamen → Rolle (Reihenfolge = Vorrang)
SYNONYMS: dict[str, tuple[str, ...]] = {
    "booking_date": ("buchungstag", "buchungsdatum", "buchung", "datum", "bookingdate", "date", "transaktionsdatum"),
    "value_date": ("valutadatum", "valuta", "wertstellung", "wertstellungsdatum", "valuedate"),
    "indicator": ("sh", "sollhaben", "kennzeichen", "soll haben"),
    "debit": ("soll", "debit", "ausgang", "belastung", "lastschrift betrag"),
    "credit": ("haben", "credit", "eingang", "gutschrift"),
    "amount": ("betrag", "betrageur", "umsatz", "amount", "betraginmeur", "umsatzineur", "betrag eur"),
    "counterparty_iban": ("iban", "kontonummeriban", "ibangegenkonto", "gegenkonto", "ibanzahlungsbeteiligter",
                          "kontonummer", "counterpartyiban"),
    "counterparty": ("empfaengerauftraggeber", "empfängerauftraggeber", "beguenstigterzahlungspflichtiger",
                     "begünstigterzahlungspflichtiger", "auftraggeberempfänger", "auftraggeberempfaenger",
                     "name", "gegenpartei", "payee", "beteiligter",
                     "zahlungsbeteiligter"),
    "description": ("verwendungszweck", "buchungstext", "beschreibung", "purpose", "text", "vorgang", "details"),
    "currency": ("waehrung", "währung", "currency"),
    "own_account": ("auftragskonto", "konto", "eigeneskonto", "kontoiban"),
    "status": ("status", "info", "umsatzstatus", "buchungsstatus"),
    "external_id": ("umsatzid", "transaktionsid", "buchungsid", "transactionid"),
}
PENDING_WORDS = ("vorgemerkt", "nicht gebucht", "pending", "ausstehend", "offen")
DEBIT_WORDS = {"s", "soll", "d", "debit", "lastschrift", "-"}


def _norm(name: str) -> str:
    return re.sub(r"[^a-zäöüß]", "", name.casefold())


@dataclass
class Detection:
    options: dict
    header: list[str]
    roles: dict[str, object]
    uncertain: list[str] = field(default_factory=list)
    unassigned: list[str] = field(default_factory=list)
    rows_parsed: int = 0
    errors: list[dict] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)
    statement_account: str | None = None
    safe: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _encoding(content: bytes) -> str:
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8"
    try:
        content.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def _rows(text: str, delimiter: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _table(text: str) -> tuple[str, int, list[list[str]]]:
    """(Trennzeichen, Index der Kopfzeile, Zeilen) – die Variante mit der längsten einheitlichen Tabelle."""
    best = None
    for delimiter in DELIMITERS:
        rows = _rows(text, delimiter)
        widths = [len(r) for r in rows if any(c.strip() for c in r)]
        if not widths:
            continue
        width = Counter(w for w in widths if w >= 3).most_common(1)
        if not width:
            continue
        width = width[0][0]
        header = next((i for i, r in enumerate(rows)
                       if len(r) == width and sum(1 for c in r if c.strip() and not re.search(r"\d", c)) >= width // 2),
                      None)
        if header is None:
            continue
        body = sum(1 for r in rows[header + 1:] if len(r) == width)
        score = (body, width)
        if best is None or score > best[0]:
            best = (score, delimiter, header, rows)
    if best is None:
        raise ParseError("Keine Tabelle erkannt – ist das eine CSV-Datei?")
    return best[1], best[2], best[3]


def _assign(header: list[str]) -> tuple[dict[str, object], list[str]]:
    roles: dict[str, object] = {}
    normalized = [_norm(h) for h in header]
    used: set[int] = set()
    for role, names in SYNONYMS.items():
        for name in names:
            matches = [i for i, n in enumerate(normalized) if i not in used and n == _norm(name)]
            if matches:
                roles[role] = header[matches[0]]
                used.add(matches[0])
                break
    # getrennte Spalten für Auftraggeber und Empfänger: je nach Richtung
    if "counterparty" not in roles:
        payer = next((header[i] for i, n in enumerate(normalized)
                      if n in ("auftraggeber", "zahler", "zahlungspflichtiger", "zahlungspflichtiger")
                      or n.startswith("zahlungspflichtige")), None)
        payee = next((header[i] for i, n in enumerate(normalized)
                      if n in ("empfänger", "empfaenger") or n.startswith("zahlungsempfänger")
                      or n.startswith("zahlungsempfaenger")), None)
        if payer and payee:
            roles["counterparty"] = {"debit": payee, "credit": payer}
            used |= {header.index(payer), header.index(payee)}
        elif payer or payee:
            roles["counterparty"] = payer or payee
            used.add(header.index(payer or payee))
    # Buchungstext und Verwendungszweck gemeinsam als Beschreibung
    texts = [header[i] for i, n in enumerate(normalized) if n in ("buchungstext", "verwendungszweck")]
    if len(texts) == 2:
        roles["description"] = texts
        used |= {header.index(t) for t in texts}
    unassigned = [h for i, h in enumerate(header) if i not in used and h.strip()]
    return roles, unassigned


def _samples(rows: list[list[str]], header: list[str], column: str, limit: int = 200) -> list[str]:
    index = header.index(column)
    return [r[index].strip() for r in rows if len(r) > index and r[index].strip()][:limit]


def _date_format(values: list[str]) -> tuple[str | None, bool]:
    fitting = []
    for fmt in DATE_FORMATS:
        try:
            for v in values:
                datetime.strptime(v, fmt)
            fitting.append(fmt)
        except ValueError:
            continue
    if not fitting:
        return None, False
    return fitting[0], len(fitting) == 1 or fitting[:2] == ["%d.%m.%Y", "%d.%m.%y"]


def _number_format(values: list[str]) -> tuple[str, str]:
    comma_dec = dot_dec = 0
    for v in values:
        v = re.sub(r"[^\d,.\-+]", "", v)
        if re.search(r",\d{1,2}$", v):
            comma_dec += 1
        elif re.search(r"\.\d{1,2}$", v):
            dot_dec += 1
    return (",", ".") if comma_dec >= dot_dec else (".", ",")


def _is_number(value: str, decimal_sep: str, thousands_sep: str) -> bool:
    cleaned = re.sub(r"[^\d,.\-+]", "", value).replace(thousands_sep, "").replace(decimal_sep, ".")
    try:
        Decimal(cleaned)
        return bool(cleaned)
    except InvalidOperation:
        return False


def detect_csv(content: bytes, roles_override: dict[str, object] | None = None) -> Detection:
    """`roles_override`: Spaltenrollen, die der Nutzer oder die KI festgelegt hat (Vorrang vor der Heuristik)."""
    encoding = _encoding(content)
    text = content.decode("utf-8-sig" if encoding == "utf-8" else encoding)
    delimiter, header_index, rows = _table(text)
    header = [c.strip() for c in rows[header_index]]
    body = [r for r in rows[header_index + 1:] if any(c.strip() for c in r)]
    roles, unassigned = _assign(header)
    for role, column in (roles_override or {}).items():
        columns = column if isinstance(column, list) else [column]
        if role in ROLES and role != "ignore" and all(isinstance(c, str) and c in header for c in columns):
            roles = {r: c for r, c in roles.items() if c != column}
            roles[role] = column
            unassigned = [h for h in unassigned if h not in columns]
    uncertain: list[str] = []

    date_fmt, sure = (None, False)
    if "booking_date" in roles:
        date_fmt, sure = _date_format(_samples(body, header, roles["booking_date"]))
        if date_fmt is None:
            uncertain.append("booking_date")
        elif not sure:
            uncertain.append("date_format")
    else:
        uncertain.append("booking_date")

    money_columns = [roles[r] for r in ("amount", "debit", "credit") if isinstance(roles.get(r), str)]
    samples = [v for c in money_columns for v in _samples(body, header, c)]
    decimal_sep, thousands_sep = _number_format(samples) if samples else (",", ".")

    if "debit" in roles and "credit" in roles:
        sign_mode, debit_indicators = "debit_credit_columns", []
        roles.pop("amount", None)
    elif "indicator" in roles and "amount" in roles:
        values = {v.casefold() for v in _samples(body, header, roles["indicator"])}
        sign_mode = "indicator_column"
        debit_indicators = sorted(v for v in values if v in DEBIT_WORDS) or ["s"]
        roles.pop("debit", None), roles.pop("credit", None)
    else:
        sign_mode, debit_indicators = "signed", []
        for role in ("debit", "credit", "indicator"):
            roles.pop(role, None)
        if "amount" not in roles:
            uncertain.append("amount")
    if isinstance(roles.get("amount"), str) and samples and not all(
        _is_number(v, decimal_sep, thousands_sep) for v in _samples(body, header, roles["amount"])
    ):
        uncertain.append("amount")

    # IBAN-Spalte inhaltlich prüfen; eigenes Konto nur, wenn es wie eine Kontonummer aussieht
    if isinstance(roles.get("counterparty_iban"), str):
        values = _samples(body, header, roles["counterparty_iban"])
        if values and not any(looks_like_iban(compact_account(v)) or v.isdigit() for v in values):
            unassigned.append(roles.pop("counterparty_iban"))
    pending_values: list[str] = []
    if isinstance(roles.get("status"), str):
        values = {v for v in _samples(body, header, roles["status"])}
        pending_values = sorted(v for v in values if any(w in v.casefold() for w in PENDING_WORDS))
    if "counterparty" not in roles:
        uncertain.append("counterparty")
    if "description" not in roles:
        uncertain.append("description")

    column_map = {k: v for k, v in roles.items() if k in ROLES and k != "ignore"}
    options = {
        "column_map": column_map,
        "delimiter": delimiter,
        "encoding": encoding,
        "skip_rows": 0,
        "date_format": date_fmt or "%d.%m.%Y",
        "decimal_sep": decimal_sep,
        "thousands_sep": thousands_sep,
        "sign_mode": sign_mode,
        "debit_indicators": debit_indicators,
        "pending_values": pending_values,
    }
    detection = Detection(options=options, header=header, roles=roles, uncertain=uncertain, unassigned=unassigned)
    return verify(content, detection)


def verify(content: bytes, detection: Detection) -> Detection:
    """Entwurf mit dem echten Parser gegen die ganze Datei prüfen; Vorschau der ersten zehn Zeilen."""
    try:
        result = parse_csv(content, CsvOptions(**detection.options))
    except ParseError as exc:
        detection.errors = [{"row_no": None, "message": str(exc)}]
        detection.safe = False
        return detection
    detection.rows_parsed = len(result.rows)
    detection.errors = [{"row_no": e.row_no, "message": e.message} for e in result.errors[:20]]
    detection.statement_account = result.statement_account
    detection.preview = [
        {"row_no": r.row_no, "booking_date": r.booking_date.isoformat(), "amount": str(r.amount),
         "counterparty": r.counterparty, "description": r.description}
        for r in result.rows[:10]
    ]
    required = {"booking_date", "description"} <= detection.options["column_map"].keys()
    detection.safe = bool(result.rows) and not result.errors and required and not (
        {"booking_date", "amount", "date_format"} & set(detection.uncertain)
    )
    return detection
