"""Katalog der anonymisierten Import-Fixtures (Dateien in diesem Ordner).

Zweck: Jede Datei hier ist ein kleiner Beispiel-Export für die Parser (CSV, OFX, MT940). `FIXTURES` nennt je Datei das
Format, bei CSV die Profil-Optionen (kwargs für `CsvOptions`) und das erwartete Ergebnis. Die Erwartungen wurden
unabhängig vom Parser aus den Quelldaten berechnet (Summen, Zeilennummern, Gegenparteien), nicht aus dessen Ausgabe.
Genutzt von `tests/unit/test_parsers.py`; auch für Import-Tests mit Datenbank gedacht.

WICHTIG: Die Bankformate sind NACHGEBILDET. Sie decken typische Eigenheiten deutscher Exporte ab (Kodierungen, Vorspann,
Datums- und Zahlenformate, Soll/Haben, Mehrkontodateien ...), sind aber NICHT mit echten Exporten verifiziert und
behaupten nicht, exakt einem echten Bankformat zu entsprechen. Dateinamen wie `dkb_like.csv` oder `ing_like.csv`
weisen nur auf den Stil hin. Alle Namen, Firmen und Texte sind frei erfunden; die IBANs sind synthetisch erzeugt
(gültige Prüfsumme, deutsche 22-stellige IBAN, aber keine echten Konten). Die eigenen Konten haben feste IBANs
(`ACCOUNT_A`, `ACCOUNT_B`). Alle Daten liegen im Januar/Februar 2026.

Aufbau eines Eintrags:
- "format": "csv" | "ofx" | "mt940"
- "description": was die Datei abdeckt
- "options": nur bei CSV, die kwargs für `CsvOptions` (nur nicht-Standardwerte von `skip_rows`, `pending_values` und
  `debit_indicators` sind aufgeführt)
- "expected":
  - "rows": Anzahl der geparsten Zeilen (ohne Fehler und ohne vorgemerkte Umsätze)
  - "sum": Summe aller geparsten Beträge als String
  - "errors", "error_rows": Anzahl und Zeilennummern der Fehlerzeilen (`ParseResult.errors`)
  - "pending_skipped": Anzahl übersprungener vorgemerkter Umsätze
  - "statement_account": eigenes Konto aus den Kopfdaten (Vorspann, OFX-Konto, MT940-Kontoangabe) oder None
  - "own_accounts": sortierte Liste der verschiedenen `own_account`-Werte der Zeilen (kann leer sein; sortiert nach
    IBAN-Text, bei zwei Konten steht also `ACCOUNT_B` vor `ACCOUNT_A`)
  - "first": Felder der ersten geparsten Zeile (`booking_date` als ISO-Datum, `amount` als String)
  - "samples" (zusätzlich, optional): ausgewählte weitere Zeilen, Schlüssel ist `row_no`, Werte sind die zu
    prüfenden Felder. `row_no` ist bei CSV die Zeilennummer in der Datei (1-basiert, Vorspann und Kopfzeile zählen
    mit), bei OFX und MT940 die laufende Nummer der Buchung über alle Konten der Datei.
"""

from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent

# Feste IBANs der eigenen Konten (Konto A: Girokonto, Konto B: Tagesgeld in den Mehrkontodateien)
ACCOUNT_A = "DE89370400440532013000"
ACCOUNT_B = "DE02120300000000202051"


def _generic_options() -> dict:
    """Profil des generischen Formats (Auftragskonto;Buchungstag;...;Betrag;Waehrung); jedes Mal frisch."""
    return {
        "column_map": {
            "own_account": "Auftragskonto",
            "booking_date": "Buchungstag",
            "value_date": "Valutadatum",
            "counterparty": "Empfänger/Auftraggeber",
            "counterparty_iban": "IBAN",
            "description": "Verwendungszweck",
            "amount": "Betrag",
            "currency": "Waehrung",
        },
        "delimiter": ";",
        "encoding": "utf-8",
        "date_format": "%d.%m.%Y",
        "decimal_sep": ",",
        "thousands_sep": ".",
        "sign_mode": "signed",
    }


