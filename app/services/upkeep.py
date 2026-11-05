"""Weniger wiederkehrende Pflege (Phase 3): Preisänderungen von Fixkosten und Regeln aus Korrekturen.

- Betragsänderungen (Idee 03): verglichen werden die fest verknüpften Zahlungen mit dem im
  jeweiligen Monat gültigen Planbetrag. Eine einzelne Abweichung wird nur gemeldet
  („einmalig“, z. B. Nachzahlung); zwei aufeinanderfolgende gleiche neue Beträge ergeben den
  Vorschlag „ab Monat X anpassen“ („dauerhaft“).
- Regeln aus Korrekturen (Idee 04): dieselbe Gegenpartei mindestens dreimal manuell gleich
  kategorisiert, keine abweichende Bestätigung, keine Regel greift → Regelvorschlag mit Vorschau.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_
from sqlmodel import Session, select

from app.errors import Conflict
from app.models import (
    CategorySource,
    ChangeActor,
    FixedCost,
    FixedCostAmount,
    FixedCostPayment,
    MappingRule,
    ReviewStatus,
    Suggestion,
    SuggestionKind,
    Transaction,
    TransactionKind,
    User,
    transaction_line,
)
from app.schemas.budget import FixedCostAmountCreate
from app.schemas.rule import RuleCreate
from app.services import analysis, budget, changes, suggestions
from app.services.categorization import RuleSet, candidates_query, suggest_pattern
from app.services.recurring import normalize_name
from app.services.suggestions import Found, Handler

L = transaction_line.c


# --- 03 Betragsänderungen ------------------------------------------------------------------------


def detect_amount_changes(session: Session, user: User, today: date) -> list[Found]:
    fixed_costs = {
        f.id: f for f in session.exec(select(FixedCost).where(FixedCost.user_id == user.id, FixedCost.active))
    }
    if not fixed_costs:
        return []
    history = budget._amount_history(session, list(fixed_costs))
    rows = session.execute(
        select(FixedCostPayment.fixed_cost_id, FixedCostPayment.due_month, L.amount, L.transaction_id)
        .join(transaction_line, and_(L.transaction_id == FixedCostPayment.transaction_id,
                                     L.split_id.is_not_distinct_from(FixedCostPayment.split_id)))
        .where(FixedCostPayment.user_id == user.id, L.excluded_at.is_(None), L.amount < 0, L.kind == "regular",
               FixedCostPayment.fixed_cost_id.in_(list(fixed_costs)))
        .order_by(FixedCostPayment.fixed_cost_id, FixedCostPayment.due_month)
    ).all()
    by_fixed: dict[int, list] = defaultdict(list)
    for row in rows:
        by_fixed[row.fixed_cost_id].append(row)
    found = []
    for fixed_id, payments in by_fixed.items():
        fixed = fixed_costs[fixed_id]
        last = payments[-1]
        paid = -last.amount
        planned = budget.amount_for(fixed, last.due_month, history)
        if paid == planned:
            continue
        previous = payments[-2] if len(payments) >= 2 else None
        # dauerhaft nur bei zwei *aufeinanderfolgenden* Fälligkeiten (laut Rhythmus) mit gleichem neuen Betrag
        consecutive = previous is not None and budget.months_between(previous.due_month, last.due_month) \
            == fixed.interval_months
        if consecutive and -previous.amount == paid \
                and budget.amount_for(fixed, previous.due_month, history) != paid:
            change, valid_from, evidence = "dauerhaft", previous.due_month, [previous, last]
            reason = f"Die letzten zwei Zahlungen betrugen {paid} € statt {planned} €"
        else:
            change, valid_from, evidence = "einmalig", last.due_month, [last]
            reason = f"Die Zahlung im {last.due_month:%m/%Y} betrug {paid} € statt {planned} € – vermutlich einmalig"
        found.append(Found(
            fingerprint=f"fc:{fixed_id}|{change}|{valid_from.isoformat()}|{paid}",
            payload={"fixed_cost_id": fixed_id, "name": fixed.name, "change": change, "old_amount": planned,
                     "new_amount": paid, "valid_from": valid_from},
            evidence={"transactions": [{"id": p.transaction_id, "month": p.due_month, "amount": -p.amount}
                                       for p in evidence]},
            reason=reason,
            priority=1 if change == "dauerhaft" else 0,
        ))
    return found


def _change_validate(session: Session, user: User, suggestion: Suggestion) -> None:
    fixed = session.get(FixedCost, suggestion.payload["fixed_cost_id"])
    if fixed is None or fixed.user_id != user.id:
        raise Conflict("Die Fixkost gibt es nicht mehr", code="suggestion_stale")


AMOUNT_FIELDS = ("fixed_cost_id", "valid_from", "amount")


def _change_apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    from app.services.recurring import FIXED_FIELDS

    fixed = session.get(FixedCost, suggestion.payload["fixed_cost_id"], with_for_update=True)
    if suggestion.payload["change"] == "einmalig":
        return "fixed_cost", fixed.id  # zur Kenntnis genommen, der Plan bleibt
    before = changes.snapshot(fixed, FIXED_FIELDS)
    old_rows = {row.id: changes.snapshot(row, AMOUNT_FIELDS) for row in budget.list_amounts(session, fixed)}
    amount = Decimal(str(overrides.get("new_amount", suggestion.payload["new_amount"])))
    valid_from = date.fromisoformat(str(overrides.get("valid_from", suggestion.payload["valid_from"])))
    budget.set_amount_from(session, fixed, FixedCostAmountCreate(valid_from=valid_from, amount=amount))
    # Betragsgeschichte mitprotokollieren, damit die Rücknahme sie vollständig wiederherstellt
    for row in budget.list_amounts(session, fixed):
        if row.id not in old_rows:
            changes.record(session, user.id, row, AMOUNT_FIELDS, action="create", before=None,
                           suggestion_id=suggestion.id, actor=actor)
        elif changes.snapshot(row, AMOUNT_FIELDS) != old_rows[row.id]:
            changes.record(session, user.id, row, AMOUNT_FIELDS, action="update", before=old_rows[row.id],
                           suggestion_id=suggestion.id, actor=actor)
    changes.record(session, user.id, fixed, FIXED_FIELDS, action="update", before=before,
                   suggestion_id=suggestion.id, actor=actor)
    return "fixed_cost", fixed.id


changes.REVERTERS["fixed_cost_amount"] = (FixedCostAmount, AMOUNT_FIELDS, lambda session, row: session.delete(row))


suggestions.register(SuggestionKind.FIXED_COST_CHANGE, Handler(
    validate=_change_validate, apply=_change_apply, setting="automation.fixed_cost_change",
    is_clear=lambda s: s.payload.get("change") == "dauerhaft",
))


def refresh_amount_changes(session: Session, user: User, today: date) -> dict[str, int]:
    return suggestions.sync(session, user, SuggestionKind.FIXED_COST_CHANGE,
                            detect_amount_changes(session, user, today), "amount-change-v1")


# --- 04 Regeln aus Korrekturen -------------------------------------------------------------------

MIN_CONFIRMED = 3


def detect_rules(session: Session, user: User, today: date) -> list[Found]:
    txs = session.exec(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.review_status == ReviewStatus.CONFIRMED,
            Transaction.category_source == CategorySource.MANUAL,
            Transaction.kind == TransactionKind.REGULAR,
            Transaction.category_id.is_not(None),
            Transaction.excluded_at.is_(None),
            Transaction.booking_date >= today - timedelta(days=400),
        )
    ).all()
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for tx in txs:
        if tx.splits:
            continue
        key = normalize_name(tx.counterparty or "")
        if len(key) >= 3:
            groups[key].append(tx)
    rules = RuleSet(session, user.id)
    open_candidates = list(session.exec(candidates_query(user)))
    found = []
    for key, items in groups.items():
        counts = Counter(t.category_id for t in items)
        category_id, count = counts.most_common(1)[0]
        if count < MIN_CONFIRMED or len(counts) > 1:
            continue  # zu wenig Belege oder uneinheitlich bestätigt
        latest = max(items, key=lambda t: (t.booking_date, t.id))
        if rules.winner(latest.description, latest.counterparty) is not None:
            continue
        pattern, field = suggest_pattern(latest.description, latest.counterparty)
        if len(pattern) < 3:
            continue
        probe = RuleSet(session, user.id, rules=[MappingRule(user_id=user.id, pattern=pattern, match_field=field,
                                                             target_category_id=category_id)])
        matching = sum(1 for t in open_candidates if probe.winner(t.description, t.counterparty))
        conflicts = sum(1 for t in txs if t.category_id != category_id and probe.winner(t.description, t.counterparty))
        found.append(Found(
            fingerprint=f"rule:{key}|{category_id}",
            payload={"name": pattern[:100], "pattern": pattern, "match_field": field, "match_type": "contains",
                     "target_category_id": category_id},
            evidence={"transactions": [t.id for t in sorted(items, key=lambda t: t.booking_date)],
                      "confirmed": count, "would_match_open": matching, "conflicts": conflicts},
            reason=f"{count}× „{latest.counterparty}“ gleich eingeordnet – künftig automatisch zuordnen?"
                   + (f" {matching} offene Buchungen würden sofort passen." if matching else ""),
            priority=1 if not conflicts else 0,
        ))
    return found


def _rule_apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    from app.services import rules as rule_service

    data = RuleCreate(**({k: v for k, v in suggestion.payload.items()
                          if k in ("name", "pattern", "match_field", "match_type", "target_category_id")}
                         | {k: v for k, v in overrides.items() if k in ("name", "pattern", "match_field")}))
    rule = rule_service.create_rule(session, user, data)
    changes.record(session, user.id, rule, RULE_FIELDS, action="create", before=None,
                   suggestion_id=suggestion.id, actor=actor)
    return "mapping_rule", rule.id


RULE_FIELDS = ("name", "pattern", "match_field", "match_type", "case_sensitive", "target_category_id", "active",
               "priority")
suggestions.register(SuggestionKind.RULE, Handler(
    validate=lambda session, user, s: None, apply=_rule_apply, setting="automation.rules",
    is_clear=lambda s: s.evidence.get("confirmed", 0) >= 5 and s.evidence.get("conflicts", 1) == 0,
))
changes.REVERTERS["mapping_rule"] = (MappingRule, RULE_FIELDS, lambda session, rule: session.delete(rule))


def refresh_rules(session: Session, user: User, today: date) -> dict[str, int]:
    return suggestions.sync(session, user, SuggestionKind.RULE, detect_rules(session, user, today), "rule-v1")


analysis.register("fixed_cost_changes", refresh_amount_changes)
analysis.register("rules", refresh_rules)
_ = ChangeActor  # Import für Typen der Handler
