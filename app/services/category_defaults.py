"""Standardkategorien für neue Nutzerprofile (reine Startdaten, ohne Datenbankzugriff).

Der Seed-Service legt diese Struktur je Profil an: Hauptkategorien mit optionalen
Unterkategorien, höchstens zwei Ebenen. Unterkategorien haben immer den Typ ihrer
Hauptkategorie (das prüft die Datenbank).

Bewusst nicht enthalten: Umbuchung/Transfer (Buchungsart `kind=transfer`) und
Tilgung (fachlich ein Transfer auf das Kreditkonto). Die zwei Systemkategorien
(`system_key`) braucht die Kreditverwaltung für Zins und Gebühren einer Rate.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DefaultCategory:
    """Eine Standardkategorie samt ihren Unterkategorien."""

    name: str
    type: str  # "income" oder "expense"
    icon: str | None = None  # Lucide-Icon in kebab-case
    color: str | None = None  # #RRGGBB, nur an Hauptkategorien
    system_key: str | None = None  # vom System benötigt, nicht löschbar
    children: tuple[DefaultCategory, ...] = ()


# Die Farben der Hauptkategorien sind so gewählt, dass sie sich in Diagrammen gut
# voneinander abheben; Unterkategorien haben keine eigene Farbe.
DEFAULT_CATEGORIES: tuple[DefaultCategory, ...] = (
    # --- Ausgaben ---
    DefaultCategory(
        name="Wohnen",
        type="expense",
        icon="house",
        color="#026FD7",
        children=(
            DefaultCategory("Miete", "expense"),
            DefaultCategory("Nebenkosten", "expense"),
            DefaultCategory("Strom", "expense"),
            DefaultCategory("Gas & Heizung", "expense"),
            DefaultCategory("Einrichtung & Instandhaltung", "expense"),
        ),
    ),
    DefaultCategory(
        name="Lebensmittel",
        type="expense",
        icon="shopping-cart",
        color="#32C364",
    ),
    DefaultCategory(
        name="Restaurant & Café",
        type="expense",
        icon="utensils",
        color="#FD7933",
    ),
    DefaultCategory(
        name="Mobilität",
        type="expense",
        icon="car",
        color="#475569",
        children=(
            DefaultCategory("Kraftstoff & Ladestrom", "expense"),
            DefaultCategory("ÖPNV & Bahn", "expense"),
            DefaultCategory("Kfz-Versicherung", "expense"),
            DefaultCategory("Kfz-Steuer", "expense"),
            DefaultCategory("Werkstatt & Wartung", "expense"),
        ),
    ),
    DefaultCategory(
        name="Versicherungen",
        type="expense",
        icon="shield-check",
        color="#058CBA",
        children=(
            DefaultCategory("Krankenversicherung", "expense"),
            DefaultCategory("Haftpflicht & Hausrat", "expense"),
            DefaultCategory("Rechtsschutz", "expense"),
            DefaultCategory("Vorsorge & Lebensversicherung", "expense"),
        ),
    ),
    DefaultCategory(
        name="Gesundheit & Körperpflege",
        type="expense",
        icon="heart-pulse",
        color="#EC5C52",
        children=(
            DefaultCategory("Arzt & Zahnarzt", "expense"),
            DefaultCategory("Apotheke", "expense"),
            DefaultCategory("Drogerie & Friseur", "expense"),
        ),
    ),
    DefaultCategory(
        name="Kommunikation & Abos",
        type="expense",
        icon="smartphone",
        color="#7970D5",
        children=(
            DefaultCategory("Mobilfunk", "expense"),
            DefaultCategory("Internet & Festnetz", "expense"),
            DefaultCategory("Streaming & Medien", "expense"),
        ),
    ),
    DefaultCategory(
        name="Freizeit & Hobby",
        type="expense",
        icon="ticket",
        color="#F987E8",
        children=(
            DefaultCategory("Sport & Fitness", "expense"),
            DefaultCategory("Kultur & Veranstaltungen", "expense"),
            DefaultCategory("Hobbys & Vereine", "expense"),
        ),
    ),
    DefaultCategory(
        name="Urlaub & Reisen",
        type="expense",
        icon="plane",
        color="#4CC8EE",
    ),
    DefaultCategory(
        name="Shopping",
        type="expense",
        icon="shopping-bag",
        color="#C03467",
        children=(
            DefaultCategory("Kleidung & Schuhe", "expense"),
            DefaultCategory("Elektronik & Technik", "expense"),
        ),
    ),
    DefaultCategory(
        name="Bildung",
        type="expense",
        icon="graduation-cap",
        color="#A243AB",
    ),
    DefaultCategory(
        name="Kinder",
        type="expense",
        icon="baby",
        color="#FB9796",
        children=(
            DefaultCategory("Kita & Betreuung", "expense"),
            DefaultCategory("Schule & Schulbedarf", "expense"),
            DefaultCategory("Spielzeug & Kinderkleidung", "expense"),
        ),
    ),
    DefaultCategory(
        name="Geschenke & Spenden",
        type="expense",
        icon="gift",
        color="#CA7197",
    ),
    DefaultCategory(
        name="Steuern & Gebühren",
        type="expense",
        icon="receipt",
        color="#9A6B45",
        children=(
            DefaultCategory("Einkommensteuer", "expense"),
            DefaultCategory("Rundfunkbeitrag", "expense"),
            DefaultCategory("Gebühren & Bußgelder", "expense"),
        ),
    ),
    DefaultCategory(
        name="Finanzen & Kredite",
        type="expense",
        icon="landmark",
        color="#EFA831",
        children=(
            # Systemkategorien: Zins- und Gebührenanteil einer Kreditrate
            DefaultCategory("Kreditzinsen", "expense", system_key="loan_interest"),
            DefaultCategory(
                "Kreditgebühren & Versicherungen", "expense", system_key="loan_fees"
            ),
            DefaultCategory("Bankgebühren & Dispozinsen", "expense"),
        ),
    ),
    DefaultCategory(
        name="Sonstiges",
        type="expense",
        icon="package",
        color="#9CA3AF",
    ),
    # --- Einnahmen ---
    DefaultCategory(
        name="Gehalt & Lohn",
        type="income",
        icon="briefcase",
        color="#168657",
    ),
    DefaultCategory(
        name="Nebeneinkünfte",
        type="income",
        icon="coins",
        color="#A9C719",
    ),
    DefaultCategory(
        name="Rente & Pension",
        type="income",
        icon="piggy-bank",
        color="#74A6EF",
    ),
    DefaultCategory(
        name="Kindergeld & staatliche Leistungen",
        type="income",
        icon="heart-handshake",
        color="#BCA8FD",
    ),
    DefaultCategory(
        name="Kapitalerträge",
        type="income",
        icon="trending-up",
        color="#40970F",
        children=(
            DefaultCategory("Zinsen", "income"),
            DefaultCategory("Dividenden", "income"),
        ),
    ),
    DefaultCategory(
        name="Erstattungen & Rückzahlungen",
        type="income",
        icon="rotate-ccw",
        color="#46D0BF",
    ),
    DefaultCategory(
        name="Sonstige Einnahmen",
        type="income",
        icon="wallet",
        color="#757703",
    ),
)
