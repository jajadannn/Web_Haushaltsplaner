"""Wiederkehrende Abbuchungen erkennen und als Fixkosten vorschlagen (deterministisch, ohne KI).

Ablauf je Profil:
1. Abbuchungszeilen der letzten 15 Monate – ohne Umbuchungen, Kredite, ausgeschlossene und bereits
   mit einer Fixkost verknüpfte Zeilen, ohne Konsumkategorien (Lebensmittel, Restaurant …).
2. Gruppieren nach Gegenpartei (IBAN, sonst normalisierter Name). Zahlungsdienstleister wie
   PayPal nur mit erkennbarer Referenz – sonst wären verschiedene Händler eine „Fixkost“.
3. Innerhalb einer Gruppe nach Betrag trennen (zwei Verträge beim selben Anbieter).
4. Rhythmus bestimmen: monatlich (mindestens drei aufeinanderfolgende Monate, 25–35 Tage
   Abstand) oder alle 3/6/12 Monate (mindestens zwei Zahlungen); die Serie muss noch laufen.
5. Abgleich mit vorhandenen Fixkosten, dann Vorschlag `fixed_cost_new` über den Vorschlagsspeicher.
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import and_, exists, not_
from sqlmodel import Session, select

from app.errors import Conflict
from app.models import (
    Category,
    ChangeActor,
    FixedCost,
    FixedCostPayment,
    LoanPayment,
    Suggestion,
    SuggestionKind,
    SuggestionStatus,
    Transaction,
    TransactionSource,
    User,
    transaction_line,
)
from app.schemas.budget import FixedCostCreate, FixedCostPaymentCreate
from app.services import ai_gateway, ai_jobs, budget, changes, merchants, suggestions
from app.services.suggestions import Found, Handler

L = transaction_line.c
GENERATOR = "recurring-v1"
HISTORY_DAYS = 460  # gut 15 Monate
CONSUMPTION = {
    "lebensmittel", "restaurant & café", "kraftstoff & ladestrom", "drogerie & friseur", "apotheke",
    "kleidung & schuhe", "bargeld",
}
PROVIDERS = ("paypal", "klarna", "amazon payments", "sumup", "stripe", "google payment", "apple")
_LEGAL = re.compile(r"\b(gmbh|mbh|ag|se|kg|ohg|ug|e\s?v|co|inc|ltd|llc|sarl|bv)\b\.?")
_REFERENCE = re.compile(
    r"(?:mandat(?:sref(?:erenz)?)?|referenz|ref|kundennr|kunden-nr|vertragsnr|vertrag|abo)[\s.:#-]*([a-z0-9][a-z0-9/-]{3,})",
    re.IGNORECASE,
)


@dataclass
class Line:
    transaction_id: int
    split_id: int | None
    amount: Decimal  # positiv (Abfluss)
    booking_date: date
    category_id: int | None
    account_id: int
    counterparty: str | None
    iban: str | None
    description: str


def normalize_name(name: str) -> str:
    text = name.casefold()
    text = _LEGAL.sub(" ", text)
    text = re.sub(r"[\d\W_]+", " ", text)
    return " ".join(text.split())


def group_key(line: Line) -> str | None:
    name = normalize_name(line.counterparty or "")
    if any(p in name for p in PROVIDERS):
        ref = _REFERENCE.search(line.description or "")
        return f"provider:{name}|ref:{ref.group(1).casefold()}" if ref else None
    if line.iban:
        return f"iban:{line.iban}"
    return f"name:{name}" if name else None


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def classify(dates: list[date]) -> int | None:
    """Rhythmus in Monaten (1, 3, 6, 12) oder None (unregelmäßig)."""
    if len(dates) < 2 or len({(d.year, d.month) for d in dates}) != len(dates):
        return None
    month_gaps = [months_between(a, b) for a, b in zip(dates, dates[1:], strict=False)]
    day_gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
    if all(g == 1 for g in month_gaps) and all(20 <= d <= 40 for d in day_gaps):
        return 1 if len(dates) >= 3 else None
    for interval in (3, 6, 12):
        if all(g == interval for g in month_gaps):
            return interval
    return None


def _clusters(lines: list[Line]) -> list[list[Line]]:
    """Beträge, die höchstens 10 % vom Median ihres Clusters abweichen, gehören zusammen."""
    clusters: list[list[Line]] = []
    for line in sorted(lines, key=lambda x: x.amount):
        for cluster in clusters:
            mid = Decimal(median([c.amount for c in cluster]))
            if abs(line.amount - mid) <= mid * Decimal("0.10"):
                cluster.append(line)
                break
        else:
            clusters.append([line])
    return clusters


def load_lines(session: Session, user_id: int, today: date) -> list[Line]:
    linked = exists().where(
        and_(FixedCostPayment.transaction_id == L.transaction_id,
             FixedCostPayment.split_id.is_not_distinct_from(L.split_id))
    )
    rows = session.execute(
        select(L.transaction_id, L.split_id, L.amount, L.booking_date, L.category_id, L.account_id,
               Transaction.counterparty, Transaction.counterparty_iban, Transaction.description)
        .select_from(transaction_line.join(Transaction, Transaction.id == L.transaction_id))
        .where(
            L.user_id == user_id,
            L.kind == "regular",
            L.excluded_at.is_(None),
            L.amount < 0,
            L.booking_date >= today - timedelta(days=HISTORY_DAYS),
            L.booking_date <= today,
            Transaction.source != TransactionSource.LOAN,
            not_(exists().where(LoanPayment.payment_transaction_id == L.transaction_id)),
            not_(linked),
        )
        .order_by(L.booking_date, L.transaction_id)
    ).all()
    return [Line(r.transaction_id, r.split_id, -r.amount, r.booking_date, r.category_id, r.account_id,
                 r.counterparty, r.counterparty_iban, r.description or "") for r in rows]


def _still_running(last: date, interval: int, today: date) -> bool:
    grace = 45 if interval == 1 else interval * 31 + 15
    return (today - last).days <= grace


def _covered(fixed_costs: list[FixedCost], cluster: list[Line], amount: Decimal) -> bool:
    """Gibt es schon eine aktive Fixkost für diese Zahlungen?"""
    for fc in fixed_costs:
        text = (fc.match_text or "").casefold()
        if text and any(text in (c.counterparty or "").casefold() or text in c.description.casefold()
                        for c in cluster):
            return True
        if fc.category_id is not None and any(c.category_id == fc.category_id for c in cluster) \
                and abs(fc.amount - amount) <= fc.amount * Decimal("0.10"):
            return True
    return False


def detect(session: Session, user: User, today: date) -> list[Found]:
    categories = {c.id: c.name.casefold() for c in session.exec(select(Category).where(Category.user_id == user.id))}
    fixed_costs = list(session.exec(select(FixedCost).where(FixedCost.user_id == user.id, FixedCost.active)))
    resolver = merchants.Resolver(session, user.id)
    groups: dict[str, list[Line]] = {}
    names: dict[str, str] = {}
    for line in load_lines(session, user.id, today):
        if line.category_id is not None and categories.get(line.category_id) in CONSUMPTION:
            continue
        resolved = resolver.group(line.counterparty, line.iban, line.description)
        if resolved is not None:
            key, name = resolved  # bestätigter Anbieter/Vertrag; ("", "") = Zahlungsdienst ohne Referenz
            if key:
                names[key] = name
        else:
            key = group_key(line)
        if key:
            groups.setdefault(key, []).append(line)

    found = []
    for key, lines in groups.items():
        clusters = [c for c in _clusters(lines) if len(c) >= 2]
        for cluster in clusters:
            cluster.sort(key=lambda c: (c.booking_date, c.transaction_id))
            interval = classify([c.booking_date for c in cluster])
            if interval is None or not _still_running(cluster[-1].booking_date, interval, today):
                continue
            amounts = [c.amount for c in cluster]
            identical = len(set(amounts)) == 1
            amount = cluster[-1].amount if identical else Decimal(median(amounts)).quantize(Decimal("0.01"))
            if _covered(fixed_costs, cluster, amount):
                continue
            due_day = Counter(c.booking_date.day for c in cluster).most_common(1)[0][0]
            category = Counter(c.category_id for c in cluster if c.category_id).most_common(1)
            account = Counter(c.account_id for c in cluster).most_common(1)[0][0]
            name = names.get(key) or (cluster[-1].counterparty or cluster[-1].description or "Fixkost")[:100]
            suffix = f"|~{int(amount)}" if len(clusters) > 1 else ""
            rhythm = {1: "monatlich", 3: "vierteljährlich", 6: "halbjährlich", 12: "jährlich"}[interval]
            spread = max(amounts) - min(amounts)
            reason = (
                f"{len(cluster)} Zahlungen, {rhythm} um den {due_day}., "
                + ("Betrag immer gleich" if identical else f"Betrag schwankt um bis zu {spread} €")
            )
            if interval == 12:
                reason += " – nur ein Jahresabstand beobachtet, bitte prüfen"
            found.append(Found(
                fingerprint=f"{key}|{interval}{suffix}",
                payload={
                    "name": name,
                    "amount": amount,
                    "interval_months": interval,
                    "due_day": due_day,
                    "first_due_date": cluster[0].booking_date if interval > 1 else None,
                    "category_id": category[0][0] if category else None,
                    "account_id": account,
                    "match_text": (cluster[-1].counterparty or "")[:100] or None,
                },
                evidence={
                    "transactions": [
                        {"id": c.transaction_id, "split_id": c.split_id, "date": c.booking_date, "amount": c.amount}
                        for c in cluster
                    ],
                    "identical_amount": identical,
                    "group": key,
                },
                reason=reason,
                priority=2 if interval == 1 else (0 if interval == 12 else 1),
            ))
    return found


def refresh(session: Session, user: User, today: date) -> dict[str, int]:
    result = suggestions.sync(session, user, SuggestionKind.FIXED_COST_NEW, detect(session, user, today), GENERATOR)
    if ai_gateway.enabled():
        for suggestion in suggestions.list_suggestions(session, user, kind=SuggestionKind.FIXED_COST_NEW,
                                                       status=SuggestionStatus.OPEN):
            if "ai" not in suggestion.payload:
                ai_jobs.enqueue(session, user.id, ENRICH, "suggestion", suggestion.id)
    return result


# --- KI-Anreicherung: Name, Anbieter, Verpflichtung (ändert nie Beträge oder Rhythmus) -----------

ENRICH = "enrich_fixed_cost"
ENRICH_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 60},
        "ist_verpflichtung": {"type": "boolean"},
        "anbieter": {"type": "string", "maxLength": 100},
        "vertrag_referenz": {"type": ["string", "null"], "maxLength": 60},
        "begruendung": {"type": "string", "maxLength": 300},
    },
    "required": ["name", "ist_verpflichtung", "anbieter", "vertrag_referenz", "begruendung"],
    "additionalProperties": False,
}
ENRICH_TASK = (
    "Die Daten zeigen wiederkehrende Abbuchungen eines Empfängers. Gib einen kurzen, verständlichen "
    "Namen für die Fixkost (z. B. „Internetanschluss“), den Anbieter, ob es eine vertragliche "
    "Verpflichtung ist (Abo, Versicherung, Miete, Vertrag) oder nur regelmäßiger Konsum, und eine "
    "Vertragsreferenz, falls sie wörtlich in den Texten steht, sonst null."
)


def _enrich_prepare(session: Session, job):
    suggestion = session.get(Suggestion, job.ref_id)
    if suggestion is None or suggestion.status != SuggestionStatus.OPEN or "ai" in suggestion.payload:
        return None
    ids = [t["id"] for t in suggestion.evidence.get("transactions", [])]
    txs = session.exec(select(Transaction).where(Transaction.id.in_(ids)).order_by(Transaction.booking_date)).all()
    data = {
        "rhythmus_monate": suggestion.payload.get("interval_months"),
        "betrag_eur": suggestion.payload.get("amount"),
        "buchungen": [{"datum": t.booking_date.isoformat(), "empfaenger": (t.counterparty or "")[:120],
                       "verwendungszweck": (t.description or "")[:200]} for t in txs[-5:]],
    }
    return ENRICH_TASK, data, ENRICH_SCHEMA


def _enrich_finish(session: Session, job, answer: dict):
    suggestion = session.get(Suggestion, job.ref_id, with_for_update=True, populate_existing=True)
    if suggestion is None or suggestion.status != SuggestionStatus.OPEN:
        return None
    payload = dict(suggestion.payload)
    payload["ai"] = answer
    payload["name"] = answer["name"].strip()[:100] or payload["name"]
    suggestion.payload = payload
    if not answer["ist_verpflichtung"]:
        suggestion.priority = min(suggestion.priority, 0) - 1
        suggestion.reason += " – laut KI eher regelmäßiger Konsum als Vertrag"
    else:
        suggestion.reason += f" – KI: {answer['begruendung'][:200]}"
    session.flush()
    return answer


ai_jobs.register(ENRICH, ai_jobs.Task(prepare=_enrich_prepare, finish=_enrich_finish))


# --- Vorschlags-Handler --------------------------------------------------------------------------

FIXED_FIELDS = ("name", "amount", "due_day", "category_id", "match_text", "start_date", "end_date", "active",
                "interval_months", "first_due_date", "account_id")
OVERRIDABLE = {"name", "amount", "due_day", "interval_months", "first_due_date", "category_id", "account_id",
               "match_text"}


def _evidence_valid(session: Session, suggestion: Suggestion) -> bool:
    for item in suggestion.evidence.get("transactions", []):
        tx = session.get(Transaction, item["id"])
        if tx is None or tx.excluded_at is not None:
            return False
    return True


def _validate(session: Session, user: User, suggestion: Suggestion) -> None:
    taken = session.exec(
        select(FixedCostPayment.id).where(
            FixedCostPayment.transaction_id.in_([t["id"] for t in suggestion.evidence.get("transactions", [])])
        )
    ).first()
    if taken is not None:
        raise Conflict("Die Zahlungen sind inzwischen einer Fixkost zugeordnet", code="suggestion_stale")


def _apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    from app import clock

    unknown = set(overrides) - OVERRIDABLE
    if unknown:
        from app.errors import Invalid

        raise Invalid("Unbekannte Felder", code="validation_error", details={"fields": sorted(unknown)})
    values = {k: v for k, v in suggestion.payload.items() if k in OVERRIDABLE} | overrides
    if not values.get("match_text"):
        values.pop("match_text", None)
    data = FixedCostCreate(**values, start_date=budget.month_start(clock.today()))
    fixed = budget.create_fixed_cost(session, user, data)
    for item in suggestion.evidence.get("transactions", []):
        try:
            with session.begin_nested():
                budget.link_payment(
                    session, user, fixed,
                    FixedCostPaymentCreate(transaction_id=item["id"], split_id=item.get("split_id"),
                                           due_month=date.fromisoformat(item["date"])),
                    source="auto" if actor == ChangeActor.AUTO else "suggestion",
                )
        except Conflict:
            continue  # z. B. zwei Zahlungen im selben Monat – die erste genügt
    changes.record(session, user.id, fixed, FIXED_FIELDS, action="create", before=None,
                   suggestion_id=suggestion.id, actor=actor)
    return "fixed_cost", fixed.id


def _is_clear(suggestion: Suggestion) -> bool:
    """Eindeutig: monatlich, mindestens drei identische Zahlungen, feste Gegenpartei, Kategorie."""
    p, e = suggestion.payload, suggestion.evidence
    return (
        p.get("interval_months") == 1
        and len(e.get("transactions", [])) >= 3
        and e.get("identical_amount") is True
        and str(e.get("group", "")).startswith(("iban:", "alias:"))
        and p.get("category_id") is not None
    )


def _reopen(old: dict, new: dict) -> str | None:
    if old.get("interval_months") != new.get("interval_months"):
        return "anderer Rhythmus"
    old_amount, new_amount = Decimal(old["amount"]), Decimal(new["amount"])
    if old_amount and abs(new_amount - old_amount) > old_amount * Decimal("0.20"):
        return f"Betrag jetzt {new_amount} € statt {old_amount} €"
    return None


def _delete_fixed(session: Session, fixed: FixedCost) -> None:
    budget.delete_fixed_cost(session, fixed)


suggestions.register(SuggestionKind.FIXED_COST_NEW, Handler(
    validate=_validate, apply=_apply, is_clear=_is_clear, setting="automation.fixed_cost",
    reopen=_reopen, evidence_valid=_evidence_valid,
))
changes.REVERTERS["fixed_cost"] = (FixedCost, FIXED_FIELDS, _delete_fixed)
