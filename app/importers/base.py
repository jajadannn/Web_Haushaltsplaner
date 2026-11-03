"""Gemeinsames Ergebnisformat aller Parser (CSV, OFX, MT940)."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

PARSER_VERSION = "1"
MAX_AMOUNT = Decimal("9999999999.99")


class ParseError(Exception):
    """Die Datei als Ganzes ist unlesbar oder passt nicht zum Profil."""


@dataclass
class ParsedRow:
    row_no: int
    booking_date: date
    amount: Decimal
    description: str
    value_date: date | None = None
    currency: str = "EUR"
    counterparty: str | None = None
    counterparty_iban: str | None = None
    external_id: str | None = None
    own_account: str | None = None  # IBAN oder Kontoreferenz des eigenen Kontos
    raw: dict = field(default_factory=dict)


@dataclass
class RowError:
    row_no: int
    message: str


@dataclass
class ParseResult:
    rows: list[ParsedRow]
    errors: list[RowError]
    # Eigenes Konto aus Kopfdaten (Vorspann, OFX-Konto, MT940-Kontoangabe)
    statement_account: str | None = None
    # Vorgemerkte (noch nicht gebuchte) Umsätze werden übersprungen, nur gezählt
    pending_skipped: int = 0


def parse_amount(text: str, decimal_sep: str = ",", thousands_sep: str = ".") -> Decimal:
    """Betrag direkt aus Text, nie über float; höchstens 2 Nachkommastellen."""
    cleaned = text.strip().replace(" ", "").replace(" ", "").replace("€", "").replace("EUR", "")
    negative = False
    if cleaned.endswith("-"):  # z. B. "12,50-"
        negative, cleaned = True, cleaned[:-1]
    if thousands_sep:
        cleaned = cleaned.replace(thousands_sep, "")
    if decimal_sep != ".":
        cleaned = cleaned.replace(decimal_sep, ".")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", cleaned):
        raise ValueError(f"Betrag '{text}' ist keine Zahl")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Betrag '{text}' ist keine Zahl") from exc
    if value.as_tuple().exponent < -2:
        raise ValueError(f"Betrag '{text}' hat mehr als zwei Nachkommastellen")
    if abs(value) > MAX_AMOUNT:
        raise ValueError(f"Betrag '{text}' ist zu groß")
    value = value.quantize(Decimal("0.01"))
    return -value if negative else value


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def fingerprint(booking_date: date, amount: Decimal, description: str, counterparty: str | None) -> str:
    """Suchhilfe für Dubletten ohne Bank-ID – ausdrücklich KEINE eindeutige Identität."""
    cents = amount.quantize(Decimal("0.01"))  # -3.5 und -3.50 sind derselbe Betrag
    key = f"{booking_date.isoformat()}|{cents}|{normalize_text(description)}|{normalize_text(counterparty)}"
    return hashlib.sha256(key.encode()).hexdigest()


IBAN_PATTERN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


def compact_account(value: str | None) -> str | None:
    """Kontokennung vereinheitlichen (Leerzeichen raus, Großbuchstaben)."""
    if not value:
        return None
    compact = re.sub(r"\s+", "", value).upper()
    return compact or None


def looks_like_iban(value: str | None) -> bool:
    return bool(value) and bool(IBAN_PATTERN.match(value))


_BLZ_ACCOUNT = re.compile(r"^(\d{8})/(\d{1,10})$")


def _iban_checksum_ok(iban: str) -> bool:
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def german_iban(blz: str, account_number: str) -> str:
    """Deutsche IBAN aus Bankleitzahl und Kontonummer (ISO 13616, Prüfziffer mod 97)."""
    bban = blz + account_number.zfill(10)
    check = 98 - int(bban + "131400") % 97  # „DE00“ → 13 14 00
    return f"DE{check:02d}{bban}"


def statement_account(value: str | None) -> str | None:
    """Kontoangabe einer Auszugsdatei (MT940 `:25:`) vereinheitlichen.

    Deutsche Banken schreiben dort oft „BLZ/Kontonummer“ statt der IBAN, teils mit der
    Währung dahinter („37040044/0532013000EUR“, „DE89…EUR“). Daraus wird die IBAN, damit
    die Datei zum angelegten Konto passt.
    """
    compact = compact_account(value)
    if compact is None:
        return None
    candidates = [compact]
    if compact.endswith("EUR"):
        candidates.append(compact[:-3])
    for candidate in candidates:
        if match := _BLZ_ACCOUNT.match(candidate):
            return german_iban(*match.groups())
        if looks_like_iban(candidate) and _iban_checksum_ok(candidate):
            return candidate
    return compact


def german_account_number(value: str | None) -> str | None:
    """Kontonummer ohne führende Nullen aus einer deutschen IBAN oder einer reinen Nummer."""
    if not value:
        return None
    if len(value) == 22 and value.startswith("DE") and value[2:].isdigit():
        return value[12:].lstrip("0") or "0"
    if value.isdigit():
        return value.lstrip("0") or "0"
    return None
