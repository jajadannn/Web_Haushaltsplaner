"""Tests der Import-Parser (CSV, OFX, MT940).

Zwei Teile:
- Katalog: Jede Datei aus `tests/fixtures/imports` wird mit den Optionen aus `catalog.py` geparst und gegen die
  unabhängig berechneten Erwartungen geprüft. Die Fixtures sind NACHGEBILDETE Beispiele, keine echten Bankexporte.
- Gezielte Einzeltests für `parse_amount`, `fingerprint`, `parse_details`, ParseError-Fälle und Randfälle.

Tests mit `xfail(strict=True)` dokumentieren bekannte Fehler im Parser-Code (`app/importers`). Sobald ein Fehler
behoben ist, schlägt der Test als "XPASS" fehl, und die Markierung kann entfernt werden.
"""

import copy
import re
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from app.importers.base import (
    ParsedRow,
    ParseError,
    ParseResult,
    compact_account,
    fingerprint,
    looks_like_iban,
    parse_amount,
)
from app.importers.csv_profile import CsvOptions, parse_csv
from app.importers.mt940 import parse_details, parse_mt940
from app.importers.ofx import parse_ofx
from app.services.iban import normalize_iban
from tests.fixtures.imports.catalog import ACCOUNT_A, ACCOUNT_B, FIXTURE_DIR, FIXTURES

FIXTURE_NAMES = sorted(FIXTURES)
UTF8_BOM = b"\xef\xbb\xbf"


