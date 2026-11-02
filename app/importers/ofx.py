"""OFX-Kontoauszüge (1.x SGML und 2.x XML) über ofxparse; FITID dient als Bank-ID.

Zwei Eigenheiten von ofxparse werden ausgeglichen:
- Dateien ohne passende Zeichensatzangabe (z. B. OFX 2.x in UTF-8) liest ofxparse als
  ASCII. Dann wird die Datei selbst dekodiert und als ASCII mit Zeichenreferenzen übergeben.
- DTPOSTED mit Zeitzone (z. B. `20260102000000[+1:CET]`) rechnet ofxparse nach UTC um;
  als Buchungstag zählt aber das Bankdatum, also die ersten acht Ziffern.
"""

import io
import re
from datetime import date

from ofxparse import OfxParser

from app.importers.base import (
    ParsedRow,
    ParseError,
    ParseResult,
    RowError,
    compact_account,
    parse_amount,
)

_TRANSACTION = re.compile(rb"<STMTTRN>(.*?)</STMTTRN>", re.IGNORECASE | re.DOTALL)
_POSTED = re.compile(rb"<DTPOSTED>\s*(\d{8})", re.IGNORECASE)


def _ascii_with_references(content: bytes) -> bytes:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding).encode("ascii", "xmlcharrefreplace")
        except UnicodeDecodeError:
            continue
    raise ParseError("OFX-Datei hat eine unbekannte Zeichenkodierung")


def _parse(content: bytes):
    try:
        return OfxParser.parse(io.BytesIO(content))
    except UnicodeDecodeError:
        return OfxParser.parse(io.BytesIO(_ascii_with_references(content)))


def _bank_dates(content: bytes) -> list[date | None]:
    """Buchungstage in Dokumentreihenfolge, so wie die Bank sie angibt."""
    dates = []
    for block in _TRANSACTION.findall(content):
        match = _POSTED.search(block)
        raw = match.group(1).decode() if match else None
        dates.append(date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])) if raw else None)
    return dates


def parse_ofx(content: bytes) -> ParseResult:
    if b"</OFX>" not in content.upper():
        raise ParseError("OFX-Datei ist unvollständig (</OFX> fehlt)")
    try:
        ofx = _parse(content)
    except ParseError:
        raise
    except Exception as exc:  # ofxparse wirft unterschiedliche Fehlertypen
        raise ParseError(f"OFX-Datei nicht lesbar: {exc}") from exc
    accounts = getattr(ofx, "accounts", None) or []
    if not accounts:
        raise ParseError("OFX-Datei enthält kein Konto")

    bank_dates = _bank_dates(content)
    total = sum(len(account.statement.transactions) for account in accounts)
    if len(bank_dates) != total:
        bank_dates = [None] * total  # Zuordnung unsicher – dann ofxparse-Datum verwenden

    result = ParseResult(rows=[], errors=[])
    row_no = 0
    for account in accounts:
        statement = account.statement
        currency = (getattr(statement, "currency", None) or "EUR").upper()
        if currency != "EUR":
            raise ParseError(f"Währung {currency} wird nicht unterstützt (nur EUR)")
        own = compact_account(account.account_id)
        for tx in statement.transactions:
            row_no += 1
            try:
                amount = parse_amount(str(tx.amount), ".", "")
            except ValueError as exc:
                result.errors.append(RowError(row_no, str(exc)))
                continue
            memo = (tx.memo or "").strip()
            payee = (tx.payee or "").strip()
            result.rows.append(
                ParsedRow(
                    row_no=row_no,
                    booking_date=bank_dates[row_no - 1] or tx.date.date(),
                    amount=amount,
                    description=memo or payee or "(ohne Verwendungszweck)",
                    counterparty=payee or None,
                    external_id=(tx.id or "").strip() or None,
                    own_account=own,
                    raw={"fitid": tx.id, "type": tx.type, "payee": tx.payee, "memo": tx.memo,
                         "date": tx.date.isoformat(), "amount": str(tx.amount), "account": account.account_id},
                )
            )
    if not result.rows and not result.errors:
        raise ParseError("OFX-Datei enthält keine Umsätze")
    if len(accounts) == 1:
        result.statement_account = compact_account(accounts[0].account_id)
    return result