FIXTURES: dict[str, dict] = {
    # --- CSV: Bankformate (nachgebildet) und Profilvarianten
    "generic_signed.csv": {
        "format": "csv",
        "description": (
            "Generisches CSV: UTF-8 ohne BOM, ';', Kopfzeile in Zeile 1, TT.MM.JJJJ, Beträge mit "
            "Vorzeichen und Tausenderpunkt, Umlaute, Semikolon im Verwendungszweck (in "
            "Anführungszeichen), ein Betrag mit '+', leere Valuta, eine abweichende Valuta, leere "
            "IBAN, IBAN mit Leerzeichen."
        ),
        "options": _generic_options(),
        "expected": {
            "rows": 11,
            "sum": "1114.42",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-02",
                "amount": "-89.00",
                "description": "Abschlag Strom Januar 2026 Kundennr 4711",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": "DE33123456780000000101",
                "external_id": None,
            },
            "samples": {
                5: {"description": "Beitrag; Haftpflicht Jahresbeitrag"},
                6: {"counterparty": "Café Östlich", "counterparty_iban": None, "value_date": None},
                7: {"counterparty": "Apotheke am Markt", "counterparty_iban": "DE52567890120000000501"},
                8: {"value_date": "2026-01-21"},
                9: {"amount": "25.00"},
                11: {"amount": "3456.78", "counterparty_iban": "DE57345678900000000301"},
                12: {"amount": "-1234.56"},
            },
        },
    },
    "sparkasse_like.csv": {
        "format": "csv",
        "description": (
            "CAMT-artiger Export: cp1252, CRLF, alle Felder in Anführungszeichen, TT.MM.JJ, "
            "Beträge ohne Tausenderpunkt, Beschreibung aus Buchungstext + Verwendungszweck, eine "
            "vorgemerkte Zeile ('Umsatz vorgemerkt', ohne Valuta), '€' und Umlaute "
            "(Kodierungstest), abweichende Valuta in einer Zeile."
        ),
        "options": {
            "column_map": {
                "own_account": "Auftragskonto",
                "booking_date": "Buchungstag",
                "value_date": "Valutadatum",
                "description": ["Buchungstext", "Verwendungszweck"],
                "counterparty": "Beguenstigter/Zahlungspflichtiger",
                "counterparty_iban": "Kontonummer/IBAN",
                "amount": "Betrag",
                "currency": "Waehrung",
                "status": "Info",
            },
            "delimiter": ";",
            "encoding": "cp1252",
            "date_format": "%d.%m.%y",
            "decimal_sep": ",",
            "thousands_sep": ".",
            "sign_mode": "signed",
            "pending_values": ["Umsatz vorgemerkt"],
        },
        "expected": {
            "rows": 8,
            "sum": "1760.12",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 1,
            "statement_account": None,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-02",
                "amount": "-61.00",
                "description": "FOLGELASTSCHRIFT Abschlag Gas Januar 2026",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": "DE33123456780000000101",
                "external_id": None,
            },
            "samples": {
                4: {
                    "description": "KARTENZAHLUNG Einkauf mit Gutschein 20 € Grünfeld",
                    "counterparty": "Supermarkt Grünfeld",
                    "counterparty_iban": None,
                },
                5: {
                    "description": "ÜBERWEISUNGSGUTSCHRIFT Erstattung Reisekosten Dezember",
                    "counterparty": "Arbeitgeber Beispiel AG",
                    "value_date": "2026-01-13",
                },
                7: {"booking_date": "2026-01-15", "amount": "2987.65"},
                9: {
                    "description": "BARGELDAUSZAHLUNG",
                    "counterparty": None,
                    "counterparty_iban": None,
                },
            },
        },
    },
    "dkb_like.csv": {
        "format": "csv",
        "description": (
            "Export mit Vorspann: UTF-8 mit BOM, 3 Zeilen Vorspann + Leerzeile, IBAN nur im "
            "Vorspann (statement_account, keine Kontospalte), Gegenpartei je nach Richtung in "
            "Zahlungsempfänger*in bzw. Zahlungspflichtige*r, zwei vorgemerkte Zeilen (Status "
            "'Vorgemerkt'), eine abweichende Wertstellung."
        ),
        "options": {
            "column_map": {
                "booking_date": "Buchungsdatum",
                "value_date": "Wertstellung",
                "status": "Status",
                "counterparty": {"debit": "Zahlungsempfänger*in", "credit": "Zahlungspflichtige*r"},
                "description": "Verwendungszweck",
                "counterparty_iban": "IBAN",
                "amount": "Betrag (€)",
            },
            "delimiter": ";",
            "encoding": "utf-8",
            "date_format": "%d.%m.%y",
            "decimal_sep": ",",
            "thousands_sep": ".",
            "sign_mode": "signed",
            "pending_values": ["Vorgemerkt"],
        },
        "expected": {
            "rows": 7,
            "sum": "3309.78",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 2,
            "statement_account": ACCOUNT_A,
            "own_accounts": [],
            "first": {
                "booking_date": "2026-01-02",
                "amount": "-38.50",
                "description": "Abschlag Wasser 01/2026",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": "DE33123456780000000101",
                "external_id": None,
            },
            "samples": {
                8: {"counterparty": "Bäckerei Krume", "counterparty_iban": None},
                9: {
                    "counterparty": "Arbeitgeber Beispiel AG",
                    "counterparty_iban": "DE57345678900000000301",
                    "amount": "3120.00",
                },
                11: {
                    "counterparty": "Erika Beispiel",
                    "counterparty_iban": "DE65789012340000000701",
                    "amount": "17.50",
                    "value_date": "2026-01-21",
                },
                14: {
                    "counterparty": "Finanzamt Musterstadt",
                    "counterparty_iban": "DE30345678900000000302",
                },
            },
        },
    },
    "ing_like.csv": {
        "format": "csv",
        "description": (
            "Export mit langem Vorspann: latin-1, CRLF, IBAN in Zeile 4 (liegt im übersprungenen "
            "Bereich, skip_rows=4), doppelte Spalte 'Währung' (die erste zählt), Saldo-Spalte, "
            "absteigend sortiert, eine abweichende Wertstellung."
        ),
        "options": {
            "column_map": {
                "booking_date": "Buchung",
                "value_date": "Wertstellungsdatum",
                "counterparty": "Auftraggeber/Empfänger",
                "description": "Verwendungszweck",
                "amount": "Betrag",
                "currency": "Währung",
            },
            "delimiter": ";",
            "encoding": "latin-1",
            "date_format": "%d.%m.%Y",
            "decimal_sep": ",",
            "thousands_sep": ".",
            "sign_mode": "signed",
            "skip_rows": 4,
        },
        "expected": {
            "rows": 8,
            "sum": "1485.69",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": ACCOUNT_A,
            "own_accounts": [],
            "first": {
                "booking_date": "2026-01-30",
                "amount": "2675.50",
                "description": "Lohn Januar 2026",
                "counterparty": "Arbeitgeber Beispiel AG",
                "counterparty_iban": None,
                "external_id": None,
            },
            "samples": {
                19: {
                    "amount": "45.00",
                    "counterparty": "Erika Beispiel",
                    "description": "Anteil Konzertkarten",
                    "value_date": "2026-01-20",
                },
                22: {"amount": "-1032.25", "booking_date": "2026-01-06"},
            },
        },
    },
    "debit_credit.csv": {
        "format": "csv",
        "description": (
            "Getrennte Spalten Soll/Haben (je Zeile genau eine gefüllt), Gegenpartei aus zwei "
            "Spalten (erste nicht leere), keine Kontoangabe in der Datei."
        ),
        "options": {
            "column_map": {
                "booking_date": "Datum",
                "value_date": "Valuta",
                "counterparty": ["Empfänger", "Auftraggeber"],
                "counterparty_iban": "IBAN Gegenkonto",
                "description": "Buchungstext",
                "debit": "Soll",
                "credit": "Haben",
            },
            "delimiter": ";",
            "encoding": "utf-8",
            "date_format": "%d.%m.%Y",
            "decimal_sep": ",",
            "thousands_sep": ".",
            "sign_mode": "debit_credit_columns",
        },
        "expected": {
            "rows": 8,
            "sum": "2431.94",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [],
            "first": {
                "booking_date": "2026-01-05",
                "amount": "-89.00",
                "description": "Abschlag Strom 01/2026 Zähler 2",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": "DE33123456780000000101",
                "external_id": None,
            },
            "samples": {
                3: {"amount": "-1150.00", "counterparty": "Hausverwaltung Müller & Söhne GmbH"},
                4: {"amount": "3456.78", "counterparty": "Arbeitgeber Beispiel AG"},
                5: {
                    "amount": "-57.43",
                    "counterparty": "Supermarkt Grünfeld",
                    "counterparty_iban": None,
                },
            },
        },
    },
    "indicator.csv": {
        "format": "csv",
        "description": (
            "Betrag ohne Vorzeichen plus Kennzeichen S/H: Komma als Trennzeichen, ISO-Datum, "
            "Punkt als Dezimaltrenner, Tausender-Komma in Anführungszeichen, keine Kontoangabe."
        ),
        "options": {
            "column_map": {
                "booking_date": "Datum",
                "value_date": "Valuta",
                "counterparty": "Name",
                "description": "Verwendungszweck",
                "amount": "Betrag",
                "indicator": "S/H",
            },
            "delimiter": ",",
            "encoding": "utf-8",
            "date_format": "%Y-%m-%d",
            "decimal_sep": ".",
            "thousands_sep": ",",
            "sign_mode": "indicator_column",
            "debit_indicators": ["S"],
        },
        "expected": {
            "rows": 7,
            "sum": "2449.83",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [],
            "first": {
                "booking_date": "2026-01-05",
                "amount": "-89.00",
                "description": "Abschlag Strom 01/2026 Zähler 3",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": None,
                "external_id": None,
            },
            "samples": {
                3: {"amount": "-1150.00"},
                4: {"amount": "3456.78"},
                5: {"amount": "-57.43"},
            },
        },
    },
    # --- CSV: Mehrkonten- und Fehlerdateien
    "multi_account.csv": {
        "format": "csv",
        "description": (
            "Generisches Format mit Zeilen für Konto A und Konto B (Spalte Auftragskonto), "
            "abwechselnd, inklusive Umbuchungspaar A -> B."
        ),
        "options": _generic_options(),
        "expected": {
            "rows": 9,
            "sum": "2479.84",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_B, ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-06",
                "amount": "-73.00",
                "description": "Abschlag Gas Januar 2026",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": "DE33123456780000000101",
                "external_id": None,
            },
            "samples": {
                3: {"own_account": ACCOUNT_B, "counterparty": "Beispielbank eG"},
                5: {"own_account": ACCOUNT_A, "counterparty_iban": ACCOUNT_B},
                6: {"own_account": ACCOUNT_B, "counterparty_iban": ACCOUNT_A},
            },
        },
    },
    "broken_date.csv": {
        "format": "csv",
        "description": (
            "Generisches Format mit zwei kaputten Zeilen: ungültiges Datum 31.02.2026 (Zeile 4) "
            "und nicht lesbarer Betrag (Zeile 7); der Rest wird geparst."
        ),
        "options": _generic_options(),
        "expected": {
            "rows": 6,
            "sum": "89.96",
            "errors": 2,
            "error_rows": [4, 7],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-05",
                "amount": "-14.20",
                "description": "Kartenzahlung Einkauf Brot und Käse",
                "counterparty": "Supermarkt Grünfeld",
                "counterparty_iban": "DE96234567890000000202",
                "external_id": None,
            },
        },
    },
    "foreign_currency.csv": {
        "format": "csv",
        "description": (
            "Generisches Format mit einer USD-Zeile (Zeile 5): ein Fehler, alle anderen Zeilen "
            "EUR."
        ),
        "options": _generic_options(),
        "expected": {
            "rows": 5,
            "sum": "7.37",
            "errors": 1,
            "error_rows": [5],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-04",
                "amount": "-71.08",
                "description": "Kartenzahlung Wocheneinkauf",
                "counterparty": "Supermarkt Grünfeld",
                "counterparty_iban": "DE96234567890000000202",
                "external_id": None,
            },
        },
    },
    # --- OFX
    "statement.ofx": {
        "format": "ofx",
        "description": (
            "OFX 1.x (SGML), cp1252 (ENCODING:USASCII, CHARSET:1252), CURDEF EUR, ein Konto "
            "(ACCTID = IBAN), FITIDs, verschiedene DTPOSTED-Schreibweisen, eine Buchung ohne "
            "NAME, eine ohne MEMO."
        ),
        "expected": {
            "rows": 7,
            "sum": "1982.73",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": ACCOUNT_A,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-02",
                "amount": "-61.40",
                "description": "Abschlag Fernwärme 01/2026",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": None,
                "external_id": "20260102-00417",
            },
            "samples": {
                2: {
                    "counterparty": "Hausverwaltung Müller & Söhne",
                    "description": "Miete Januar 2026 Wohnung links",
                    "external_id": "20260105-00022",
                },
                4: {"counterparty": None, "description": "Bargeldauszahlung Geldautomat Hauptstraße"},
                5: {"booking_date": "2026-01-15", "amount": "2987.65"},
                6: {"counterparty": "Finanzamt Musterstadt", "description": "Finanzamt Musterstadt"},
            },
        },
    },
    "multi_account.ofx": {
        "format": "ofx",
        "description": (
            "OFX 1.x (SGML, UTF-8) mit zwei STMTTRNRS-Blöcken (Konto A und B): statement_account "
            "bleibt None, own_account steht je Zeile."
        ),
        "expected": {
            "rows": 6,
            "sum": "2043.31",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_B, ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-07",
                "amount": "-29.90",
                "description": "Mobilfunk Februar Vorauszahlung Büro",
                "counterparty": "FunkNetz Muster GmbH",
                "counterparty_iban": None,
                "external_id": "A-20260107-1",
            },
            "samples": {
                2: {
                    "counterparty": "Max Muster",
                    "description": "Umbuchung Tagesgeld",
                    "own_account": ACCOUNT_A,
                },
                4: {
                    "counterparty": "Max Muster",
                    "external_id": "B-20260114-1",
                    "own_account": ACCOUNT_B,
                },
                6: {"counterparty": "Beispielbank eG", "amount": "3.21"},
            },
        },
    },
    # --- MT940
    "statement.sta": {
        "format": "mt940",
        "description": (
            "MT940, UTF-8, CRLF, ein Auszug für Konto A; deutsche :86:-Felder (?00, ?20-?2x, ?30, "
            "?31, ?32/?33), SVWZ+ über mehrere Unterfelder, ein hart auf 65 Zeichen umbrochenes "
            ":86:, Buchungs- ungleich Wertstellungsdatum (Zeile 4)."
        ),
        "expected": {
            "rows": 7,
            "sum": "1935.13",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": ACCOUNT_A,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-02",
                "amount": "-89.00",
                "description": "Abschlag Strom Januar 2026 Kd-Nr 4711",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": "DE33123456780000000101",
                "external_id": None,
            },
            "samples": {
                2: {
                    "description": "Miete Januar 2026 Wohnung 7. OG rechts",
                    "counterparty": "Hausverwaltung Müller & Söhne GmbH",
                    "counterparty_iban": "DE26234567890000000201",
                },
                3: {
                    "description": "Beitrag Haftpflicht Jahresbeitrag 2026",
                    "counterparty": "Versicherung Sicherheit AG",
                },
                4: {
                    "booking_date": "2026-01-12",
                    "counterparty_iban": None,
                    "value_date": "2026-01-13",
                },
                5: {"amount": "2987.65", "description": "Gehalt 01/2026 Abrechnung"},
            },
        },
    },
    "multi_account.sta": {
        "format": "mt940",
        "description": (
            "MT940, cp1252 (Umlaute), CRLF, zwei Auszüge (:20:) für Konto A und Konto B: "
            "statement_account bleibt None, own_account steht je Zeile."
        ),
        "expected": {
            "rows": 6,
            "sum": "2028.47",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_B, ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-08",
                "amount": "-45.60",
                "description": "Wochenendeinkauf Grünfeld",
                "counterparty": "Supermarkt Grünfeld",
                "counterparty_iban": None,
                "external_id": None,
            },
            "samples": {
                1: {
                    "description": "Wochenendeinkauf Grünfeld",
                    "counterparty": "Supermarkt Grünfeld",
                    "own_account": ACCOUNT_A,
                },
                2: {"counterparty": "Max Muster", "counterparty_iban": ACCOUNT_B, "amount": "-300.00"},
                4: {
                    "counterparty": "Max Muster",
                    "counterparty_iban": ACCOUNT_A,
                    "amount": "300.00",
                    "own_account": ACCOUNT_B,
                },
                5: {
                    "description": "Anteil Wochenendreise Größe",
                    "counterparty": "Erika Beispiel",
                    "own_account": ACCOUNT_B,
                },
            },
        },
    },
    # --- Dublettentests (generisches Format, nur Konto A)
    "dedup_a.csv": {
        "format": "csv",
        "description": (
            "Dublettentest: 02.-15.01.2026; am 05.01. stehen zwei identische Zeilen (Bäckerei "
            "Krume, -3,50, Zeilen 4 und 5); die Zeilen vom 10.-15.01. stehen identisch auch in "
            "dedup_b.csv."
        ),
        "options": _generic_options(),
        "expected": {
            "rows": 9,
            "sum": "111.73",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-02",
                "amount": "-42.10",
                "description": "Wasser und Abwasser Dezember 2025",
                "counterparty": "Stadtwerke Musterhausen",
                "counterparty_iban": "DE33123456780000000101",
                "external_id": None,
            },
            "samples": {
                4: {
                    "description": "Kartenzahlung Brötchen",
                    "counterparty": "Bäckerei Krume",
                    "amount": "-3.50",
                },
                5: {
                    "description": "Kartenzahlung Brötchen",
                    "counterparty": "Bäckerei Krume",
                    "amount": "-3.50",
                },
            },
        },
    },
    "dedup_b.csv": {
        "format": "csv",
        "description": (
            "Dublettentest: 10.-31.01.2026; die Zeilen vom 10.-15.01. (Zeilen 2-5) sind identisch "
            "zu dedup_a.csv (Überlappung), ab 16.01. kommen neue Zeilen (eine davon wieder "
            "Bäckerei Krume, aber am 22.01.)."
        ),
        "options": _generic_options(),
        "expected": {
            "rows": 10,
            "sum": "3339.81",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-10",
                "amount": "-9.40",
                "description": "Kartenzahlung Kaffee und Kuchen",
                "counterparty": "Café Östlich",
                "counterparty_iban": None,
                "external_id": None,
            },
        },
    },
    "partial_1.csv": {
        "format": "csv",
        "description": (
            "Dublettentest: enthält EINE von zwei echten, identischen Zahlungen (Bäckerei Krume, "
            "-3,50, 20.01.2026, Zeile 4), sonst nur Zeilen, die in keiner anderen Datei "
            "vorkommen."
        ),
        "options": _generic_options(),
        "expected": {
            "rows": 4,
            "sum": "-60.85",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-18",
                "amount": "-31.20",
                "description": "Kartenzahlung Sonntagseinkauf",
                "counterparty": "Supermarkt Grünfeld",
                "counterparty_iban": None,
                "external_id": None,
            },
        },
    },
    "partial_2.csv": {
        "format": "csv",
        "description": (
            "Dublettentest: enthält die ZWEITE der zwei echten, identischen Zahlungen vom "
            "20.01.2026 (Zeile 2), sonst nur Zeilen, die in keiner anderen Datei vorkommen."
        ),
        "options": _generic_options(),
        "expected": {
            "rows": 4,
            "sum": "3.70",
            "errors": 0,
            "error_rows": [],
            "pending_skipped": 0,
            "statement_account": None,
            "own_accounts": [ACCOUNT_A],
            "first": {
                "booking_date": "2026-01-20",
                "amount": "-3.50",
                "description": "Kartenzahlung Brötchen",
                "counterparty": "Bäckerei Krume",
                "counterparty_iban": None,
                "external_id": None,
            },
        },
    },
}
