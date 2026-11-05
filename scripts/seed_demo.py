#!/usr/bin/env python
"""Demo-Daten für den Finanzplaner in einer eigenen Datenbank `finanzplaner_demo`.

Nutzung: .venv/bin/python scripts/seed_demo.py

Die Datenbank wird bei jedem Lauf gelöscht und neu aufgebaut (Alembic). Alle Daten werden
ausschließlich über die HTTP-API (TestClient) angelegt, damit die Validierung greift.
Alle Daten sind relativ zu heute, damit der aktuelle Monat realistisch aussieht.
"""

import os
import random
import sys
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

DEMO_DB = "finanzplaner_demo"

import psycopg  # noqa: E402
from sqlalchemy import make_url  # noqa: E402

from app.config import Settings  # noqa: E402

base_url = make_url(Settings().database_url)
demo_url = base_url.set(database=DEMO_DB)
if demo_url.database != "finanzplaner_demo":  # pragma: no cover - Schutz
    sys.exit(f"Abbruch: Zieldatenbank ist nicht {DEMO_DB}")

# Vor dem Import der App setzen, damit get_settings() die Demo-DB sieht
os.environ["DATABASE_URL"] = demo_url.render_as_string(hide_password=False)


def recreate_database() -> None:
    assert demo_url.database == "finanzplaner_demo"
    with psycopg.connect(
        host=demo_url.host, port=demo_url.port, user=demo_url.username,
        password=demo_url.password, dbname="postgres", autocommit=True,
    ) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()", (DEMO_DB,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{DEMO_DB}"')
        conn.execute(f'CREATE DATABASE "{DEMO_DB}"')


def migrate() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def money(value) -> str:
    return f"{Decimal(str(value)):.2f}"