# ------------------------------------------------------------------------------------------------- Hilfen
def read(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


def csv_options(name: str, **overrides) -> CsvOptions:
    """Profil aus dem Katalog (als Kopie, damit Tests nichts verändern), optional mit Überschreibungen."""
    options = copy.deepcopy(FIXTURES[name]["options"])
    options.update(overrides)
    return CsvOptions(**options)


def parse_fixture(name: str) -> ParseResult:
    spec = FIXTURES[name]
    content = read(name)
    if spec["format"] == "csv":
        return parse_csv(content, csv_options(name))
    if spec["format"] == "ofx":
        return parse_ofx(content)
    if spec["format"] == "mt940":
        return parse_mt940(content)
    raise AssertionError(f"{name}: unbekanntes Format {spec['format']!r}")


def field_value(row: ParsedRow, key: str):
    """Feldwert in der Schreibweise des Katalogs (Datum als ISO-String, Betrag als String)."""
    value = getattr(row, key)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def row_tuples(result: ParseResult) -> list[tuple]:
    return [(r.row_no, r.booking_date, r.amount, r.description, r.counterparty, r.counterparty_iban, r.own_account)
            for r in result.rows]


def fingerprints(name: str) -> list[str]:
    return [fingerprint(r.booking_date, r.amount, r.description, r.counterparty) for r in parse_fixture(name).rows]


GENERIC_HEADER = "Auftragskonto;Buchungstag;Valutadatum;Empfänger/Auftraggeber;IBAN;Verwendungszweck;Betrag;Waehrung"


def generic_csv(*lines: str) -> bytes:
    return "\n".join([GENERIC_HEADER, *lines]).encode("utf-8")


def generic_line(date_text: str = "05.01.2026", purpose: str = "Zweck", amount: str = "-1,00",
                 currency: str = "EUR") -> str:
    return f"{ACCOUNT_A};{date_text};{date_text};Muster;;{purpose};{amount};{currency}"


# ---------------------------------------------------------------------------------- Katalog: Ergebnis je Datei
def test_catalog_matches_files_on_disk():
    on_disk = {p.name for p in FIXTURE_DIR.iterdir() if p.suffix in {".csv", ".ofx", ".sta"}}
    assert on_disk == set(FIXTURES)


def test_catalog_entries_are_complete():
    first_keys = {"booking_date", "amount", "description", "counterparty", "counterparty_iban", "external_id"}
    expected_keys = {"rows", "sum", "errors", "error_rows", "pending_skipped", "statement_account", "own_accounts",
                     "first"}
    for name, spec in FIXTURES.items():
        assert spec["format"] in {"csv", "ofx", "mt940"}, name
        assert ("options" in spec) == (spec["format"] == "csv"), name
        expected = spec["expected"]
        assert expected_keys <= set(expected), name
        assert set(expected["first"]) == first_keys, name
        assert expected["errors"] == len(expected["error_rows"]), name
        assert expected["own_accounts"] == sorted(expected["own_accounts"]), name


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_summary(name):
    expected = FIXTURES[name]["expected"]
    result = parse_fixture(name)
    actual = {
        "rows": len(result.rows),
        "sum": sum((r.amount for r in result.rows), Decimal("0.00")),
        "errors": len(result.errors),
        "error_rows": [e.row_no for e in result.errors],
        "pending_skipped": result.pending_skipped,
        "statement_account": result.statement_account,
        "own_accounts": sorted({r.own_account for r in result.rows if r.own_account}),
    }
    wanted = {key: expected[key] for key in actual}
    wanted["sum"] = Decimal(wanted["sum"])
    assert actual == wanted


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_first_row(name):
    expected = FIXTURES[name]["expected"]["first"]
    first = parse_fixture(name).rows[0]
    assert {key: field_value(first, key) for key in expected} == expected


SAMPLES = [(name, row_no) for name in FIXTURE_NAMES for row_no in FIXTURES[name]["expected"].get("samples", {})]


@pytest.mark.parametrize(("name", "row_no"), SAMPLES, ids=[f"{name}-row{row_no}" for name, row_no in SAMPLES])
def test_fixture_sample_rows(name, row_no):
    expected = FIXTURES[name]["expected"]["samples"][row_no]
    rows = {r.row_no: r for r in parse_fixture(name).rows}
    assert row_no in rows, f"Zeile {row_no} wurde nicht geparst (vorhanden: {sorted(rows)})"
    assert {key: field_value(rows[row_no], key) for key in expected} == expected


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_parsed_rows_are_well_formed(name):
    result = parse_fixture(name)
    previous = 0
    for row in result.rows:
        assert row.row_no > previous
        previous = row.row_no
        assert isinstance(row.amount, Decimal)
        assert row.amount.as_tuple().exponent == -2
        assert row.amount != 0
        assert row.currency == "EUR"
        assert date(2026, 1, 1) <= row.booking_date <= date(2026, 2, 28)
        assert row.description.strip()
        assert row.raw
        for iban in (row.own_account, row.counterparty_iban):
            if iban:
                assert normalize_iban(iban) == iban
                assert iban.startswith("DE")
    if result.statement_account:
        assert normalize_iban(result.statement_account) == result.statement_account
    external_ids = [r.external_id for r in result.rows]
    if FIXTURES[name]["format"] == "ofx":
        assert all(external_ids)
        assert len(set(external_ids)) == len(external_ids)
    else:
        assert not any(external_ids)


# ------------------------------------------------------------------------------ Katalog: Eigenschaften der Dateien
# (Datei, Kodierung, hat BOM, Zeilenende) - die Kodierung ist Teil dessen, was die Fixtures prüfen sollen
FILE_FACTS = [
    ("generic_signed.csv", "utf-8", False, b"\n"),
    ("sparkasse_like.csv", "cp1252", False, b"\r\n"),
    ("dkb_like.csv", "utf-8", True, b"\n"),
    ("ing_like.csv", "latin-1", False, b"\r\n"),
    ("debit_credit.csv", "utf-8", False, b"\n"),
    ("indicator.csv", "utf-8", False, b"\n"),
    ("statement.ofx", "cp1252", False, b"\r\n"),
    ("multi_account.ofx", "utf-8", False, b"\r\n"),
    ("statement.sta", "utf-8", False, b"\r\n"),
    ("multi_account.sta", "cp1252", False, b"\r\n"),
]


@pytest.mark.parametrize(("name", "encoding", "bom", "newline"), FILE_FACTS, ids=[f[0] for f in FILE_FACTS])
def test_fixture_file_encoding_and_line_endings(name, encoding, bom, newline):
    data = read(name)
    assert data.startswith(UTF8_BOM) == bom
    assert any(byte > 127 for byte in data), "ohne Umlaute wäre die Kodierung nicht geprüft"
    if encoding == "utf-8":
        data.decode("utf-8")  # darf nicht fehlschlagen
    else:
        with pytest.raises(UnicodeDecodeError):
            data.decode("utf-8")
        data.decode(encoding)
    if newline == b"\r\n":
        assert data.count(b"\r\n") == data.count(b"\n") > 0
    else:
        assert b"\r" not in data


def test_sparkasse_like_contains_cp1252_only_character():
    data = read("sparkasse_like.csv")
    assert b"\x80" in data  # "€" in cp1252 (in latin-1 gäbe es dieses Zeichen nicht)
    assert "Einkauf mit Gutschein 20 € Grünfeld" in data.decode("cp1252")


def test_dkb_like_has_preamble_with_spaced_iban_and_blank_line():
    lines = read("dkb_like.csv").decode("utf-8-sig").splitlines()
    assert lines[0] == '"Girokonto";"DE89 3704 0044 0532 0130 00"'
    assert lines[1].startswith('"Zeitraum:"')
    assert lines[2].startswith('"Kontostand vom')
    assert lines[3] == ""
    assert lines[4].startswith('"Buchungsdatum";"Wertstellung";"Status"')
    assert not any("Auftragskonto" in line for line in lines)


def test_ing_like_has_long_preamble_and_duplicate_currency_column():
    lines = read("ing_like.csv").decode("latin-1").splitlines()
    assert lines[3] == "IBAN;DE89 3704 0044 0532 0130 00"
    header = lines[14].split(";")
    assert header.count("Währung") == 2
    assert lines[13] == ""


IBAN_DE = re.compile(r"(?<![A-Za-z])DE\d{2}(?: ?\d{4}){4} ?\d{2}(?!\d)")
WITHOUT_IBAN = {"indicator.csv"}  # absichtlich ganz ohne IBAN (weder Kontospalte noch Vorspann)
IBAN_FOREIGN = re.compile(r"(?<![A-Za-z])(?!DE)[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,}")


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_ibans_are_german_and_have_valid_checksums(name):
    text = read(name).decode("latin-1")  # IBANs sind ASCII, latin-1 kann jedes Byte lesen
    found = [re.sub(r"\s+", "", match) for match in IBAN_DE.findall(text)]
    assert found or name in WITHOUT_IBAN, "jede Fixture enthält mindestens eine IBAN"
    for iban in found:
        assert normalize_iban(iban) == iban
    assert not IBAN_FOREIGN.findall(text)


# ---------------------------------------------------------------- Katalog: Dateien für Dublettentests
def test_dedup_a_has_exactly_one_pair_of_identical_rows():
    result = parse_fixture("dedup_a.csv")
    pairs = {fp: n for fp, n in Counter(fingerprints("dedup_a.csv")).items() if n > 1}
    assert list(pairs.values()) == [2]
    twins = [r for r in result.rows if r.booking_date == date(2026, 1, 5)]
    assert len(twins) == 2
    twin_1, twin_2 = twins
    assert (twin_1.description, twin_1.counterparty, twin_1.amount) == (
        twin_2.description, twin_2.counterparty, twin_2.amount)
    assert (twin_1.description, twin_1.counterparty, twin_1.amount) == (
        "Kartenzahlung Brötchen", "Bäckerei Krume", Decimal("-3.50"))
    assert min(r.booking_date for r in result.rows) == date(2026, 1, 2)
    assert max(r.booking_date for r in result.rows) == date(2026, 1, 15)


def test_dedup_b_overlaps_dedup_a_from_10_to_15_january_and_has_new_rows_after():
    def key(r):  # alles, was eine Zeile ausmacht
        return (r.booking_date, r.value_date, r.amount, r.description, r.counterparty, r.counterparty_iban,
                r.own_account)

    rows_a = parse_fixture("dedup_a.csv").rows
    rows_b = parse_fixture("dedup_b.csv").rows
    overlap_a = [key(r) for r in rows_a if date(2026, 1, 10) <= r.booking_date <= date(2026, 1, 15)]
    overlap_b = [key(r) for r in rows_b if r.booking_date <= date(2026, 1, 15)]
    assert overlap_a == overlap_b
    assert len(overlap_a) == 4
    # auch die Rohzeilen sind Byte für Byte gleich (die vier Zeilen der Überlappung stehen am Ende von dedup_a)
    assert read("dedup_b.csv").splitlines()[1:5] == read("dedup_a.csv").splitlines()[-4:]
    new_b = [r for r in rows_b if r.booking_date >= date(2026, 1, 16)]
    assert new_b
    assert not {key(r) for r in new_b} & {key(r) for r in rows_a}
    assert min(r.booking_date for r in rows_b) == date(2026, 1, 10)
    assert max(r.booking_date for r in rows_b) == date(2026, 1, 31)
    assert len(set(fingerprints("dedup_b.csv"))) == len(rows_b)  # in dedup_b keine identischen Zeilen


def test_partial_files_each_hold_one_of_two_identical_payments():
    fp_1, fp_2 = fingerprints("partial_1.csv"), fingerprints("partial_2.csv")
    assert len(set(fp_1)) == len(fp_1)
    assert len(set(fp_2)) == len(fp_2)
    shared = set(fp_1) & set(fp_2)
    assert shared == {fingerprint(date(2026, 1, 20), Decimal("-3.50"), "Kartenzahlung Brötchen", "Bäckerei Krume")}


def test_fixtures_do_not_collide_by_accident():
    """Gleiche Zeilen (Fingerprint) in verschiedenen Dateien gibt es nur dort, wo sie Absicht sind."""
    allowed = {frozenset({"dedup_a.csv", "dedup_b.csv"}), frozenset({"partial_1.csv", "partial_2.csv"})}
    seen: dict[str, set[str]] = {}
    for name in FIXTURE_NAMES:
        for fp in fingerprints(name):
            seen.setdefault(fp, set()).add(name)
    shared = {frozenset(files) for files in seen.values() if len(files) > 1}
    assert shared <= allowed


# ----------------------------------------------------------------------------------------------- parse_amount
@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        ("1.234,56", {}, "1234.56"),
        ("-0,01", {}, "-0.01"),
        ("12,50-", {}, "-12.50"),
        ("+3,00", {}, "3.00"),
        ("1234.56", {"decimal_sep": ".", "thousands_sep": ","}, "1234.56"),
        ("1,234.56", {"decimal_sep": ".", "thousands_sep": ","}, "1234.56"),
        ("€ 5,00", {}, "5.00"),
        ("5,00 €", {}, "5.00"),
        ("EUR 5,00", {}, "5.00"),
        ("-1.234,56", {}, "-1234.56"),
        ("1.234.567,89", {}, "1234567.89"),
        ("1234,56", {}, "1234.56"),
        ("1 234,56", {}, "1234.56"),
        ("1\u00a0234,56", {}, "1234.56"),
        ("  42,00  ", {}, "42.00"),
        ("5", {}, "5.00"),
        ("5,5", {}, "5.50"),
        ("0", {}, "0.00"),
        ("-3.50", {"decimal_sep": ".", "thousands_sep": ""}, "-3.50"),
        ("9999999999,99", {}, "9999999999.99"),
    ],
)
def test_parse_amount_valid(text, kwargs, expected):
    result = parse_amount(text, **kwargs)
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)
    assert str(result) == expected  # immer zwei Nachkommastellen


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("1,234", "mehr als zwei Nachkommastellen"),
        ("abc", "keine Zahl"),
        ("", "keine Zahl"),
        ("   ", "keine Zahl"),
        ("12,", "keine Zahl"),
        ("1,2,3", "keine Zahl"),
        ("--5,00", "keine Zahl"),
        ("zwölf Euro", "keine Zahl"),
        ("10000000000,00", "zu groß"),
    ],
)
def test_parse_amount_invalid(text, message):
    with pytest.raises(ValueError, match=message):
        parse_amount(text)


