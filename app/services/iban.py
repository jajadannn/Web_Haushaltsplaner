import re

from app.errors import Invalid

# Längen der häufigsten Länder; andere Länder nur Format + Prüfsumme
_LENGTHS = {"DE": 22, "AT": 20, "CH": 21, "NL": 18, "BE": 16, "FR": 27, "IT": 27, "ES": 24, "LU": 20}


def normalize_iban(raw: str) -> str:
    """Entfernt Leerzeichen, prüft Format, Länderlänge und Prüfsumme (ISO 13616, mod 97)."""
    iban = re.sub(r"\s+", "", raw).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        raise Invalid("IBAN hat ein ungültiges Format", code="invalid_iban")
    expected = _LENGTHS.get(iban[:2])
    if expected and len(iban) != expected:
        raise Invalid(f"IBAN für {iban[:2]} muss {expected} Zeichen haben", code="invalid_iban")
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    if int(digits) % 97 != 1:
        raise Invalid("IBAN-Prüfsumme ist ungültig", code="invalid_iban")
    return iban
