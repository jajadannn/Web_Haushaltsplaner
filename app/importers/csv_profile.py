"""Profilgesteuerter CSV-Parser für Bankexporte.

`column_map` ordnet Felder den Spaltenüberschriften zu:
- booking_date (Pflicht), value_date, currency, external_id, own_account, status
- amount (sign_mode `signed` bzw. `indicator_column`), debit + credit
  (`debit_credit_columns`), indicator (`indicator_column`, Werte in `debit_indicators`)
- description: Spalte oder Liste von Spalten (werden mit Leerzeichen verbunden)
- counterparty / counterparty_iban: Spalte, Liste (erste nicht leere) oder
  {"debit": ..., "credit": ...} – je nach Richtung (z. B. Empfänger bei Abbuchungen)
Die Kopfzeile wird gesucht (Vorspann wie Kontostand/IBAN wird übersprungen); eine IBAN
im Vorspann gilt als eigenes Konto.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.importers.base import (
    ParsedRow,
    ParseError,
    ParseResult,
    RowError,
    compact_account,
    looks_like_iban,
    parse_amount,
)

HEADER_SEARCH_ROWS = 40


@dataclass
class CsvOptions:
    column_map: dict
    delimiter: str = ";"
    encoding: str = "utf-8"
    skip_rows: int = 0
    date_format: str = "%d.%m.%Y"
    decimal_sep: str = ","
    thousands_sep: str = "."
    sign_mode: str = "signed"
    debit_indicators: list[str] = field(default_factory=list)
    pending_values: list[str] = field(default_factory=list)


def _columns(spec) -> list[str]:
    if spec is None:
        return []
    if isinstance(spec, str):
        return [spec]
    if isinstance(spec, list):
        return list(spec)
    if isinstance(spec, dict):
        return [v for v in (spec.get("debit"), spec.get("credit")) if v]
    raise ParseError(f"Ungültige Spaltenangabe: {spec!r}")


def required_columns(options: CsvOptions) -> list[str]:
    names: list[str] = []
    for spec in options.column_map.values():
        names.extend(_columns(spec))
    return list(dict.fromkeys(names))


def _decode(content: bytes, encoding: str) -> str:
    codec = "utf-8-sig" if encoding.lower().replace("_", "-") in ("utf-8", "utf8") else encoding
    try:
        return content.decode(codec)
    except (UnicodeDecodeError, LookupError) as exc:
        raise ParseError(f"Datei lässt sich nicht als {encoding} lesen – Zeichenkodierung im Profil prüfen") from exc


def _find_header(rows: list[list[str]], options: CsvOptions) -> int:
    wanted = set(required_columns(options))
    for index in range(options.skip_rows, min(len(rows), options.skip_rows + HEADER_SEARCH_ROWS)):
        cells = {cell.strip() for cell in rows[index]}
        if wanted <= cells:
            return index
    raise ParseError(
        "Kopfzeile nicht gefunden – erwartet werden die Spalten: " + ", ".join(sorted(wanted))
    )


def _preamble_account(rows: list[list[str]]) -> str | None:
    for row in rows:
        for cell in row:
            candidate = compact_account(cell)
            if looks_like_iban(candidate):
                return candidate
    return None


class _Row:
    def __init__(self, header: list[str], values: list[str]):
        self.values = {}
        for name, value in zip(header, values, strict=False):
            self.values.setdefault(name.strip(), value.strip())  # doppelte Überschrift: erste zählt

    def get(self, column: str | None) -> str:
        return self.values.get(column, "") if column else ""

    def pick(self, spec, outgoing: bool) -> str:
        if isinstance(spec, dict):
            return self.get(spec.get("debit") if outgoing else spec.get("credit"))
        if isinstance(spec, list):
            return next((v for v in (self.get(c) for c in spec) if v), "")
        return self.get(spec)


def _parse_date(value: str, fmt: str, label: str) -> date:
    try:
        return datetime.strptime(value, fmt).date()
    except ValueError as exc:
        raise ValueError(f"{label} '{value}' passt nicht zum Format {fmt}") from exc


def _amount(row: _Row, options: CsvOptions) -> Decimal:
    cmap = options.column_map

    def number(column: str) -> Decimal:
        return parse_amount(row.get(column), options.decimal_sep, options.thousands_sep)

    if options.sign_mode == "debit_credit_columns":
        debit, credit = row.get(cmap.get("debit")), row.get(cmap.get("credit"))
        if bool(debit) == bool(credit):
            raise ValueError("Genau eine der Spalten Soll/Haben muss gefüllt sein")
        return -abs(number(cmap["debit"])) if debit else abs(number(cmap["credit"]))
    value = number(cmap.get("amount"))
    if options.sign_mode == "indicator_column":
        indicator = row.get(cmap.get("indicator")).casefold()
        if not indicator:
            raise ValueError("Soll/Haben-Kennzeichen fehlt")
        debit_values = {v.casefold() for v in options.debit_indicators}
        return -abs(value) if indicator in debit_values else abs(value)
    return value


def parse_csv(content: bytes, options: CsvOptions) -> ParseResult:
    if "booking_date" not in options.column_map:
        raise ParseError("Profil ordnet keine Spalte für das Buchungsdatum zu")
    text = _decode(content, options.encoding)
    reader = csv.reader(io.StringIO(text), delimiter=options.delimiter)
    rows, line_numbers, previous_end = [], [], 0
    for values in reader:
        rows.append(values)
        line_numbers.append(previous_end + 1)  # Startzeile in der Datei, auch bei Umbrüchen in Anführungszeichen
        previous_end = reader.line_num
    header_index = _find_header(rows, options)
    header = [cell.strip() for cell in rows[header_index]]
    cmap = options.column_map
    pending_values = {v.casefold() for v in options.pending_values}

    result = ParseResult(rows=[], errors=[], statement_account=_preamble_account(rows[:header_index]))
    for line_no, values in zip(line_numbers[header_index + 1 :], rows[header_index + 1 :], strict=True):
        if not any(cell.strip() for cell in values):
            continue
        row = _Row(header, values)
        if pending_values and row.get(cmap.get("status")).casefold() in pending_values:
            result.pending_skipped += 1
            continue
        try:
            amount = _amount(row, options)
            outgoing = amount < 0
            currency = (row.get(cmap.get("currency")) or "EUR").upper()
            if currency != "EUR":
                raise ValueError(f"Währung {currency} wird nicht unterstützt (nur EUR)")
            description = " ".join(v for v in (row.get(c) for c in _columns(cmap.get("description"))) if v)
            value_date = row.get(cmap.get("value_date"))
            parsed = ParsedRow(
                row_no=line_no,
                booking_date=_parse_date(row.get(cmap["booking_date"]), options.date_format, "Buchungsdatum"),
                value_date=_parse_date(value_date, options.date_format, "Wertstellung") if value_date else None,
                amount=amount,
                currency=currency,
                description=description or "(ohne Verwendungszweck)",
                counterparty=row.pick(cmap.get("counterparty"), outgoing) or None,
                counterparty_iban=compact_account(row.pick(cmap.get("counterparty_iban"), outgoing)),
                external_id=row.get(cmap.get("external_id")) or None,
                own_account=compact_account(row.get(cmap.get("own_account"))),
                raw=row.values,
            )
        except ValueError as exc:
            result.errors.append(RowError(line_no, str(exc)))
            continue
        result.rows.append(parsed)
    if not result.rows and not result.errors and not result.pending_skipped:
        raise ParseError("Datei enthält keine Umsätze")
    return result
