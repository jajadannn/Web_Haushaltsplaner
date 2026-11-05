"""Prüfliste: ungeklärte bzw. automatisch kategorisierte Buchungen bestätigen.

Bestätigen betrifft nur die Kategorisierung – es bedeutet NICHT, dass die Buchung mit
einem Kontoauszug abgestimmt wurde.
"""

from decimal import Decimal

from sqlmodel import Session, func, select

from app.errors import AppError, Invalid
from app.models import (
    Account,
    Category,
    CategorySource,
    Loan,
    LoanPayment,
    LoanScheduleEntry,
    MappingRule,
    MatchType,
    ReviewStatus,
    Transaction,
    TransactionKind,
    User,
)
from app.models.imports import ImportRow
from app.schemas.rule import ReviewConfirm
from app.services.categorization import RuleSet, candidates_query, suggest_pattern
from app.services.common import get_owned
from app.services.transactions import _assert_editable, assert_pair_unchanged


def review_query(user: User, status: str | None):
    query = select(Transaction).where(Transaction.user_id == user.id, Transaction.excluded_at.is_(None))
    if status is None:
        return query.where(Transaction.review_status.in_([ReviewStatus.NEEDS_REVIEW, ReviewStatus.AUTO_CATEGORIZED]))
    return query.where(Transaction.review_status == status)


# --- 10/22: Gruppieren und nach Klärungsbedarf ordnen --------------------------------------------

LARGE_AMOUNT = 100


def _group_key(tx: Transaction) -> str | None:
    from app.services.recurring import normalize_name

    name = normalize_name(tx.counterparty or "")
    return f"{name}|{'in' if tx.amount > 0 else 'out'}" if len(name) >= 2 else None


def _groupable(session: Session, tx: Transaction, loan_ids: set[int]) -> bool:
    return not tx.splits and tx.kind == TransactionKind.REGULAR and tx.id not in loan_ids


def review_groups(session: Session, user: User, min_size: int = 2) -> list[dict]:
    """Offene Buchungen nach Gegenpartei und Richtung; Kreditraten und Aufteilungen ausgenommen."""
    txs = list(session.exec(review_query(user, None).order_by(Transaction.booking_date, Transaction.id)))
    loan_ids = set(_loan_suggestions(session, [t.id for t in txs]))
    groups: dict[str, list[Transaction]] = {}
    for tx in txs:
        key = _group_key(tx)
        if key and _groupable(session, tx, loan_ids):
            groups.setdefault(key, []).append(tx)
    result = []
    for key, items in groups.items():
        if len(items) < min_size:
            continue
        result.append({
            "key": key,
            "label": items[-1].counterparty,
            "direction": key.rsplit("|", 1)[1],
            "count": len(items),
            "total": sum((t.amount for t in items), Decimal("0.00")),
            "transaction_ids": [t.id for t in items],
            "category_ids": sorted({t.category_id for t in items if t.category_id is not None}),
        })
    return sorted(result, key=lambda g: (-g["count"], g["label"].casefold()))


def _priority(tx: Transaction, loan: dict | None, group_size: int) -> tuple[tuple, str]:
    """Sortierschlüssel und Begründung: Konflikte, dann große Beträge, dann Gruppen, dann Rest."""
    amount = abs(tx.amount)
    if loan is not None:
        return (0, -amount), "Mögliche Kreditrate – zuerst klären, damit Restschuld und Plan stimmen"
    if amount >= LARGE_AMOUNT:
        return (1, -amount), f"Großer Betrag ({amount:.2f} €) – wirkt stark auf Budget und Berichte"
    if group_size >= 3:
        return (2, -group_size, -amount), f"Eine von {group_size} ähnlichen Buchungen – gemeinsam bestätigen"
    return (3, -amount), "Einzelbuchung mit kleinem Betrag"


def list_review_by_priority(session: Session, user: User, status: str | None, limit: int, offset: int) -> dict:
    txs = list(session.exec(review_query(user, status)))
    loans = _loan_suggestions(session, [t.id for t in txs])
    sizes: dict[str, int] = {}
    for tx in txs:
        key = _group_key(tx)
        if key:
            sizes[key] = sizes.get(key, 0) + 1
    ranked = sorted(
        ((tx, *_priority(tx, loans.get(tx.id), sizes.get(_group_key(tx) or "", 1))) for tx in txs),
        key=lambda item: (item[1], item[0].booking_date.toordinal() * -1, -item[0].id),
    )
    page = ranked[offset:offset + limit]
    return {
        "items": [{"transaction": tx, "suggested_loan": loans.get(tx.id), "priority_reason": reason}
                  for tx, _, reason in page],
        "total": len(txs),
        "limit": limit,
        "offset": offset,
    }


