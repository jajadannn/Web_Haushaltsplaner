"""Zuordnen statt doppelt zählen (Phase 7): Umbuchungen, Erstattungen (Idee 06), Split-Vorlagen (Idee 13).

- Umbuchung: Abfluss auf einem eigenen Konto und gleich hoher Zufluss auf einem anderen eigenen Konto
  innerhalb von drei Tagen, wobei die Gegenpartei-IBAN das jeweils andere eigene Konto ist. Annahme
  macht beide Buchungen zu einem Umbuchungspaar – das Vermögen ändert sich dadurch nicht mehr.
- Erstattung: Zufluss derselben Gegenpartei bis 90 Tage nach einer kategorisierten Ausgabe und
  höchstens in deren Höhe. Annahme ordnet der Erstattung die Kategorie des Einkaufs zu (mindert die
  Ausgaben) und merkt die Verknüpfung, damit sie nicht doppelt zugeordnet wird.
- Split-Vorlagen: Wurde dieselbe Gegenpartei mindestens zweimal gleich aufgeteilt (gleiche Kategorien
  und Beträge), wird eine neue Buchung mit gleichem Gesamtbetrag zur Aufteilung vorgeschlagen.
  Aus einem Gesamtbetrag ohne Beleg werden keine Einzelkategorien geraten. Kreditbuchungen nie.
"""

import hashlib
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from app.errors import Conflict
from app.models import (
    Account,
    AccountType,
    Category,
    CategorySource,
    LoanPayment,
    RefundLink,
    ReviewStatus,
    Suggestion,
    SuggestionKind,
    Transaction,
    TransactionKind,
    TransactionSource,
    User,
)
from app.schemas.transaction import SplitIn
from app.services import analysis, settings, suggestions
from app.services.iban import normalize_iban
from app.services.recurring import normalize_name
from app.services.suggestions import Found, Handler
from app.services.transactions import update_transaction

WINDOW_DAYS = 120


def _recent(session: Session, user: User, today: date):
    return session.exec(select(Transaction).where(
        Transaction.user_id == user.id, Transaction.excluded_at.is_(None),
        Transaction.booking_date >= today - timedelta(days=WINDOW_DAYS),
        Transaction.source != TransactionSource.LOAN,
    ).order_by(Transaction.booking_date, Transaction.id)).all()


def _is_loan_payment(session: Session, tx_id: int) -> bool:
    return session.exec(select(LoanPayment.id).where(LoanPayment.payment_transaction_id == tx_id)).first() is not None


# --- Umbuchungen ---------------------------------------------------------------------------------


def detect_transfers(session: Session, user: User, today: date) -> list[Found]:
    own = {a.iban_normalized: a for a in session.exec(select(Account).where(
        Account.user_id == user.id, Account.type != AccountType.LOAN, Account.iban_normalized.is_not(None)))}
    by_id = {a.id: a for a in own.values()}
    candidates = [t for t in _recent(session, user, today)
                  if t.kind == TransactionKind.REGULAR and t.transfer_peer_id is None and not t.splits
                  and t.account_id in by_id]
    outs = [t for t in candidates if t.amount < 0]
    ins = [t for t in candidates if t.amount > 0]
    used: set[int] = set()
    found = []
    for out in outs:
        target = own.get(normalize_iban(out.counterparty_iban or "")) if out.counterparty_iban else None
        if target is None or target.id == out.account_id:
            continue
        options = [t for t in ins if t.id not in used and t.account_id == target.id and t.amount == -out.amount
                   and abs((t.booking_date - out.booking_date).days) <= 3]
        if not options:
            continue
        match = min(options, key=lambda t: abs((t.booking_date - out.booking_date).days))
        back = normalize_iban(match.counterparty_iban or "") if match.counterparty_iban else None
        if back is not None and back != by_id[out.account_id].iban_normalized:
            continue
        used.add(match.id)
        found.append(Found(
            fingerprint=f"transfer:{out.id}|{match.id}",
            payload={"transaction_ids": [out.id, match.id], "amount": -out.amount,
                     "from_account": by_id[out.account_id].name, "to_account": target.name,
                     "dates": [out.booking_date, match.booking_date]},
            evidence={},
            reason=f"{-out.amount} € von {by_id[out.account_id].name} an {target.name} – als Umbuchung zwischen "
                   "eigenen Konten zusammenfassen? (Dann zählt sie weder als Ausgabe noch als Einnahme.)",
            priority=2,
        ))
    return found