def test_parse_amount_never_uses_float():
    # 0.1 + 0.2 darf nicht durch Gleitkomma verfälscht werden: der Text wird direkt in Decimal gewandelt
    assert parse_amount("0,10") + parse_amount("0,20") == Decimal("0.30")
    assert parse_amount("1234567890,12") == Decimal("1234567890.12")


# ----------------------------------------------------------------------------------------------- Kontokennung
def test_compact_account_and_looks_like_iban():
    assert compact_account(" de89 3704 0044 0532 0130 00 ") == ACCOUNT_A
    assert compact_account("   ") is None
    assert compact_account(None) is None
    assert looks_like_iban(ACCOUNT_A)
    assert not looks_like_iban("37040044/0532013000")
    assert not looks_like_iban(None)


# ------------------------------------------------------------------------------------------------ fingerprint
class TestFingerprint:
    DAY = date(2026, 1, 5)
    BASE = fingerprint(DAY, Decimal("-3.50"), "Kartenzahlung Brötchen", "Bäckerei Krume")

    def test_is_stable_sha256_hex(self):
        assert re.fullmatch(r"[0-9a-f]{64}", self.BASE)
        assert fingerprint(self.DAY, Decimal("-3.50"), "Kartenzahlung Brötchen", "Bäckerei Krume") == self.BASE

    def test_case_and_whitespace_do_not_matter(self):
        shouted = fingerprint(self.DAY, Decimal("-3.50"), "KARTENZAHLUNG   brötchen ", "  bäckerei \t KRUME")
        assert shouted == self.BASE

    def test_casefold_handles_german_sharp_s(self):
        assert fingerprint(self.DAY, Decimal("-3.50"), "Großeinkauf", None) == fingerprint(
            self.DAY, Decimal("-3.50"), "GROSSEINKAUF", None)

    def test_missing_counterparty_equals_empty_counterparty(self):
        without = fingerprint(self.DAY, Decimal("-3.50"), "x", None)
        assert without == fingerprint(self.DAY, Decimal("-3.50"), "x", "  ")

    @pytest.mark.parametrize(
        ("booking", "amount", "description", "counterparty"),
        [
            (date(2026, 1, 6), Decimal("-3.50"), "Kartenzahlung Brötchen", "Bäckerei Krume"),
            (date(2026, 1, 5), Decimal("-3.51"), "Kartenzahlung Brötchen", "Bäckerei Krume"),
            (date(2026, 1, 5), Decimal("3.50"), "Kartenzahlung Brötchen", "Bäckerei Krume"),
            (date(2026, 1, 5), Decimal("-3.50"), "Kartenzahlung Brot", "Bäckerei Krume"),
            (date(2026, 1, 5), Decimal("-3.50"), "Kartenzahlung Brötchen", "Bäckerei Kruste"),
            (date(2026, 1, 5), Decimal("-3.50"), "Kartenzahlung Brötchen", None),
        ],
        ids=["date", "amount", "sign", "description", "counterparty", "no-counterparty"],
    )
    def test_any_real_difference_changes_it(self, booking, amount, description, counterparty):
        assert fingerprint(booking, amount, description, counterparty) != self.BASE