def main() -> None:
    recreate_database()
    migrate()

    from app.config import get_settings

    get_settings.cache_clear()
    assert get_settings().database_url == os.environ["DATABASE_URL"]
    from fastapi.testclient import TestClient

    from app.main import app

    rng = random.Random(42)
    today = date.today()
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    # Vier Monate Historie auf dem Girokonto, damit die Fixkostenerkennung Serien findet
    first_history = (first_prev - timedelta(days=1)).replace(day=1)
    first_history = (first_history - timedelta(days=1)).replace(day=1)

    api = TestClient(app, client=("127.0.0.1", 50000))

    def call(method: str, path: str, uid: int | None = None, expect=(200, 201, 204), **kw):
        headers = {"X-User-Id": str(uid)} if uid is not None else {}
        r = api.request(method, path, headers=headers, **kw)
        if r.status_code not in expect:
            sys.exit(f"{method} {path} -> {r.status_code}: {r.text}\nPayload: {kw}")
        return r.json() if r.content else None

    counts: dict[str, int] = {}

    def bump(key: str, n: int = 1) -> None:
        counts[key] = counts.get(key, 0) + n

    # --- Profile, Kategorien ---------------------------------------------------
    users = {n: call("POST", "/users", json={"name": n}) for n in ("Fabian", "Lea")}

    cat_cache: dict[int, dict[str, int]] = {}

    def cat(uid: int, name: str, kind: str = "expense") -> int:
        if uid not in cat_cache:
            cat_cache[uid] = {c["name"]: c["id"] for c in call("GET", "/categories", uid)}
        if name not in cat_cache[uid]:
            created = call("POST", "/categories", uid, json={"name": name, "type": kind})
            cat_cache[uid][name] = created["id"]
            bump("categories (neu)")
        return cat_cache[uid][name]

    # Vorhandene Standardkategorien (je Profil automatisch angelegt) nach Anzeigenamen
    def cats(uid: int) -> dict[str, int]:
        return {
            "Gehalt": cat(uid, "Gehalt & Lohn", "income"),
            "Lebensmittel": cat(uid, "Lebensmittel"),
            "Essen": cat(uid, "Restaurant & Café"),
            "Auto": cat(uid, "Kraftstoff & Ladestrom"),
            "Haushalt": cat(uid, "Drogerie & Friseur"),
            "Freizeit": cat(uid, "Freizeit & Hobby"),
            "Miete": cat(uid, "Miete"),
            "Strom": cat(uid, "Strom"),
            "Handy": cat(uid, "Mobilfunk"),
            "Streaming": cat(uid, "Streaming & Medien"),
            "Fitness": cat(uid, "Sport & Fitness"),
        }

    # --- Fabian: Stammdaten -----------------------------------------------------
    f = users["Fabian"]["id"]
    fc = cats(f)
    sparkasse = call("POST", "/institutions", f, json={"name": "Sparkasse"})
    dkb = call("POST", "/institutions", f, json={"name": "DKB"})
    f_giro = call("POST", "/accounts", f, json={
        "name": "Girokonto", "type": "checking", "institution_id": sparkasse["id"],
        "opening_balance": "1500.00", "opening_balance_date": first_history.isoformat()})
    f_tages = call("POST", "/accounts", f, json={
        "name": "Tagesgeld", "type": "savings", "institution_id": dkb["id"],
        "opening_balance": "5000.00", "opening_balance_date": first_prev.isoformat()})
    f_card = call("POST", "/accounts", f, json={
        "name": "Kreditkarte", "type": "credit_card", "institution_id": dkb["id"],
        "opening_balance": "0.00", "opening_balance_date": first_prev.isoformat()})
    bump("institutions", 2)
    bump("accounts", 3)

    def fixed(uid, name, amount, day, category=None, match=None):
        body = {"name": name, "amount": money(amount), "due_day": day}
        if category:
            body["category_id"] = category
        if match:
            body["match_text"] = match
        call("POST", "/fixed-costs", uid, json=body)
        bump("fixed costs")

    fixed(f, "Miete", "850.00", 1, fc["Miete"])
    fixed(f, "Strom", "90.00", 15, fc["Strom"], "Stadtwerke")
    fixed(f, "Handy", "24.99", 20, fc["Handy"], "Telekom")
    fixed(f, "Streaming", "13.99", 8, fc["Streaming"], "Netflix")

    # --- Fabian: Kredit ---------------------------------------------------------
    due_day = 30
    first_due = first_prev.replace(day=min(due_day, monthrange(first_prev.year, first_prev.month)[1]))
    loan = call("POST", "/loans", f, json={
        "name": "Autokredit", "loan_type": "annuity", "lender_name": "Autobank",
        "annual_interest_rate": "5.0000", "current_balance": "7840.12",
        "balance_date": first_prev.isoformat(), "first_due_date": first_due.isoformat(),
        "payment_day": due_day, "term_months": 36, "payment_account_id": f_giro["id"],
    })
    bump("loans")
    if first_due <= today:
        first_rate = call("GET", f"/loans/{loan['id']}/schedule", f)[0]
        call("POST", f"/loans/{loan['id']}/payments", f, json={
            "booking_date": first_due.isoformat(), "amount": first_rate["planned_installment"],
            "description": "Rate Autokredit Autobank"})
        bump("loan payments")

    # --- Transaktionen ----------------------------------------------------------
    def tx(uid, account, day, amount, desc, cp=None, category=None):
        if day > today:
            return None
        body = {"account_id": account, "booking_date": day.isoformat(),
                "amount": money(amount), "description": desc}
        if cp:
            body["counterparty"] = cp
        if category:
            body["category_id"] = category
        bump("transactions")
        return call("POST", "/transactions", uid, json=body)

    def transfer(account_from, account_to, day, amount, desc, uid):
        if day > today:
            return
        call("POST", "/transfers", uid, json={
            "from_account_id": account_from, "to_account_id": account_to,
            "booking_date": day.isoformat(), "amount": money(amount), "description": desc})
        bump("transfers")

    def day_of(month_first: date, d: int) -> date:
        return month_first.replace(day=min(d, monthrange(month_first.year, month_first.month)[1]))

    shops = [  # (Gegenpartei, Beschreibung, Kategorie, min, max)
        ("Rewe", "REWE Markt Einkauf", "Lebensmittel", 12, 68),
        ("Edeka", "EDEKA Center Einkauf", "Lebensmittel", 8, 55),
        ("Bäckerei Müller", "Bäckerei Müller", "Lebensmittel", 3, 11),
        ("Shell", "Tankstelle Shell", "Auto", 35, 72),
        ("dm Drogeriemarkt", "dm Drogerie", "Haushalt", 6, 29),
        ("Pizzeria Roma", "Restaurant Pizzeria Roma", "Essen", 18, 52),
        ("Kino Cinestar", "Kino Cinestar", "Freizeit", 11, 28),
        ("Lidl", "LIDL Einkauf", "Lebensmittel", 9, 47),
        ("Café Central", "Café Central", "Essen", 4, 16),
    ]

    def everyday(uid, c, account_ids, month_first, n, last_day):
        """n Alltagsausgaben auf Tage 1..last_day verteilt; account_ids = [(Konto, Gewicht)]."""
        for _ in range(n):
            cp, desc, cname, lo, hi = rng.choice(shops)
            day = month_first.replace(day=rng.randint(1, last_day))
            account = rng.choices([a for a, _ in account_ids], [w for _, w in account_ids])[0]
            amount = Decimal(rng.randint(lo * 100, hi * 100)) / 100
            tx(uid, account, day, -amount, desc, cp, c[cname])

    for month_first in (first_prev, first_this):
        last_day = monthrange(month_first.year, month_first.month)[1]
        elapsed = last_day if month_first < first_this else today.day
        n = max(5, round(rng.randint(15, 25) * elapsed / last_day))
        # Fixe Buchungen
        tx(f, f_giro["id"], day_of(month_first, 1), "2850.00", "Gehalt", "Arbeitgeber GmbH", fc["Gehalt"])
        tx(f, f_giro["id"], day_of(month_first, 1), "-850.00", "Miete", "Hausverwaltung Schmidt", fc["Miete"])
        tx(f, f_giro["id"], day_of(month_first, 8), "-13.99", "Netflix Abo", "Netflix", fc["Streaming"])
        tx(f, f_giro["id"], day_of(month_first, 15), "-90.00", "Stadtwerke Abschlag", "Stadtwerke", fc["Strom"])
        tx(f, f_giro["id"], day_of(month_first, 20), "-24.99", "Telekom Mobilfunk", "Telekom", fc["Handy"])
        # Umbuchungen
        transfer(f_giro["id"], f_tages["id"], day_of(month_first, 3), "100.00", "Sparen Tagesgeld", f)
        # Alltag (Girokonto, ein Teil auf der Karte)
        everyday(f, fc, [(f_giro["id"], 3), (f_card["id"], 1)], month_first, n, elapsed)

    # Kreditkartenabrechnung: Vormonat vollständig, Girokonto -> Kreditkarte
    card_total = Decimal("0")
    for t in call(
        "GET", f"/transactions?account_ids={f_card['id']}&date_to={last_prev.isoformat()}&limit=200", f
    )["items"]:
        card_total += -Decimal(t["amount"])
    if card_total > 0:
        transfer(f_giro["id"], f_card["id"], day_of(first_this, 2), card_total, "Kreditkartenabrechnung", f)

    # Für die Vorschläge (KI-Ausbau): Internet monatlich ohne Fixkost, Versicherung vierteljährlich,
    # dreimal gleich eingeordneter Händler (Regelvorschlag), Erstattung zu einem Einkauf
    month = first_history
    while month <= first_this:
        tx(f, f_giro["id"], day_of(month, 4), "-39.99", "Internet Festnetz Kundennr 88123", "Netzwelt GmbH",
           cat(f, "Internet & Festnetz"))
        nxt = month + timedelta(days=32)
        month = nxt.replace(day=1)
    tx(f, f_giro["id"], day_of(first_history, 12), "-96.00", "Beitrag Hausrat Q", "Hausrat Versicherung AG")
    tx(f, f_giro["id"], day_of(first_this, 12), "-96.00", "Beitrag Hausrat Q", "Hausrat Versicherung AG")
    for d in (5, 12, 19):
        tx(f, f_giro["id"], day_of(first_prev, d), "-45.00", "Tankstelle Aral", "Aral", fc["Auto"])
    tx(f, f_giro["id"], day_of(first_prev, 9), "-79.90", "Modehaus Online Bestellung", "Modehaus Nord",
       cat(f, "Kleidung & Schuhe"))
    tx(f, f_giro["id"], day_of(first_prev, 21), "29.90", "Rückerstattung Retoure", "Modehaus Nord")

    # Besonderheiten dieses Monats / Prüfliste
    gid = f_giro["id"]
    d1 = first_this + timedelta(days=min(1, today.day - 1))
    d2 = first_this + timedelta(days=min(2, today.day - 1))
    tx(f, gid, d1, "50.00", "Rückzahlung Max", "Max Mustermann")
    tx(f, gid, first_prev + timedelta(days=17), "-23.40", "Kartenzahlung unbekannt 4711", "Kiosk Hauptbahnhof")
    tx(f, gid, d1, "-37.80", "PayPal Europe Zahlung")
    tx(f, gid, d2, "10.00", "Erstattung Rewe", "Rewe", fc["Lebensmittel"])

    # --- Lea ---------------------------------------------------------------------
    le = users["Lea"]["id"]
    lc = cats(le)
    ing = call("POST", "/institutions", le, json={"name": "ING"})
    l_giro = call("POST", "/accounts", le, json={
        "name": "Girokonto", "type": "checking", "institution_id": ing["id"],
        "opening_balance": "800.00", "opening_balance_date": first_prev.isoformat()})
    bump("institutions")
    bump("accounts")
    fixed(le, "Handy", "15.00", 25, lc["Handy"])
    fixed(le, "Fitness", "29.90", 10, lc["Fitness"], "FitX")
    for month_first in (first_prev, first_this):
        last_day = monthrange(month_first.year, month_first.month)[1]
        elapsed = last_day if month_first < first_this else today.day
        tx(le, l_giro["id"], day_of(month_first, 2), "1900.00", "Gehalt", "Design Studio AG", lc["Gehalt"])
        tx(le, l_giro["id"], day_of(month_first, 10), "-29.90", "FitX Mitgliedschaft", "FitX", lc["Fitness"])
        tx(le, l_giro["id"], day_of(month_first, 25), "-15.00", "Handyvertrag", "Vodafone", lc["Handy"])
        everyday(le, lc, [(l_giro["id"], 1)], month_first, max(4, round(10 * elapsed / last_day)), elapsed)

    # --- Zusammenfassung -----------------------------------------------------------
    print(f"Demo-Datenbank: {DEMO_DB} (Stichtag {today.isoformat()})")
    for name, user in users.items():
        print(f"  Profil {name}: id={user['id']}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print("\nAPI starten mit:")
    print(f"  DATABASE_URL={os.environ['DATABASE_URL']} .venv/bin/uvicorn app.main:app --port 8001")


if __name__ == "__main__":
    main()
