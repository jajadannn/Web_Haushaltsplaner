"""Erklären, Fragen, Erfassen (Phase 6).

- Monatserklärung (Idee 07): Das Backend berechnet den Vergleich (Vormonat, Schnitt der drei
  Monate davor, Hauptkategorien, größte Buchungen, Einmaleffekte); die KI formuliert nur daraus
  zwei, drei Sätze. Verweise auf Buchungen sind nur aus den gelieferten IDs erlaubt.
- Fragen (Idee 08): Die KI wählt genau ein Werkzeug aus einer festen Liste mit geprüften
  Parametern. Ausgeführt wird über die vorhandenen Services, nur lesend, nur im eigenen Profil.
  Die Antwort nennt Zeitraum, Datenstand und Belege. Kein SQL vom Modell.
- Erfassung in natürlicher Sprache (Idee 21): „Gestern 18,50 € bar Mittagessen“ → Entwurf für den
  Plus-Dialog. Konto/Kategorie nur aus den angebotenen IDs, Datum rechnet das Backend; fehlt etwas,
  wird nachgefragt. Ohne KI erkennt eine einfache Regel Betrag und Datum.
"""

import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, func, select

from app import clock
from app.errors import AppError, Invalid
from app.models import (
    Account,
    AccountType,
    Category,
    FixedCost,
    Transaction,
    TransactionKind,
    User,
    transaction_line,
)
from app.schemas.filters import TransactionFilter
from app.services import ai_gateway, budget, reports, settings
from app.services.recurring import normalize_name
from app.services.transactions import category_with_descendants, filtered_query

ZERO = Decimal("0.00")
L = transaction_line.c


class AiUnavailableError(AppError):
    status_code = 503
    code = "ai_unavailable"


def _require_ai(session: Session | None = None, user: User | None = None) -> None:
    if not ai_gateway.enabled():
        raise AiUnavailableError("Keine lokale KI eingerichtet (AI_URL) – Funktion nicht verfügbar")
    if session is not None and user is not None and not settings.get(session, user.id, "ai.enabled"):
        raise AiUnavailableError("Die KI ist in diesem Profil ausgeschaltet (Einstellungen → Automatik & KI)")


def _ask(task: str, data, schema: dict, session: Session | None = None, user: User | None = None) -> dict:
    _require_ai(session, user)
    try:
        return ai_gateway.ask(task, data, schema, session=session)
    except ai_gateway.AiUnavailable as exc:
        raise AiUnavailableError(f"KI nicht erreichbar: {exc}") from exc
    except ai_gateway.AiInvalidAnswer as exc:
        raise AppError(f"Die KI-Antwort war unbrauchbar: {exc}", code="ai_invalid_answer") from exc


# --- 07 Monatsvergleich --------------------------------------------------------------------------