# ----------------------------------------------------------------------------------------------- parse_details
def full_length_details() -> tuple[str, str, str]:
    """Voll ausgeschöpftes :86: (alle Unterfelder maximal lang) samt erwartetem Zweck und Namen."""
    purpose = [chr(ord("a") + n) * 27 for n in range(10)] + [chr(ord("p") + n) * 27 for n in range(4)]
    lines = ["166?00" + "A" * 27, "?10" + "9" * 10]
    lines += [f"?{20 + n}{part}" for n, part in enumerate(purpose[:10])]
    lines += ["?30" + "B" * 11, f"?31{ACCOUNT_B}", "?32" + "N" * 27, "?33" + "M" * 27, "?34166"]
    lines += [f"?{60 + n}{part}" for n, part in enumerate(purpose[10:])]
    return "\r\n".join(lines), "".join(purpose), "N" * 27 + "M" * 27


MULTILINE_SVWZ = (
    "105?00LASTSCHRIFT?10931\n"
    "?20EREF+0102STW00471\n"
    "?21MREF+STWMANDAT-4711\n"
    "?22CRED+DE98ZZZ09999999999\n"
    "?23SVWZ+Abschlag Strom Janu\n"
    "?24ar 2026 Kd-Nr 4711\n"
    "?30TESTDEFFXXX\n"
    "?31DE33123456780000000101\n"
    "?32Stadtwerke Musterhausen"
)


def test_parse_details_multiline_svwz_over_several_subfields():
    assert parse_details(MULTILINE_SVWZ) == {
        "posting_text": "LASTSCHRIFT",
        "purpose": "Abschlag Strom Januar 2026 Kd-Nr 4711",
        "name": "Stadtwerke Musterhausen",
        "iban": "DE33123456780000000101",
    }


def test_parse_details_line_break_inside_a_subfield_is_ignored():
    details = "166?00ÜBERWEISUNG?20SVWZ+Abschlag Strom Ja\nnuar 2026?32Stadtwerke Muster\nhausen"
    parsed = parse_details(details)
    assert parsed["purpose"] == "Abschlag Strom Januar 2026"
    assert parsed["name"] == "Stadtwerke Musterhausen"


def test_parse_details_svwz_ends_at_the_next_sepa_key():
    parsed = parse_details("105?00LASTSCHRIFT?20SVWZ+Miete Januar?21EREF+ABC123?22MREF+M-1")
    assert parsed["purpose"] == "Miete Januar"


def test_parse_details_key_before_svwz_is_dropped_and_text_after_it_kept():
    parsed = parse_details("105?00LASTSCHRIFT?20EREF+NOTPROVIDED?21KREF+K1?22SVWZ+Rechnung 4711")
    assert parsed["purpose"] == "Rechnung 4711"


def test_parse_details_without_sepa_keys_joins_purpose_subfields_directly():
    parsed = parse_details("166?00ÜBERWEISUNG?20Rechnung 4711 vom 05.?2101.2026 bezahlt?60 mit Dank?61 und Gruß")
    assert parsed["posting_text"] == "ÜBERWEISUNG"
    assert parsed["purpose"] == "Rechnung 4711 vom 05.01.2026 bezahlt mit Dank und Gruß"


def test_parse_details_collapses_whitespace():
    assert parse_details("166?00X?20Strom   Januar \t 2026")["purpose"] == "Strom Januar 2026"


def test_parse_details_falls_back_to_posting_text_without_purpose():
    parsed = parse_details("808?00Kontoführung")
    assert parsed == {"posting_text": "Kontoführung", "purpose": "Kontoführung", "name": None, "iban": None}


def test_parse_details_uses_all_purpose_subfields_20_to_29_and_60_to_63():
    details, purpose, name = full_length_details()
    parsed = parse_details(details.replace("\r\n", "\n"))
    assert parsed == {"posting_text": "A" * 27, "purpose": purpose, "name": name, "iban": ACCOUNT_B}


def test_parse_details_name_is_joined_from_32_and_33():
    parsed = parse_details("166?00X?20Z?32Hausverwaltung Müller & Söh?33ne GmbH")
    assert parsed["name"] == "Hausverwaltung Müller & Söhne GmbH"
    assert parse_details("166?00X?20Z?33Nur Zeile zwei")["name"] == "Nur Zeile zwei"


def test_parse_details_iban_is_compacted_and_uppercased():
    assert parse_details("166?00X?20Z?31de33 1234 5678 0000 0001 01")["iban"] == "DE33123456780000000101"


@pytest.mark.parametrize("details", ["", "166", "kein Unterfeld hier"])
def test_parse_details_without_subfields_is_empty(details):
    assert parse_details(details) == {"posting_text": "", "purpose": "", "name": None, "iban": None}


# ---------------------------------------------------------------------------------------------- CSV: Einzelfälle
def test_csv_line_endings_do_not_matter():
    data = read("generic_signed.csv")
    options = csv_options("generic_signed.csv")
    assert row_tuples(parse_csv(data.replace(b"\n", b"\r\n"), options)) == row_tuples(parse_csv(data, options))


def test_csv_blank_lines_are_skipped_but_keep_line_numbers():
    data = generic_csv(generic_line(), "", generic_line("06.01.2026"), "", "")
    result = parse_csv(data, csv_options("generic_signed.csv"))
    assert [r.row_no for r in result.rows] == [2, 4]
    assert not result.errors