def _transfer_apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    a_id, b_id = suggestion.payload["transaction_ids"]
    a = session.get(Transaction, a_id, with_for_update=True)
    b = session.get(Transaction, b_id, with_for_update=True)
    for tx in (a, b):
        if tx is None or tx.user_id != user.id or tx.transfer_peer_id is not None or tx.splits \
                or _is_loan_payment(session, tx.id):
            raise Conflict("Die Buchungen haben sich geändert", code="suggestion_stale")
    a.transfer_peer_id, b.transfer_peer_id = b.id, a.id
    for tx in (a, b):
        tx.kind, tx.category_id = TransactionKind.TRANSFER, None
        tx.review_status, tx.category_source, tx.applied_rule_id = ReviewStatus.CONFIRMED, CategorySource.MANUAL, None
    session.flush()
    return "transaction", a.id


suggestions.register(SuggestionKind.TRANSFER_MATCH, Handler(validate=lambda s, u, x: None, apply=_transfer_apply))


# --- Erstattungen --------------------------------------------------------------------------------


def detect_refunds(session: Session, user: User, today: date) -> list[Found]:
    linked = set(session.exec(select(RefundLink.refund_transaction_id).where(RefundLink.user_id == user.id)).all())
    categories = {c.id: c for c in session.exec(select(Category).where(Category.user_id == user.id))}
    txs = [t for t in _recent(session, user, today) if t.kind == TransactionKind.REGULAR and not t.splits]
    purchases: dict[str, list[Transaction]] = defaultdict(list)
    for t in txs:
        category = categories.get(t.category_id)
        if t.amount < 0 and category is not None and category.type == "expense":
            key = normalize_name(t.counterparty or "")
            if key:
                purchases[key].append(t)
    found = []
    for refund in txs:
        if refund.amount <= 0 or refund.id in linked or refund.review_status == ReviewStatus.CONFIRMED:
            continue
        category = categories.get(refund.category_id)
        if category is not None and category.type == "income":
            continue
        options = [p for p in purchases.get(normalize_name(refund.counterparty or ""), [])
                   if 0 <= (refund.booking_date - p.booking_date).days <= 90 and refund.amount <= -p.amount]
        if not options:
            continue
        original = min(options, key=lambda p: (abs(-p.amount - refund.amount), -p.booking_date.toordinal()))
        partial = refund.amount < -original.amount
        found.append(Found(
            fingerprint=f"refund:{refund.id}|{original.id}",
            payload={"refund_id": refund.id, "original_id": original.id, "amount": refund.amount,
                     "original_amount": -original.amount, "category_id": original.category_id,
                     "category": categories[original.category_id].name, "partial": partial,
                     "counterparty": refund.counterparty, "alternatives": len(options) - 1},
            evidence={},
            reason=f"Die Gutschrift über {refund.amount} € von „{refund.counterparty}“ gehört vermutlich zum Einkauf "
                   f"vom {original.booking_date:%d.%m.%Y} ({-original.amount} €)"
                   + (" – Teilerstattung" if partial else "")
                   + (f"; {len(options) - 1} weitere Einkäufe kämen in Frage" if len(options) > 1 else "") + ".",
        ))
    return found


def _refund_apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    refund = session.get(Transaction, suggestion.payload["refund_id"], with_for_update=True)
    original_id = overrides.get("original_id", suggestion.payload["original_id"])
    original = session.get(Transaction, original_id)
    if refund is None or original is None or original.user_id != user.id or refund.user_id != user.id:
        raise Conflict("Die Buchungen gibt es nicht mehr", code="suggestion_stale")
    if session.exec(select(RefundLink.id).where(RefundLink.refund_transaction_id == refund.id)).first():
        raise Conflict("Die Gutschrift ist bereits zugeordnet", code="suggestion_stale")
    update_transaction(session, user, refund, {"category_id": original.category_id})
    refund.review_status, refund.category_source = ReviewStatus.CONFIRMED, CategorySource.MANUAL
    session.add(RefundLink(user_id=user.id, refund_transaction_id=refund.id, original_transaction_id=original.id))
    session.flush()
    return "transaction", refund.id


