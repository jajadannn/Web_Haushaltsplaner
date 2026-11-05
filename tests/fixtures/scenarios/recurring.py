"""Anonymisierter Prüfsatz für die Fixkostenerkennung (alle Daten erfunden, Stichtag 2026-11-20).

Jedes Szenario bringt eine Buchungsliste und die fachlich erwarteten Vorschläge mit. Eine leere
Erwartungsliste bedeutet: Es darf kein Vorschlag entstehen.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Expected:
    name_contains: str
    interval_months: int
    amount: str
    due_day: int


@dataclass(frozen=True)
class Scenario:
    name: str
    transactions: list[dict]
    expected: list[Expected] = field(default_factory=list)
    # Gesetzt, wenn der Code fachlich ein anderes Ergebnis liefert (Begründung für xfail)
    xfail: str | None = None


def buchung(day: str, amount: str, counterparty: str, description: str, iban: str | None = None,
            category_name: str | None = None) -> dict:
    row = {"booking_date": day, "amount": amount, "counterparty": counterparty, "description": description}
    if iban:
        row["counterparty_iban"] = iban
    if category_name:
        row["category_name"] = category_name
    return row


def monthly(months: list[str], day: int, amounts: list[str], counterparty: str, description: str, **kw) -> list[dict]:
    return [buchung(f"{m}-{day:02d}", a, counterparty, description, **kw) for m, a in zip(months, amounts, strict=True)]


MONATE = ["2026-08", "2026-09", "2026-10", "2026-11"]

SCENARIOS: list[Scenario] = [
    Scenario(
        "internet_monatlich_identisch",
        monthly(MONATE, 5, ["-39.99"] * 4, "Netzwerk Beispiel GmbH", "Internet Tarif Komfort",
                iban="DE02100100100006820101", category_name="Internet & Festnetz"),
        [Expected("Netzwerk Beispiel", 1, "39.99", 5)],
    ),
    Scenario(
        "strom_schwankend",
        monthly(MONATE, 12, ["-82.10", "-85.40", "-79.80", "-84.00"], "Stadtwerke Musterstadt", "Abschlag Strom",
                iban="DE02120300000000202051", category_name="Strom"),
        [Expected("Stadtwerke", 1, "83.05", 12)],  # Median der vier Beträge
    ),
    Scenario(
        "versicherung_vierteljaehrlich",
        [buchung("2026-05-15", "-61.50", "Sicherungs AG", "Hausrat Beitrag Quartal",
                 iban="DE02300209000106531065", category_name="Haftpflicht & Hausrat"),
         buchung("2026-08-15", "-61.50", "Sicherungs AG", "Hausrat Beitrag Quartal",
                 iban="DE02300209000106531065", category_name="Haftpflicht & Hausrat")],
        [Expected("Sicherungs", 3, "61.50", 15)],
    ),
    Scenario(
        "jahresbeitrag",
        [buchung("2025-09-10", "-48.00", "Sportverein Beispieldorf e.V.", "Jahresbeitrag Mitglied",
                 iban="DE02500105170137075030"),
         buchung("2026-09-10", "-48.00", "Sportverein Beispieldorf e.V.", "Jahresbeitrag Mitglied",
                 iban="DE02500105170137075030")],
        [Expected("Sportverein", 12, "48.00", 10)],
    ),
    Scenario(
        "zwei_vertraege_gleicher_anbieter",
        monthly(MONATE, 3, ["-9.99"] * 4, "Streamwerk GmbH", "Abo Basis", iban="DE02200505501015871393")
        + monthly(MONATE, 18, ["-29.99"] * 4, "Streamwerk GmbH", "Abo Premium", iban="DE02200505501015871393"),
        [Expected("Streamwerk", 1, "9.99", 3), Expected("Streamwerk", 1, "29.99", 18)],
    ),
    Scenario(
        "supermarkt_regelmaessig",
        monthly(MONATE, 7, ["-54.20", "-54.20", "-54.20", "-54.20"], "Markt Mustermann", "Kartenzahlung",
                iban="DE52760300800123456789", category_name="Lebensmittel"),
    ),
    Scenario(
        "paypal_ohne_referenz",
        monthly(MONATE, 9, ["-14.99"] * 4, "PayPal Europe S.a.r.l.", "PayPal Zahlung Onlinekauf"),
    ),
    Scenario(
        "paypal_mit_mandatsreferenz",
        monthly(MONATE, 9, ["-14.99"] * 4, "PayPal Europe S.a.r.l.", "Mandatsref ABC12345 Streaming Abo"),
        [Expected("PayPal", 1, "14.99", 9)],
    ),
    Scenario(
        "erstattung",
        [buchung("2026-09-20", "25.00", "Online Shop Beispiel", "Erstattung Retoure"),
         buchung("2026-10-20", "25.00", "Online Shop Beispiel", "Erstattung Retoure"),
         buchung("2026-11-20", "25.00", "Online Shop Beispiel", "Erstattung Retoure")],
    ),
    Scenario(
        "fehlender_importmonat",
        [buchung("2026-08-06", "-24.90", "Fitness Beispiel GmbH", "Mitgliedsbeitrag", iban="DE89370400440532013000"),
         buchung("2026-09-06", "-24.90", "Fitness Beispiel GmbH", "Mitgliedsbeitrag", iban="DE89370400440532013000"),
         buchung("2026-11-06", "-24.90", "Fitness Beispiel GmbH", "Mitgliedsbeitrag", iban="DE89370400440532013000")],
    ),
    Scenario(
        "preiserhoehung_im_letzten_monat",
        monthly(MONATE, 10, ["-39.99", "-39.99", "-39.99", "-44.99"], "Mobilfunk Beispiel AG", "Mobilfunk Tarif",
                iban="DE02100500000054540402", category_name="Mobilfunk"),
        # Fachlich soll der aktuelle Preis 44,99 vorgeschlagen werden. Der Code clustert mit 10 %
        # Toleranz: 44,99 liegt 12,5 % über 39,99 und fällt als Einzelposten heraus. Vorschlag
        # kommt daher mit 39,99 aus nur drei Zahlungen (Preiserhöhung bleibt unbeachtet).
        [Expected("Mobilfunk Beispiel", 1, "44.99", 10)],
        xfail="Cluster-Toleranz 10 %: die erhöhte letzte Zahlung (+12,5 %) wird ausgeklammert, "
              "vorgeschlagen wird der alte Betrag 39,99",
    ),
    Scenario(
        "vertragsende_juni",
        monthly(["2026-03", "2026-04", "2026-05", "2026-06"], 4, ["-19.99"] * 4, "Zeitung Beispiel Verlag",
                "Digitalabo", iban="DE02600501010002034304"),
    ),
    Scenario(
        "zwei_zahlungen_im_selben_monat",
        [buchung(f"{m}-{d:02d}", "-12.00", "Kiosk Beispiel", "Zeitschrift", iban="DE45100900001234567890")
         for m in ("2026-08", "2026-09", "2026-10", "2026-11") for d in (3, 20)],
    ),
]