def test_csv_short_row_is_a_row_error_and_does_not_stop_the_file():
    data = generic_csv(generic_line(), f"{ACCOUNT_A};06.01.2026", generic_line("07.01.2026"))
    result = parse_csv(data, csv_options("generic_signed.csv"))
    assert [r.row_no for r in result.rows] == [2, 4]
    assert [e.row_no for e in result.errors] == [3]


def test_csv_empty_description_gets_placeholder():
    result = parse_csv(generic_csv(generic_line(purpose="")), csv_options("generic_signed.csv"))
    assert result.rows[0].description == "(ohne Verwendungszweck)"


def test_csv_error_messages_name_the_problem():
    data = generic_csv(generic_line("31.02.2026"), generic_line(amount="zwölf Euro"), generic_line(currency="USD"))
    result = parse_csv(data, csv_options("generic_signed.csv"))
    messages = [e.message for e in result.errors]
    assert [e.row_no for e in result.errors] == [2, 3, 4]
    assert "Buchungsdatum" in messages[0]
    assert "Betrag" in messages[1]
    assert "USD" in messages[2]


def test_csv_duplicate_header_first_column_wins():
    options = CsvOptions(column_map={"booking_date": "Buchung", "description": "Zweck", "amount": "Betrag",
                                     "currency": "Währung"})
    eur_first = "Buchung;Zweck;Währung;Betrag;Währung\n05.01.2026;Test;EUR;-1,00;USD\n".encode()
    usd_first = "Buchung;Zweck;Währung;Betrag;Währung\n05.01.2026;Test;USD;-1,00;EUR\n".encode()
    assert [r.currency for r in parse_csv(eur_first, options).rows] == ["EUR"]
    result = parse_csv(usd_first, options)
    assert not result.rows
    assert "USD" in result.errors[0].message


DEBIT_CREDIT_HEADER = "Datum;Valuta;Auftraggeber;Empfänger;IBAN Gegenkonto;Buchungstext;Soll;Haben"


def test_csv_debit_credit_columns_need_exactly_one_value():
    data = "\n".join([
        DEBIT_CREDIT_HEADER,
        "05.01.2026;05.01.2026;;X;;beide gefüllt;1,00;2,00",
        "06.01.2026;06.01.2026;;X;;beide leer;;",
        "07.01.2026;07.01.2026;;X;;nur Soll;3,00;",
        "08.01.2026;08.01.2026;Y;;;nur Haben;;4,00",
    ]).encode()
    result = parse_csv(data, csv_options("debit_credit.csv"))
    assert [e.row_no for e in result.errors] == [2, 3]
    assert all("Soll/Haben" in e.message for e in result.errors)
    assert [r.amount for r in result.rows] == [Decimal("-3.00"), Decimal("4.00")]
    assert [r.counterparty for r in result.rows] == ["X", "Y"]


def test_csv_debit_credit_amounts_are_taken_as_absolute_values():
    data = f"{DEBIT_CREDIT_HEADER}\n05.01.2026;05.01.2026;;X;;Test;-5,00;\n06.01.2026;06.01.2026;Y;;;Test;;-6,00\n"
    result = parse_csv(data.encode(), csv_options("debit_credit.csv"))
    assert [r.amount for r in result.rows] == [Decimal("-5.00"), Decimal("6.00")]


def test_csv_indicator_column_is_case_insensitive_and_amount_sign_is_ignored():
    data = (b"Datum,Valuta,Name,Verwendungszweck,Betrag,S/H\n"
            b"2026-01-05,2026-01-05,X,Z,10.00,s\n"
            b"2026-01-05,2026-01-05,X,Z,10.00,h\n"
            b"2026-01-05,2026-01-05,X,Z,-10.00,S\n")
    result = parse_csv(data, csv_options("indicator.csv"))
    assert [r.amount for r in result.rows] == [Decimal("-10.00"), Decimal("10.00"), Decimal("-10.00")]


def test_csv_pending_values_are_case_insensitive():
    options = CsvOptions(column_map={"booking_date": "Datum", "status": "Status", "amount": "Betrag",
                                     "description": "Zweck"}, pending_values=["Vorgemerkt"])
    data = b"Datum;Status;Betrag;Zweck\n05.01.2026;VORGEMERKT;-1,00;a\n06.01.2026;gebucht;-2,00;b\n"
    result = parse_csv(data, options)
    assert (len(result.rows), result.pending_skipped) == (1, 1)
    assert result.rows[0].row_no == 3


def test_csv_only_pending_rows_is_not_an_error():
    options = CsvOptions(column_map={"booking_date": "Datum", "status": "Status", "amount": "Betrag"},
                         pending_values=["Vorgemerkt"])
    result = parse_csv(b"Datum;Status;Betrag\n05.01.2026;Vorgemerkt;-1,00\n", options)
    assert (len(result.rows), result.pending_skipped) == (0, 1)


def test_csv_skip_rows_is_the_first_row_searched_for_the_header():
    data = read("dkb_like.csv")  # Kopfzeile steht auf Zeilenindex 4
    result = parse_csv(data, csv_options("dkb_like.csv", skip_rows=4))
    assert len(result.rows) == 7
    assert result.statement_account == ACCOUNT_A  # IBAN im übersprungenen Vorspann zählt trotzdem
    with pytest.raises(ParseError, match="Kopfzeile nicht gefunden"):
        parse_csv(data, csv_options("dkb_like.csv", skip_rows=5))


def test_csv_utf8_bom_in_front_of_the_header_is_ignored():
    data = read("generic_signed.csv")
    with_bom = parse_csv(UTF8_BOM + data, csv_options("generic_signed.csv"))
    assert row_tuples(with_bom) == row_tuples(parse_csv(data, csv_options("generic_signed.csv")))


@pytest.mark.parametrize("encoding", ["UTF-8", "utf8", "UTF_8", "utf-8-sig"])
def test_csv_utf8_aliases_strip_the_bom(encoding):
    result = parse_csv(read("dkb_like.csv"), csv_options("dkb_like.csv", encoding=encoding))
    assert len(result.rows) == 7