suggestions.register(SuggestionKind.REFUND_MATCH, Handler(validate=lambda s, u, x: None, apply=_refund_apply))


# --- Split-Vorlagen ------------------------------------------------------------------------------


def _template(tx: Transaction) -> tuple:
    return tuple(sorted((str(s.amount), s.kind, s.category_id) for s in tx.splits))


def detect_split_templates(session: Session, user: User, today: date) -> list[Found]:
    txs = _recent(session, user, today)
    confirmed: dict[str, list[Transaction]] = defaultdict(list)
    for t in txs:
        if t.splits and t.review_status == ReviewStatus.CONFIRMED and not _is_loan_payment(session, t.id):
            key = normalize_name(t.counterparty or "")
            if key:
                confirmed[key].append(t)
    templates: dict[str, tuple] = {}
    for key, items in confirmed.items():
        shapes = defaultdict(list)
        for t in items:
            shapes[_template(t)].append(t)
        shape, examples = max(shapes.items(), key=lambda kv: len(kv[1]))
        if len(examples) >= 2:
            templates[key] = (shape, examples[-1])
    found = []
    for t in txs:
        if t.splits or t.review_status == ReviewStatus.CONFIRMED or t.kind != TransactionKind.REGULAR:
            continue
        key = normalize_name(t.counterparty or "")
        if key not in templates or _is_loan_payment(session, t.id):
            continue
        shape, example = templates[key]
        total = sum((Decimal(amount) for amount, _, _ in shape), Decimal("0"))
        if total != t.amount:
            continue  # nur exakt gleicher Gesamtbetrag – nichts raten
        lines = [{"amount": amount, "kind": kind, "category_id": category_id} for amount, kind, category_id in shape]
        found.append(Found(
            fingerprint=f"split:{t.id}|{hashlib.sha256(repr(shape).encode()).hexdigest()[:16]}",
            payload={"transaction_id": t.id, "counterparty": t.counterparty, "lines": lines,
                     "template_from": example.id},
            evidence={},
            reason=f"„{t.counterparty}“ wurde bisher immer so aufgeteilt – diese Buchung genauso aufteilen?",
        ))
    return found


def _split_apply(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    tx = session.get(Transaction, suggestion.payload["transaction_id"], with_for_update=True)
    if tx is None or tx.user_id != user.id or tx.splits:
        raise Conflict("Die Buchung hat sich geändert", code="suggestion_stale")
    splits = [SplitIn(amount=Decimal(line["amount"]), kind=line["kind"], category_id=line["category_id"])
              for line in suggestion.payload["lines"]]
    update_transaction(session, user, tx, {"splits": splits})
    tx.review_status = ReviewStatus.CONFIRMED
    session.flush()
    return "transaction", tx.id


suggestions.register(SuggestionKind.SPLIT_TEMPLATE, Handler(
    validate=lambda s, u, x: None, apply=_split_apply, setting="automation.split_templates",
    is_clear=lambda s: True,
))


def refresh(session: Session, user: User, today: date) -> dict[str, int]:
    totals = {"new": 0, "updated": 0, "stale": 0}
    for kind, detect, generator in (
        (SuggestionKind.TRANSFER_MATCH, detect_transfers, "transfer-v1"),
        (SuggestionKind.REFUND_MATCH, detect_refunds, "refund-v1"),
        (SuggestionKind.SPLIT_TEMPLATE, detect_split_templates, "split-v1"),
    ):
        result = suggestions.sync(session, user, kind, detect(session, user, today), generator)
        totals = {k: totals[k] + result[k] for k in totals}
    return totals


analysis.register("matching", refresh)
_ = settings