def _shift(first: date, months: int) -> date:
    total = first.year * 12 + first.month - 1 + months
    return date(total // 12, total % 12 + 1, 1)


def _roots(session: Session, user: User, start: date, end: date) -> dict[int, tuple[str, Decimal]]:
    data = reports.categories(session, user, start, end, "expense")
    return {i["category_id"]: (i["name"], i["net"]) for i in data["items"] if i["parent_id"] is None}


def month_comparison(session: Session, user: User, month: date) -> dict:
    today = clock.today()
    first = budget.month_start(month)
    last = budget.month_end(first)
    end = min(last, today)
    if end < first:
        raise Invalid("Der Monat liegt in der Zukunft", code="month_in_future")
    previous = _shift(first, -1)
    current = _roots(session, user, first, end)
    prev = _roots(session, user, previous, budget.month_end(previous))
    avg_months = [_roots(session, user, _shift(first, -k), budget.month_end(_shift(first, -k))) for k in (1, 2, 3)]
    names = {cid: name for d in (current, prev, *avg_months) for cid, (name, _) in d.items()}
    rows = []
    for cid, name in names.items():
        cur = current.get(cid, (name, ZERO))[1]
        before = prev.get(cid, (name, ZERO))[1]
        avg = (sum((m.get(cid, (name, ZERO))[1] for m in avg_months), ZERO) / 3).quantize(Decimal("0.01"))
        if cur or before or avg:
            rows.append({"category_id": cid, "name": name, "current": cur, "previous": before, "average_3": avg,
                         "delta": cur - before})
    rows.sort(key=lambda r: (-abs(r["delta"]), r["name"]))
    expenses = sum((r["current"] for r in rows), ZERO)
    previous_expenses = sum((r["previous"] for r in rows), ZERO)

    outflows = session.exec(select(Transaction).where(
        Transaction.user_id == user.id, Transaction.amount < 0, Transaction.kind == TransactionKind.REGULAR,
        Transaction.excluded_at.is_(None), Transaction.booking_date.between(first, end),
    ).order_by(Transaction.amount, Transaction.id)).all()
    seen = {normalize_name(c or "") for c in session.exec(select(Transaction.counterparty).where(
        Transaction.user_id == user.id, Transaction.booking_date >= _shift(first, -6),
        Transaction.booking_date < first)).all()}
    largest = [{"transaction_id": t.id, "date": t.booking_date, "amount": -t.amount,
                "counterparty": t.counterparty, "description": t.description} for t in outflows[:5]]
    one_offs = [entry for entry, t in zip(largest, outflows[:5], strict=False)
                if entry["amount"] >= 50 and normalize_name(t.counterparty or t.description or "") not in seen]
    return {
        "month": first, "until": end, "incomplete": end < last,
        "expenses": expenses, "previous_expenses": previous_expenses, "delta": expenses - previous_expenses,
        "categories": rows[:10], "largest": largest, "one_offs": one_offs,
    }


EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 600},
                   "verweise": {"type": "array", "items": {"type": "integer"}, "maxItems": 5}},
    "required": ["text", "verweise"], "additionalProperties": False,
}


def explain_month(session: Session, user: User, month: date) -> dict:
    comparison = month_comparison(session, user, month)
    task = ("Erkläre in zwei bis drei kurzen Sätzen, warum sich die Ausgaben gegenüber dem Vormonat verändert haben. "
            "Nutze nur die Zahlen aus den Daten, erfinde keine Ursachen. Ist der Monat unvollständig, sage das. "
            "Verweise nur auf Buchungs-IDs aus den Daten.")
    data = reports_jsonable(comparison)
    answer = _ask(task, data, EXPLAIN_SCHEMA, session, user)
    allowed = {t["transaction_id"] for t in comparison["largest"]}
    return {"month": comparison["month"], "text": answer["text"].strip(),
            "references": [i for i in answer["verweise"] if i in allowed], "comparison": comparison}


def reports_jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: reports_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [reports_jsonable(v) for v in value]
    return value


# --- 08 Fragen -----------------------------------------------------------------------------------

TOOLS = {
    "transactions_search": "Wie viel / wie oft für etwas in einem beliebigen Zeitraum: Summe, Anzahl und Beispiele, "
                           "gefiltert nach Kategorie (kategorie_id) und/oder Suchtext (Händlername)",
    "sum_by": "Summen je Kategorie oder je Gegenpartei in einem Zeitraum (gruppierung: kategorie|gegenpartei)",
    "report_summary": "Einnahmen, Ausgaben und Vermögen insgesamt in einem Zeitraum",
    "report_categories": "Ausgaben oder Einnahmen aller Hauptkategorien in einem Zeitraum (typ: expense|income)",
    "report_trends": "Monatsverlauf der letzten N Monate (monate), optional für eine Kategorie",
    "month_comparison": "NUR für „Warum war Monat X teurer/anders als der Vormonat?“ (Monat über date_from)",
    "fixed_costs_list": "Liste der Fixkosten und Abos",
}
NULLABLE_STRING = {"type": ["string", "null"]}
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "werkzeug": {"type": "string", "enum": list(TOOLS)},
        "date_from": NULLABLE_STRING, "date_to": NULLABLE_STRING, "suche": NULLABLE_STRING,
        "kategorie_id": {"type": ["integer", "null"]},
        "typ": {"type": ["string", "null"], "enum": ["expense", "income", None]},
        "monate": {"type": ["integer", "null"]},
        "gruppierung": {"type": ["string", "null"], "enum": ["kategorie", "gegenpartei", None]},
    },
    "required": ["werkzeug", "date_from", "date_to", "suche", "kategorie_id", "typ", "monate", "gruppierung"],
    "additionalProperties": False,
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"antwort": {"type": "string", "minLength": 1, "maxLength": 800},
                   "belege": {"type": "array", "items": {"type": "integer"}, "maxItems": 10}},
    "required": ["antwort", "belege"], "additionalProperties": False,
}