def test_csv_statement_account_comes_only_from_the_preamble():
    result = parse_csv(read("generic_signed.csv"), csv_options("generic_signed.csv"))
    assert result.statement_account is None  # IBANs in den Datenzeilen sind Gegenkonten
    result = parse_csv(read("ing_like.csv"), csv_options("ing_like.csv"))
    assert result.statement_account == ACCOUNT_A


# ------------------------------------------------------------------------------------------- OFX: Einzelfälle
OFX_HEADER = ("OFXHEADER:100\r\nDATA:OFXSGML\r\nVERSION:102\r\nSECURITY:NONE\r\nENCODING:USASCII\r\nCHARSET:1252\r\n"
              "COMPRESSION:NONE\r\nOLDFILEUID:NONE\r\nNEWFILEUID:NONE\r\n\r\n")


def leaf(tag: str, value: str, xml: bool) -> str:
    return f"<{tag}>{value}</{tag}>" if xml else f"<{tag}>{value}"


def ofx_transaction(fitid="F1", posted="20260102", amount="-1.00", name="Muster", memo="Zweck", *, xml=False) -> str:
    """Eine Buchung (SGML oder XML); ein Wert von None lässt das Feld weg."""
    fields = [("TRNTYPE", "DEBIT"), ("DTPOSTED", posted), ("TRNAMT", amount), ("FITID", fitid), ("NAME", name),
              ("MEMO", memo)]
    inner = "".join(leaf(tag, value, xml) + "\r\n" for tag, value in fields if value is not None)
    return "<STMTTRN>\r\n" + inner + "</STMTTRN>\r\n"


def ofx_statement(transactions: str, account: str | None = ACCOUNT_A, curdef: str = "EUR", *, xml=False) -> str:
    status = ("<STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>" if xml
              else "<STATUS><CODE>0<SEVERITY>INFO</STATUS>")
    acctid = leaf("ACCTID", account, xml) + "\r\n" if account else ""
    return ("<STMTTRNRS>\r\n" + leaf("TRNUID", "1", xml) + "\r\n" + status + "\r\n<STMTRS>\r\n"
            + leaf("CURDEF", curdef, xml) + "\r\n<BANKACCTFROM>\r\n" + leaf("BANKID", "37040044", xml) + "\r\n"
            + acctid + leaf("ACCTTYPE", "CHECKING", xml) + "\r\n</BANKACCTFROM>\r\n<BANKTRANLIST>\r\n"
            + transactions + "</BANKTRANLIST>\r\n</STMTRS>\r\n</STMTTRNRS>\r\n")


def ofx_file(*statements: str, header: str = OFX_HEADER, encoding: str = "cp1252") -> bytes:
    body = ("<OFX>\r\n<SIGNONMSGSRSV1>\r\n<SONRS>\r\n<STATUS><CODE>0<SEVERITY>INFO</STATUS>\r\n"
            "<DTSERVER>20260203120000\r\n<LANGUAGE>GER\r\n</SONRS>\r\n</SIGNONMSGSRSV1>\r\n<BANKMSGSRSV1>\r\n"
            + "".join(statements) + "</BANKMSGSRSV1>\r\n</OFX>\r\n")
    return (header + body).encode(encoding)


def ofx2_file(*statements: str, encoding: str = "utf-8") -> bytes:
    """OFX 2.x (XML): Endtags überall, XML-Deklaration statt SGML-Kopfzeilen (Konten mit xml=True erzeugen)."""
    return (f'<?xml version="1.0" encoding="{encoding.upper()}"?>\r\n'
            '<?OFX OFXHEADER="200" VERSION="211" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>\r\n'
            "<OFX><SIGNONMSGSRSV1><SONRS><STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>"
            "<DTSERVER>20260203120000</DTSERVER></SONRS></SIGNONMSGSRSV1><BANKMSGSRSV1>"
            + "".join(statements) + "</BANKMSGSRSV1></OFX>\r\n").encode(encoding)


def test_ofx_multi_account_returns_both_accounts():
    result = parse_ofx(read("multi_account.ofx"))
    assert result.statement_account is None  # mehrere Konten: keine eindeutige Kontoangabe im Kopf
    assert [r.own_account for r in result.rows] == [ACCOUNT_A] * 3 + [ACCOUNT_B] * 3
    assert [r.row_no for r in result.rows] == [1, 2, 3, 4, 5, 6]
    assert Counter(r.own_account for r in result.rows) == {ACCOUNT_A: 3, ACCOUNT_B: 3}
    assert sum(r.amount for r in result.rows if r.own_account == ACCOUNT_A) == Decimal("1870.10")
    assert sum(r.amount for r in result.rows if r.own_account == ACCOUNT_B) == Decimal("173.21")


def test_ofx_line_endings_do_not_matter():
    data = read("statement.ofx")
    assert row_tuples(parse_ofx(data.replace(b"\r\n", b"\n"))) == row_tuples(parse_ofx(data))


def test_ofx_name_and_memo_fallbacks():
    data = ofx_file(ofx_statement(
        ofx_transaction("A", name=None, memo="nur Memo") + ofx_transaction("B", name="nur Name", memo=None)
        + ofx_transaction("C", name=None, memo=None)))
    rows = parse_ofx(data).rows
    assert [(r.description, r.counterparty) for r in rows] == [
        ("nur Memo", None), ("nur Name", "nur Name"), ("(ohne Verwendungszweck)", None)]


def test_ofx_account_without_acctid_has_no_own_account():
    result = parse_ofx(ofx_file(ofx_statement(ofx_transaction(), account=None)))
    assert result.statement_account is None
    assert result.rows[0].own_account is None


def test_ofx_amount_formats():
    data = ofx_file(ofx_statement(
        ofx_transaction("A", amount="+12.5") + ofx_transaction("B", amount="-1.234,56")
        + ofx_transaction("C", amount="100")))
    assert [r.amount for r in parse_ofx(data).rows] == [Decimal("12.50"), Decimal("-1234.56"), Decimal("100.00")]