def list_review(session: Session, user: User, status: str | None, limit: int, offset: int) -> dict:
    query = review_query(user, status)
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    txs = list(
        session.exec(query.order_by(Transaction.booking_date.desc(), Transaction.id.desc()).limit(limit).offset(offset))
    )
    suggestions = _loan_suggestions(session, [tx.id for tx in txs])
    return {
        "items": [{"transaction": tx, "suggested_loan": suggestions.get(tx.id)} for tx in txs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _loan_suggestions(session: Session, tx_ids: list[int]) -> dict[int, dict]:
    """Vorgeschlagene Kreditraten aus dem Import (noch nicht als Rate gebucht)."""
    if not tx_ids:
        return {}
    rows = session.exec(
        select(ImportRow.created_transaction_id, LoanScheduleEntry, Loan.id, Account.name)
        .join(LoanScheduleEntry, LoanScheduleEntry.id == ImportRow.suggested_loan_entry_id)
        .join(Loan, Loan.id == LoanScheduleEntry.loan_id)
        .join(Account, Account.id == Loan.account_id)
        .where(ImportRow.created_transaction_id.in_(tx_ids), LoanScheduleEntry.status == "planned")
    )
    paid = set(
        session.exec(
            select(LoanPayment.payment_transaction_id).where(LoanPayment.payment_transaction_id.in_(tx_ids))
        )
    )
    return {
        tx_id: {
            "loan_id": loan_id,
            "loan_name": name,
            "seq": entry.seq,
            "due_date": entry.due_date,
            "planned_installment": str(entry.planned_installment),
        }
        for tx_id, entry, loan_id, name in rows
        if tx_id not in paid
    }


def _confirm(session: Session, user: User, tx: Transaction, data: ReviewConfirm, category: Category | None) -> None:
    _assert_editable(session, tx)
    if data.as_transfer:
        assert_pair_unchanged(tx, {"kind": TransactionKind.TRANSFER})
    elif category is not None:
        assert_pair_unchanged(tx, {"kind": TransactionKind.REGULAR, "category_id": category.id})
    if tx.splits:
        if any(s.kind == TransactionKind.REGULAR and s.category_id is None for s in tx.splits):
            raise Invalid(f"Buchung {tx.id}: Aufteilung hat Zeilen ohne Kategorie", code="split_incomplete")
    elif data.as_transfer:
        tx.kind, tx.category_id, tx.category_source, tx.applied_rule_id = (
            TransactionKind.TRANSFER, None, CategorySource.MANUAL, None,
        )
    elif category is not None:
        tx.category_id, tx.category_source, tx.applied_rule_id = category.id, CategorySource.MANUAL, None
        tx.kind = TransactionKind.REGULAR
    elif tx.category_id is None and tx.kind == TransactionKind.REGULAR:
        raise Invalid(f"Buchung {tx.id} hat noch keine Kategorie", code="category_required")
    tx.review_status = ReviewStatus.CONFIRMED


def _category(session: Session, user: User, data: ReviewConfirm) -> Category | None:
    if data.as_transfer and data.category_id is not None:
        raise Invalid("Umbuchungen haben keine Kategorie", code="transfer_without_category")
    if data.category_id is None:
        return None
    category = get_owned(session, Category, data.category_id, user.id, "Kategorie")
    if not category.active:
        raise Invalid("Kategorie ist deaktiviert", code="category_inactive")
    return category


def confirm(session: Session, user: User, tx: Transaction, data: ReviewConfirm) -> Transaction:
    _confirm(session, user, tx, data, _category(session, user, data))
    session.flush()
    return tx


def bulk_confirm(session: Session, user: User, tx_ids: list[int], data: ReviewConfirm) -> int:
    """Alles oder nichts: erst alle Buchungen prüfen, dann gemeinsam ändern."""
    category = _category(session, user, data)
    txs = [get_owned(session, Transaction, tx_id, user.id, "Buchung") for tx_id in dict.fromkeys(tx_ids)]
    for tx in txs:
        _confirm(session, user, tx, data, category)
    session.flush()
    return len(txs)


def _assert_suggestion_valid(session: Session, tx: Transaction) -> None:
    """Ein Vorschlag ist nur bestätigbar, solange seine Kategorie aktiv ist (und bei KI-Vorschlägen
    weiterhin zur Buchungsrichtung passt) – sie kann sich seit dem Vorschlag geändert haben."""
    if tx.category_id is None:
        return
    category = session.get(Category, tx.category_id, with_for_update={"read": True})
    if category is None or not category.active:
        raise Invalid(f"Buchung {tx.id}: Kategorie ist deaktiviert", code="category_inactive")
    if tx.category_source == CategorySource.AI and category.type != ("expense" if tx.amount < 0 else "income"):
        raise Invalid(f"Buchung {tx.id}: Kategorie passt nicht mehr zur Buchung", code="category_type_mismatch")


def confirm_all_suggestions(session: Session, user: User) -> dict:
    """Alle automatisch zugeordneten Buchungen (Regel/KI) so bestätigen, wie vorgeschlagen.

    Anders als die Sammelbestätigung nicht „alles oder nichts“: Eine Buchung, die sich nicht
    bestätigen lässt (z. B. als Kreditrate gebucht), wird übersprungen und bleibt in der Liste.
    """
    txs = list(session.exec(review_query(user, ReviewStatus.AUTO_CATEGORIZED).order_by(Transaction.id)))
    confirmed, skipped = 0, 0
    for tx in txs:
        savepoint = session.begin_nested()
        try:
            _assert_suggestion_valid(session, tx)
            _confirm(session, user, tx, ReviewConfirm(), None)
            session.flush()
            savepoint.commit()
            confirmed += 1
        except AppError:
            savepoint.rollback()
            skipped += 1
    return {"confirmed": confirmed, "skipped": skipped}


def suggest_rule(session: Session, user: User, tx: Transaction) -> dict:
    """Bearbeitbarer Regelvorschlag – wird nicht gespeichert."""
    pattern, field = suggest_pattern(tx.description, tx.counterparty)
    if len(pattern) < 2:
        raise Invalid("Aus dieser Buchung lässt sich kein sinnvolles Muster ableiten", code="no_rule_suggestion")
    probe = MappingRule(user_id=user.id, pattern=pattern, match_type=MatchType.CONTAINS, match_field=field,
                        target_category_id=tx.category_id or 0)
    rules = RuleSet(session, user.id, rules=[probe])
    matching = sum(
        1 for other in session.exec(candidates_query(user)) if rules.winner(other.description, other.counterparty)
    )
    return {
        "name": pattern,
        "pattern": pattern,
        "match_type": MatchType.CONTAINS,
        "match_field": field,
        "target_category_id": tx.category_id,
        "matching_transactions": matching,
    }