def _bad(message: str) -> Invalid:
    return Invalid(message, code="ask_invalid_parameters")


def _period(params: dict, today: date) -> tuple[date, date]:
    try:
        start = date.fromisoformat(params["date_from"]) if params.get("date_from") else date(today.year, 1, 1)
        end = date.fromisoformat(params["date_to"]) if params.get("date_to") else today
    except ValueError as exc:
        raise _bad("Ungültiges Datum") from exc
    if end < start or (end - start).days > 366 * 5:
        raise _bad("Zeitraum unzulässig")
    return start, end


def _lines(session: Session, user: User, txs, f: TransactionFilter):
    """Buchungszeilen der gefundenen Buchungen wie in den Berichten: Teilbuchungen einzeln, nur reguläre
    (keine Umbuchungsanteile), bei Kategoriefilter nur die passenden Zeilen."""
    if not txs:
        return []
    query = select(L.transaction_id, L.split_id, L.amount, L.category_id).where(
        L.transaction_id.in_([t.id for t in txs]), L.kind == TransactionKind.REGULAR, L.excluded_at.is_(None))
    if f.category_id is not None:
        ids = (category_with_descendants(session, user.id, f.category_id) if f.include_subcategories
               else [f.category_id])
        query = query.where(L.category_id.in_(ids))
    return session.execute(query).all()


def _execute(session: Session, user: User, tool: str, params: dict) -> tuple[dict, tuple[date, date]]:
    today = clock.today()
    category_id = params.get("kategorie_id")
    if category_id is not None:
        category = session.get(Category, category_id)
        if category is None or category.user_id != user.id:
            raise _bad("Unbekannte Kategorie")
    start, end = _period(params, today)
    if tool == "transactions_search":
        search = (params.get("suche") or "").strip()[:200] or None
        f = TransactionFilter(date_from=start, date_to=end, search=search, category_id=category_id)
        query = filtered_query(session, user, f)
        txs = session.exec(query.order_by(Transaction.booking_date.desc())).all()
        total = sum((line.amount for line in _lines(session, user, txs, f)), ZERO)
        return {"count": len(txs), "sum": total,
                "examples": [{"id": t.id, "date": t.booking_date, "amount": t.amount, "counterparty": t.counterparty,
                              "description": (t.description or "")[:120]} for t in txs[:10]]}, (start, end)
    if tool == "sum_by":
        f = TransactionFilter(date_from=start, date_to=end, category_id=category_id)
        txs = session.exec(filtered_query(session, user, f)).all()
        by_id = {t.id: t for t in txs}
        names = {c.id: c.name for c in session.exec(select(Category).where(Category.user_id == user.id))}
        totals: Counter = Counter()
        for line in _lines(session, user, txs, f):
            key = names.get(line.category_id, "ohne Kategorie") if params.get("gruppierung") != "gegenpartei" \
                else (by_id[line.transaction_id].counterparty or "unbekannt")
            totals[key] += line.amount
        return {"groups": [{"name": k, "sum": v} for k, v in sorted(totals.items(), key=lambda kv: kv[1])[:15]]}, \
            (start, end)
    if tool == "report_summary":
        data = reports.summary(session, user, start, end)
        return {"movements": data["movements"], "net_worth": data["net_worth"]}, (start, end)
    if tool == "report_categories":
        typ = params.get("typ") or "expense"
        data = reports.categories(session, user, start, end, typ)
        return {"type": typ, "items": [{"name": i["name"], "net": i["net"]} for i in data["items"]
                                       if i["parent_id"] is None][:15], "total": data["total_net"]}, (start, end)
    if tool == "report_trends":
        months = params.get("monate") or 6
        if not 1 <= months <= 36:
            raise _bad("Monate zwischen 1 und 36")
        data = reports.trends(session, user, months, today, category_id)
        return {"months": data["months"]}, (_shift(budget.month_start(today), -(months - 1)), today)
    if tool == "month_comparison":
        data = month_comparison(session, user, start)
        return data, (data["month"], data["until"])
    if tool == "fixed_costs_list":
        items = session.exec(select(FixedCost).where(FixedCost.user_id == user.id, FixedCost.active)).all()
        return {"fixed_costs": [{"name": f.name, "amount": f.amount, "interval_months": f.interval_months,
                                 "due_day": f.due_day} for f in items]}, (today, today)
    raise _bad("Unbekanntes Werkzeug")