@pytest.mark.filterwarnings("ignore::bs4.XMLParsedAsHTMLWarning")
def test_ofx_xml_2x_with_ascii_text_and_two_accounts():
    statements = (ofx_statement(ofx_transaction("A1", memo="Strom", xml=True), ACCOUNT_A, xml=True)
                  + ofx_statement(ofx_transaction("B1", amount="5.00", memo="Zinsen", xml=True), ACCOUNT_B, xml=True))
    result = parse_ofx(ofx2_file(statements))
    assert result.statement_account is None
    assert [(r.own_account, r.external_id, r.amount, r.description) for r in result.rows] == [
        (ACCOUNT_A, "A1", Decimal("-1.00"), "Strom"), (ACCOUNT_B, "B1", Decimal("5.00"), "Zinsen")]


@pytest.mark.filterwarnings("ignore::bs4.XMLParsedAsHTMLWarning")
def test_ofx_xml_2x_with_umlauts_in_utf8():
    statement = ofx_statement(ofx_transaction(name="Müller", memo="Größe", xml=True), xml=True)
    result = parse_ofx(ofx2_file(statement))
    assert (result.rows[0].counterparty, result.rows[0].description) == ("Müller", "Größe")


def test_ofx_dtposted_with_timezone_keeps_the_bank_date():
    result = parse_ofx(ofx_file(ofx_statement(ofx_transaction(posted="20260102000000[+1:CET]"))))
    assert result.rows[0].booking_date == date(2026, 1, 2)


@pytest.mark.parametrize("posted", ["20260102", "20260102120000", "20260102000000", "20260102000000.000[0:GMT]"])
def test_ofx_dtposted_variants_without_offset(posted):
    result = parse_ofx(ofx_file(ofx_statement(ofx_transaction(posted=posted))))
    assert result.rows[0].booking_date == date(2026, 1, 2)


def test_ofx_foreign_currency_is_rejected():
    with pytest.raises(ParseError, match="USD"):
        parse_ofx(ofx_file(ofx_statement(ofx_transaction(), curdef="USD")))


def test_ofx_unreadable_amount_is_reported_cleanly():
    try:
        result = parse_ofx(ofx_file(ofx_statement(ofx_transaction(amount="-3.505"))))
    except ParseError:
        return  # sauberer Abbruch ist in Ordnung
    assert len(result.errors) == 1  # ebenso eine Fehlerzeile


def test_ofx_truncated_file_is_rejected():
    data = read("statement.ofx")
    cut = data[: data.index(b"<FITID>20260108")]
    with pytest.raises(ParseError):
        parse_ofx(cut)


# --------------------------------------------------------------------------------------- MT940: Einzelfälle
def mt940_entry(line61: str, field86: str | None = None) -> str:
    return f":61:{line61}\r\n" + (f":86:{field86}\r\n" if field86 is not None else "")


def mt940_text(*entries: str, account: str = ACCOUNT_A) -> str:
    return (f":20:TEST\r\n:25:{account}\r\n:28C:00001/001\r\n:60F:C260101EUR100,00\r\n" + "".join(entries)
            + ":62F:C260131EUR100,00\r\n-\r\n")


def mt940_rows(*entries: str) -> list[ParsedRow]:
    return parse_mt940(mt940_text(*entries).encode()).rows


def test_mt940_multi_account_statements_are_kept_apart():
    result = parse_mt940(read("multi_account.sta"))
    assert result.statement_account is None
    assert [r.own_account for r in result.rows] == [ACCOUNT_A] * 3 + [ACCOUNT_B] * 3
    assert [r.row_no for r in result.rows] == [1, 2, 3, 4, 5, 6]
    assert sum(r.amount for r in result.rows if r.own_account == ACCOUNT_A) == Decimal("1804.40")
    assert sum(r.amount for r in result.rows if r.own_account == ACCOUNT_B) == Decimal("224.07")


def test_mt940_crlf_and_lf_give_the_same_result():
    data = read("statement.sta")
    assert b"\r\n" in data
    assert row_tuples(parse_mt940(data.replace(b"\r\n", b"\n"))) == row_tuples(parse_mt940(data))


def test_mt940_decodes_utf8_and_falls_back_to_cp1252():
    utf8 = parse_mt940(read("statement.sta")).rows
    cp1252 = parse_mt940(read("multi_account.sta")).rows
    assert utf8[3].counterparty == "Café Östlich"
    assert cp1252[0].description == "Wochenendeinkauf Grünfeld"
    assert cp1252[4].description == "Anteil Wochenendreise Größe"


@pytest.mark.parametrize(("mark", "expected"), [("D", "-10.00"), ("C", "10.00"), ("RD", "10.00")])
def test_mt940_debit_credit_marks(mark, expected):
    (row,) = mt940_rows(mt940_entry(f"2601020102{mark}10,00NMSCNONREF", "166?00X?20Text"))
    assert row.amount == Decimal(expected)


def test_mt940_reversal_of_credit_is_negative():
    (row,) = mt940_rows(mt940_entry("2601040104RC30,00NMSCNONREF", "166?00STORNO?20Storno Gutschrift"))
    assert row.amount == Decimal("-30.00")


def test_mt940_booking_date_is_entry_date_and_value_date_is_kept():
    (row,) = mt940_rows(mt940_entry("2512310102D10,00NMSCNONREF", "166?00X?20Jahreswechsel"))
    assert (row.booking_date, row.value_date) == (date(2026, 1, 2), date(2025, 12, 31))


def test_mt940_counterparty_iban_only_if_it_looks_like_an_iban():
    (row,) = mt940_rows(mt940_entry("2601020102D10,00NMSCNONREF", "166?00X?20Text?30370400440?310532013000?32Name"))
    assert (row.counterparty, row.counterparty_iban) == ("Name", None)


def test_mt940_entry_without_details_gets_placeholder():
    (row,) = mt940_rows(mt940_entry("2601020102D10,00NMSCNONREF"))
    assert (row.description, row.counterparty, row.counterparty_iban) == ("(ohne Verwendungszweck)", None, None)


def test_mt940_two_entries_stay_two_transactions():
    rows = mt940_rows(mt940_entry("2601020102D10,00NMSCNONREF", "166?00A?20Eins"),
                      mt940_entry("2601030103C20,00NTRFNONREF", "051?00B?20Zwei"))
    assert [(r.amount, r.description) for r in rows] == [(Decimal("-10.00"), "Eins"), (Decimal("20.00"), "Zwei")]