def ask(session: Session, user: User, question: str) -> dict:
    today = clock.today()
    categories = session.exec(select(Category.id, Category.name, Category.type).where(Category.user_id == user.id))
    choice = _ask(
        "Wähle für die Frage des Nutzers genau ein Werkzeug und seine Parameter. Der Zeitraum (date_from bis "
        "date_to) muss die ganze Frage abdecken – z. B. „diesen und letzten Monat“ = erster Tag des Vormonats bis "
        "heute. Für Beträge zu einer Kategorie oder einem Händler über einen Zeitraum nimm transactions_search. "
        "Kategorien über kategorie_id (Händlernamen stehen nicht in den Kategorien). Datumswerte als JJJJ-MM-TT; "
        "nicht benötigte Parameter sind null.",
        {"frage": question[:500], "heute": today.isoformat(), "werkzeuge": TOOLS,
         "kategorien": [{"id": c.id, "name": c.name, "typ": c.type} for c in categories]},
        TOOL_SCHEMA, session, user,
    )
    result, (start, end) = _execute(session, user, choice["werkzeug"], choice)
    result = reports_jsonable(result)
    answer = _ask(
        "Beantworte die Frage kurz auf Deutsch nur mit den Ergebnissen. Nenne den Zeitraum. Belege nur als "
        "Buchungs-IDs aus den Ergebnissen.",
        {"frage": question[:500], "zeitraum": [start.isoformat(), end.isoformat()], "ergebnis": result},
        ANSWER_SCHEMA, session, user,
    )
    allowed = {e["id"] for e in result.get("examples", [])}
    return {"question": question, "tool": choice["werkzeug"],
            "parameters": {k: v for k, v in choice.items() if k != "werkzeug" and v is not None},
            "period": {"from": start, "to": end}, "data_as_of": today, "answer": answer["antwort"].strip(),
            "references": [i for i in answer["belege"] if i in allowed], "result": result}


# --- 21 Natürliche Spracheingabe -----------------------------------------------------------------

PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "betrag": {"type": "string"}, "richtung": {"type": "string", "enum": ["ausgabe", "einnahme"]},
        "datum": NULLABLE_STRING,
        "datum_relativ": {"type": ["string", "null"], "enum": ["heute", "gestern", "vorgestern", None]},
        "kategorie_id": {"type": ["integer", "null"]}, "konto_id": {"type": ["integer", "null"]},
        "beschreibung": {"type": "string", "maxLength": 200},
    },
    "required": ["betrag", "richtung", "datum", "datum_relativ", "kategorie_id", "konto_id", "beschreibung"],
    "additionalProperties": False,
}
# Tausendertrennung (1.234,56 / 1,234.56) zuerst, sonst ganze Zahl mit optionalen Nachkommastellen
_AMOUNT = re.compile(r"(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d{1,7}(?:[.,]\d{1,2})?)\s*(?:€|eur|euro)?",
                     re.IGNORECASE)
_RELATIVE = re.compile(r"\b(vorgestern|gestern|heute)\b")
RELATIVE = {"heute": 0, "gestern": 1, "vorgestern": 2}


def _money(text) -> Decimal | None:
    """Betrag aus Text wie „18,50 Euro“, „1.234,56“ oder „1,234.56“ – positiv, auf Cent gerundet."""
    match = re.search(r"\d[\d.,]*", str(text or ""))
    if not match:
        return None
    raw = match.group(0).rstrip(".,")
    if "," in raw and "." in raw:  # das letzte Trennzeichen ist das Dezimalzeichen
        decimal_sep = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if decimal_sep == "," else ",", "").replace(decimal_sep, ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    elif raw.count(".") > 1 or re.search(r"\.\d{3}$", raw):
        raw = raw.replace(".", "")  # Tausenderpunkt
    try:
        value = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _rule_parse(text: str) -> dict:
    lowered = text.casefold()
    match = _AMOUNT.search(lowered)
    found_day = _RELATIVE.search(lowered)  # Wortgrenzen: „gestern“ steckt auch in „vorgestern“
    relative = found_day.group(1) if found_day else None
    income = any(w in lowered for w in ("bekommen", "erhalten", "einnahme", "gutschrift"))
    description = re.sub(r"\b(heute|gestern|vorgestern|bar|für|fuer|€|eur|euro)\b", " ", text, flags=re.IGNORECASE)
    description = " ".join(_AMOUNT.sub(" ", description).split())
    return {"betrag": match.group(1) if match else "", "richtung": "einnahme" if income else "ausgabe",
            "datum": None, "datum_relativ": relative, "kategorie_id": None, "konto_id": None,
            "beschreibung": description[:200]}


def parse_entry(session: Session, user: User, text: str) -> dict:
    today = clock.today()
    accounts = session.exec(select(Account).where(Account.user_id == user.id, Account.archived_at.is_(None),
                                                  Account.type != AccountType.LOAN)).all()
    categories = session.exec(select(Category).where(Category.user_id == user.id, Category.active,
                                                     Category.system_key.is_(None))).all()
    ai_used = False
    if settings.ai_allowed(session, user.id):
        try:
            parsed = ai_gateway.ask(
                "Mach aus der Beschreibung einen Buchungsentwurf. Konto und Kategorie nur aus den Listen, sonst null. "
                "Datum entweder absolut (JJJJ-MM-TT) oder relativ (heute/gestern/vorgestern).",
                {"text": text[:300], "heute": today.isoformat(),
                 "konten": [{"id": a.id, "name": a.name, "typ": a.type} for a in accounts],
                 "kategorien": [{"id": c.id, "name": c.name, "typ": c.type} for c in categories]},
                PARSE_SCHEMA,
            )
            ai_used = True
        except (ai_gateway.AiUnavailable, ai_gateway.AiInvalidAnswer):
            parsed = _rule_parse(text)
    else:
        parsed = _rule_parse(text)

    questions = []
    amount = _money(parsed["betrag"])
    if amount is None:  # KI-Betrag unlesbar: Betrag aus dem Text selbst
        amount = _money(_rule_parse(text)["betrag"])
    if amount is None:
        questions.append("amount")
    booking_date = today
    if parsed.get("datum"):
        try:
            booking_date = date.fromisoformat(parsed["datum"])
        except ValueError:
            questions.append("date")
    elif parsed.get("datum_relativ") in RELATIVE:
        booking_date = today - timedelta(days=RELATIVE[parsed["datum_relativ"]])
    if booking_date > today:
        booking_date, questions = today, [*questions, "date"]
    account_ids = {a.id for a in accounts}
    account_id = parsed.get("konto_id") if parsed.get("konto_id") in account_ids else None
    if account_id is None:
        questions.append("account")
    category_ids = {c.id for c in categories}
    category_id = parsed.get("kategorie_id") if parsed.get("kategorie_id") in category_ids else None
    signed = None if amount is None else (amount if parsed["richtung"] == "einnahme" else -amount)

    duplicate = None
    if signed is not None:
        query = select(Transaction).where(
            Transaction.user_id == user.id, Transaction.amount == signed,
            Transaction.booking_date.between(booking_date - timedelta(days=3), booking_date + timedelta(days=3)),
            Transaction.excluded_at.is_(None))
        if account_id is not None:
            query = query.where(Transaction.account_id == account_id)
        found = session.exec(query.order_by(func.abs(Transaction.booking_date - booking_date))).first()
        if found is not None:
            duplicate = {"id": found.id, "booking_date": found.booking_date, "amount": found.amount,
                         "description": found.description, "counterparty": found.counterparty}
    return {"amount": signed, "booking_date": booking_date, "account_id": account_id, "category_id": category_id,
            "description": (parsed.get("beschreibung") or text)[:200].strip(), "questions": questions,
            "possible_duplicate": duplicate, "ai_used": ai_used}