def test_mt940_full_length_details_are_not_truncated():
    details, purpose, name = full_length_details()
    (row,) = mt940_rows(mt940_entry("2601020102D10,00NMSCNONREF", details))
    assert row.counterparty == name
    assert row.counterparty_iban == ACCOUNT_B
    assert row.description == purpose


def test_mt940_space_at_the_end_of_a_subfield_line_is_kept():
    details = "166?00LASTSCHRIFT\r\n?20SVWZ+Abschlag Strom \r\n?21Januar 2026"
    (row,) = mt940_rows(mt940_entry("2601020102D10,00NMSCNONREF", details))
    assert row.description == "Abschlag Strom Januar 2026"


def test_mt940_utf8_bom_does_not_drop_the_first_statement():
    text = (mt940_text(mt940_entry("2601020102D10,00NMSCNONREF", "166?00A?20Eins"), account=ACCOUNT_A)
            + mt940_text(mt940_entry("2601050105C15,00NMSCNONREF", "166?00B?20Zwei"), account=ACCOUNT_B))
    result = parse_mt940(UTF8_BOM + text.encode("utf-8"))
    assert [r.own_account for r in result.rows] == [ACCOUNT_A, ACCOUNT_B]


# ------------------------------------------------------------------------------------------ ParseError-Fälle
def test_csv_missing_header_column_raises():
    options = copy.deepcopy(FIXTURES["generic_signed.csv"]["options"])
    options["column_map"]["amount"] = "Gibt es nicht"
    with pytest.raises(ParseError, match=r"Kopfzeile nicht gefunden.*Gibt es nicht"):
        parse_csv(read("generic_signed.csv"), CsvOptions(**options))


def test_csv_header_not_in_the_first_40_rows_raises():
    data = ("Vorspann\n" * 45 + GENERIC_HEADER + "\n" + generic_line() + "\n").encode()
    with pytest.raises(ParseError, match="Kopfzeile nicht gefunden"):
        parse_csv(data, csv_options("generic_signed.csv"))


def test_csv_header_within_the_first_40_rows_is_found():
    data = ("Vorspann\n" * 39 + GENERIC_HEADER + "\n" + generic_line() + "\n").encode()
    assert len(parse_csv(data, csv_options("generic_signed.csv")).rows) == 1


def test_csv_wrong_delimiter_raises():
    with pytest.raises(ParseError, match="Kopfzeile nicht gefunden"):
        parse_csv(read("generic_signed.csv"), csv_options("generic_signed.csv", delimiter=","))


def test_csv_wrong_encoding_raises():
    # cp1252-Datei mit Umlauten, Profil sagt utf-8
    with pytest.raises(ParseError, match="Zeichenkodierung"):
        parse_csv(read("sparkasse_like.csv"), csv_options("sparkasse_like.csv", encoding="utf-8"))
    with pytest.raises(ParseError, match="Zeichenkodierung"):
        parse_csv(read("ing_like.csv"), csv_options("ing_like.csv", encoding="utf-8"))


def test_csv_unknown_encoding_name_raises():
    with pytest.raises(ParseError, match="Zeichenkodierung"):
        parse_csv(read("generic_signed.csv"), csv_options("generic_signed.csv", encoding="gibt-es-nicht"))


def test_csv_empty_file_raises():
    for content in (b"", b"\n\n", b"\xef\xbb\xbf"):
        with pytest.raises(ParseError):
            parse_csv(content, csv_options("generic_signed.csv"))


def test_csv_header_only_raises():
    with pytest.raises(ParseError, match="keine Umsätze"):
        parse_csv(generic_csv(), csv_options("generic_signed.csv"))


def test_csv_profile_without_booking_date_raises():
    options = copy.deepcopy(FIXTURES["generic_signed.csv"]["options"])
    del options["column_map"]["booking_date"]
    with pytest.raises(ParseError, match="Buchungsdatum"):
        parse_csv(read("generic_signed.csv"), CsvOptions(**options))


def test_csv_profile_with_invalid_column_spec_raises():
    options = copy.deepcopy(FIXTURES["generic_signed.csv"]["options"])
    options["column_map"]["description"] = 5
    with pytest.raises(ParseError, match="Spaltenangabe"):
        parse_csv(read("generic_signed.csv"), CsvOptions(**options))


@pytest.mark.parametrize("content", [b"", b"\n\n", b"   \r\n"], ids=["empty", "newlines", "blanks"])
def test_ofx_and_mt940_empty_file_raises(content):
    with pytest.raises(ParseError):
        parse_ofx(content)
    with pytest.raises(ParseError):
        parse_mt940(content)


@pytest.mark.parametrize(
    "content",
    [
        b"Das ist keine OFX-Datei",
        b"a:b:c\r\n\r\n<foo>",
        b"\x00\x01\x02\xff\xfe binary",
        b"<html><body>Anmeldung erforderlich</body></html>",
    ],
    ids=["text", "colons", "binary", "html"],
)
def test_ofx_broken_file_raises(content):
    with pytest.raises(ParseError):
        parse_ofx(content)


def test_ofx_transaction_without_required_field_raises():
    for transactions in (ofx_transaction(fitid=None), ofx_transaction(amount=None), ofx_transaction(posted=None)):
        with pytest.raises(ParseError):
            parse_ofx(ofx_file(ofx_statement(transactions)))


def test_ofx_without_account_raises():
    with pytest.raises(ParseError, match="kein Konto"):
        parse_ofx(ofx_file(""))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"Das ist kein MT940", "Keine MT940"),
        (mt940_text().encode(), "keine Umsätze"),
        (mt940_text(mt940_entry("XYZ", "166?00X")).encode(), "nicht lesbar"),
        (mt940_text(mt940_entry("2602300230D10,00NMSCNONREF", "166?00X")).encode(), "nicht lesbar"),
        (mt940_text(mt940_entry("2601020102D10,00NMSCNONREF", "166?00X")).replace("EUR", "USD").encode(), "USD"),
        (b"\x00\x01\x02\x03", "Keine MT940"),
    ],
    ids=["text", "no-entries", "bad-61", "impossible-date", "usd", "binary"],
)
def test_mt940_broken_file_raises(content, message):
    with pytest.raises(ParseError, match=message):
        parse_mt940(content)
