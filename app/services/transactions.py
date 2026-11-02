from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import and_, exists, not_, or_
from sqlmodel import Session, func, select

from app.errors import Conflict, Invalid
from app.models import Account, AccountType, Category, User
from app.models.imports import TransactionImportLink
from app.models.loan import LoanPayment
from app.models.transaction import (
    CategorySource,
    ReviewStatus,
    Transaction,
    TransactionKind,
    TransactionSource,
    TransactionSplit,
)
from app.schemas.filters import TransactionFilter
from app.schemas.transaction import SplitIn, TransactionCreate, TransferCreate
from app.services.common import get_owned
from app.services.iban import normalize_iban

# Bei importierten Buchungen sind die Bankdaten maßgeblich
_IMPORT_FIXED_FIELDS = ("account_id", "booking_date", "value_date", "amount")


# --- Filter -------------------------------------------------------------------


def category_with_descendants(session: Session, user_id: int, category_id: int) -> list[int]:
    tree = (
        select(Category.id)
        .where(Category.id == category_id, Category.user_id == user_id)
        .cte("tree", recursive=True)
    )
    tree = tree.union_all(select(Category.id).where(Category.parent_id == tree.c.id))
    return list(session.exec(select(tree.c.id)))


def _has_splits():
    return exists().where(TransactionSplit.transaction_id == Transaction.id)


def _uncategorized():
    """Reguläre Buchung (bzw. Split-Zeile) ohne Kategorie; Transfers brauchen keine."""
    unsplit = and_(
        Transaction.kind == TransactionKind.REGULAR,
        Transaction.category_id.is_(None),
        not_(_has_splits()),
    )
    open_line = exists().where(
        TransactionSplit.transaction_id == Transaction.id,
        TransactionSplit.kind == TransactionKind.REGULAR,
        TransactionSplit.category_id.is_(None),
    )
    return or_(unsplit, open_line)


def filtered_query(session: Session, user: User, f: TransactionFilter):
    """Gemeinsame Abfrage für Liste und Export."""
    query = select(Transaction).where(Transaction.user_id == user.id)
    if f.date_from:
        query = query.where(Transaction.booking_date >= f.date_from)
    if f.date_to:
        query = query.where(Transaction.booking_date <= f.date_to)
    if f.account_ids:
        query = query.where(Transaction.account_id.in_(f.account_ids))
    if f.institution_id is not None:
        query = query.where(
            Transaction.account_id.in_(
                select(Account.id).where(
                    Account.user_id == user.id, Account.institution_id == f.institution_id
                )
            )
        )
    if f.category_id is not None:
        ids = (
            category_with_descendants(session, user.id, f.category_id)
            if f.include_subcategories
            else [f.category_id]
        )
        query = query.where(
            or_(
                Transaction.category_id.in_(ids),
                exists().where(
                    TransactionSplit.transaction_id == Transaction.id,
                    TransactionSplit.category_id.in_(ids),
                ),
            )
        )
    if f.uncategorized is not None:
        query = query.where(_uncategorized() if f.uncategorized else not_(_uncategorized()))
    if f.kind is not None:
        query = query.where(
            or_(
                Transaction.kind == f.kind,
                exists().where(
                    TransactionSplit.transaction_id == Transaction.id,
                    TransactionSplit.kind == f.kind,
                ),
            )
        )
    if f.review_status is not None:
        query = query.where(Transaction.review_status == f.review_status)
    if f.source is not None:
        query = query.where(Transaction.source == f.source)
    if f.search:
        pattern = "%" + f.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(
            or_(
                Transaction.description.ilike(pattern, escape="\\"),
                Transaction.counterparty.ilike(pattern, escape="\\"),
            )
        )
    if f.amount_min is not None:
        query = query.where(Transaction.amount >= f.amount_min)
    if f.amount_max is not None:
        query = query.where(Transaction.amount <= f.amount_max)
    if not f.include_excluded:
        query = query.where(Transaction.excluded_at.is_(None))
    return query


def list_transactions(
    session: Session, user: User, f: TransactionFilter, *, limit: int, offset: int
) -> tuple[list[Transaction], int]:
    query = filtered_query(session, user, f)
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    items = session.exec(
        query.order_by(Transaction.booking_date.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), total


# --- Validierung --------------------------------------------------------------


def get_transaction(session: Session, user: User, transaction_id: int) -> Transaction:
    return get_owned(session, Transaction, transaction_id, user.id, "Buchung")


def check_booking_date(account: Account, booking_date: date) -> None:
    if booking_date < account.opening_balance_date:
        raise Invalid(
            "Buchungsdatum liegt vor dem Stichtag des Anfangssaldos – "
            "erst Stichtag und Anfangssaldo des Kontos anpassen",
            code="before_opening",
            details={"opening_balance_date": account.opening_balance_date},
        )


def bookable_account(session: Session, user: User, account_id: int, booking_date: date) -> Account:
    account = get_owned(session, Account, account_id, user.id, "Konto")
    if account.archived_at is not None:
        raise Conflict("Konto ist archiviert", code="account_archived")
    if account.type == AccountType.LOAN:
        raise Invalid(
            "Buchungen auf Kreditkonten entstehen über /loans", code="loan_account_via_loans"
        )
    check_booking_date(account, booking_date)
    return account


def _usable_category(session: Session, user: User, category_id: int) -> Category:
    category = get_owned(session, Category, category_id, user.id, "Kategorie")
    if not category.active:
        raise Invalid("Kategorie ist deaktiviert", code="category_inactive")
    return category


def _validate_lines(
    session: Session,
    user: User,
    amount: Decimal,
    kind: str,
    category_id: int | None,
    splits: Sequence[SplitIn],
) -> None:
    if kind == TransactionKind.TRANSFER and category_id is not None:
        raise Invalid("Umbuchungen haben keine Kategorie", code="transfer_without_category")
    if not splits:
        return
    if kind != TransactionKind.REGULAR or category_id is not None:
        raise Invalid(
            "Bei einer Aufteilung tragen die Zeilen Art und Kategorie, nicht die Buchung",
            code="split_on_line_level",
        )
    if len(splits) < 2:
        raise Invalid("Eine Aufteilung braucht mindestens zwei Zeilen", code="split_too_few")
    total = sum((s.amount for s in splits), Decimal("0"))
    if total != amount:
        raise Invalid(
            "Summe der Zeilen entspricht nicht dem Buchungsbetrag",
            code="split_sum_mismatch",
            details={"amount": amount, "split_sum": total},
        )
    for split in splits:
        if split.kind == TransactionKind.TRANSFER and split.category_id is not None:
            raise Invalid("Umbuchungs-Zeilen haben keine Kategorie", code="transfer_without_category")


def _categorization(kind: str, category_id: int | None, splits: Sequence) -> tuple[str, str]:
    """(review_status, category_source) für eine manuelle Erfassung."""
    if splits:
        lines = [(s.kind, s.category_id) for s in splits]
    else:
        lines = [(kind, category_id)]
    complete = all(k == TransactionKind.TRANSFER or c is not None for k, c in lines)
    if complete:
        return ReviewStatus.CONFIRMED, CategorySource.MANUAL
    has_any = any(c is not None for _, c in lines)
    return ReviewStatus.NEEDS_REVIEW, (CategorySource.MANUAL if has_any else CategorySource.NONE)


def _new_split_rows(user: User, splits: Sequence[SplitIn]) -> list[TransactionSplit]:
    return [
        TransactionSplit(
            user_id=user.id, line_no=i, amount=s.amount, kind=s.kind, category_id=s.category_id
        )
        for i, s in enumerate(splits, start=1)
    ]


def _assert_editable(session: Session, tx: Transaction) -> None:
    if tx.source == TransactionSource.LOAN:
        raise Conflict(
            "Kreditbuchungen werden über /loans geändert", code="loan_transaction_via_loans"
        )
    if session.exec(select(LoanPayment.id).where(LoanPayment.payment_transaction_id == tx.id)).first():
        raise Conflict(
            "Zahlung ist als Kreditrate gebucht – Änderungen über /loans (Rate stornieren)",
            code="loan_payment_via_loans",
        )


# --- Schreiben ----------------------------------------------------------------


def create_transaction(session: Session, user: User, data: TransactionCreate) -> Transaction:
    bookable_account(session, user, data.account_id, data.booking_date)
    splits = data.splits or []
    _validate_lines(session, user, data.amount, data.kind, data.category_id, splits)
    for category_id in {data.category_id, *(s.category_id for s in splits)} - {None}:
        _usable_category(session, user, category_id)

    review_status, category_source = _categorization(data.kind, data.category_id, splits)
    tx = Transaction(
        user_id=user.id,
        account_id=data.account_id,
        booking_date=data.booking_date,
        value_date=data.value_date,
        amount=data.amount,
        description=data.description,
        counterparty=data.counterparty,
        counterparty_iban=normalize_iban(data.counterparty_iban) if data.counterparty_iban else None,
        kind=data.kind,
        category_id=data.category_id,
        review_status=review_status,
        category_source=category_source,
        source=TransactionSource.MANUAL,
        splits=_new_split_rows(user, splits),
    )
    session.add(tx)
    session.flush()
    return tx


def update_transaction(
    session: Session, user: User, tx: Transaction, changes: dict
) -> Transaction:
    _assert_editable(session, tx)
    # Auch manuelle Buchungen, die als Dublette einer Bankzeile bestätigt wurden, tragen
    # eine Importidentität – ihre Bankfelder dürfen sich nicht mehr unbemerkt verschieben
    if has_import_identity(session, tx):
        fixed = sorted(k for k in _IMPORT_FIXED_FIELDS if k in changes and changes[k] != getattr(tx, k))
        if fixed:
            raise Invalid(
                "Bei importierten Buchungen sind Konto, Datum und Betrag fest – "
                "fehlerhafte Buchungen stattdessen ausschließen",
                code="imported_fields_fixed",
                details={"fields": fixed},
            )
    assert_pair_unchanged(tx, changes)

    account_id = changes.get("account_id", tx.account_id)
    booking_date = changes.get("booking_date", tx.booking_date)
    if "account_id" in changes and account_id != tx.account_id:
        bookable_account(session, user, account_id, booking_date)
    elif "booking_date" in changes:
        check_booking_date(session.get(Account, account_id), booking_date)

    amount = changes.get("amount", tx.amount)
    kind = changes.get("kind", tx.kind)
    category_id = changes.get("category_id", tx.category_id)
    splits_changed = "splits" in changes
    if splits_changed:
        lines = [SplitIn.model_validate(s) for s in (changes.pop("splits") or [])]
    else:
        # Bestehende Aufteilung bleibt – prüfen, ob sie zu Betrag/Art noch passt
        lines = [SplitIn(amount=s.amount, kind=s.kind, category_id=s.category_id) for s in tx.splits]
    _validate_lines(session, user, amount, kind, category_id, lines)

    # Neu zugeordnete Kategorien müssen aktiv sein; bestehende Zuordnungen bleiben gültig
    if changes.get("category_id") not in (None, tx.category_id):
        _usable_category(session, user, changes["category_id"])
    if splits_changed:
        known = {s.category_id for s in tx.splits}
        for cid in {line.category_id for line in lines} - known - {None}:
            _usable_category(session, user, cid)

    categorization_changed = splits_changed or "kind" in changes or "category_id" in changes
    if changes.get("counterparty_iban"):
        changes["counterparty_iban"] = normalize_iban(changes["counterparty_iban"])
    for key, value in changes.items():
        setattr(tx, key, value)

    if splits_changed:
        tx.splits.clear()
        session.flush()
        tx.splits.extend(_new_split_rows(user, lines))
    if categorization_changed:
        tx.review_status, tx.category_source = _categorization(kind, category_id, lines)
        tx.applied_rule_id = None
    session.flush()
    return tx


def assert_pair_unchanged(tx: Transaction, changes: dict) -> None:
    """Gekoppelte Umbuchung: Konto, Datum, Betrag und Art nur gemeinsam änderbar.

    Gilt für alle Änderungswege (Bearbeiten, Prüfliste), sonst würde eine Seite zur
    Ausgabe/Einnahme, während die Gegenseite eine Umbuchung bleibt.
    """
    if tx.transfer_peer_id is None:
        return
    paired = sorted(
        k for k in ("account_id", "booking_date", "amount", "kind")
        if k in changes and changes[k] != getattr(tx, k)
    )
    if paired or changes.get("category_id") is not None:
        raise Invalid(
            "Teil einer Umbuchung – zum Ändern beide Seiten löschen und neu anlegen",
            code="transfer_pair_linked",
            details={"fields": paired or ["category_id"]},
        )


def has_import_identity(session: Session, tx: Transaction) -> bool:
    """Importiert oder als Dublette einer Importzeile bestätigt."""
    if tx.source == TransactionSource.IMPORT:
        return True
    return session.exec(
        select(TransactionImportLink.id).where(TransactionImportLink.transaction_id == tx.id)
    ).first() is not None


def delete_transaction(session: Session, tx: Transaction) -> None:
    _assert_editable(session, tx)
    if has_import_identity(session, tx):
        raise Conflict(
            "Importierte Buchungen werden ausgeschlossen statt gelöscht, "
            "damit ein erneuter Import sie nicht wiederherstellt",
            code="imported_use_exclude",
        )
    # Umbuchung: Gegenseite mitlöschen, sonst entstünde Geld aus dem Nichts – aber nur,
    # wenn auch sie gelöscht werden darf (keine Bank-Identität, keine Kreditbuchung)
    peer = session.get(Transaction, tx.transfer_peer_id) if tx.transfer_peer_id else None
    if peer is not None:
        if peer.source != TransactionSource.MANUAL or has_import_identity(session, peer):
            raise Conflict(
                "Die Gegenseite dieser Umbuchung ist mit Bankdaten abgeglichen – "
                "die Umbuchung als Ganzes ausschließen statt löschen",
                code="transfer_peer_imported",
            )
        session.delete(peer)
    session.delete(tx)
    session.flush()


def set_excluded(session: Session, tx: Transaction, reason: str | None) -> Transaction:
    """Schließt eine importierte Buchung aus Salden und Berichten aus (oder hebt das auf)."""
    _assert_editable(session, tx)
    peer = session.get(Transaction, tx.transfer_peer_id) if tx.transfer_peer_id else None
    if not has_import_identity(session, tx) and not (peer and has_import_identity(session, peer)):
        raise Invalid(
            "Nur importierte Buchungen werden ausgeschlossen – manuelle bitte löschen",
            code="manual_use_delete",
        )
    # Umbuchungspaare werden gemeinsam aus- bzw. eingeschlossen, sonst bliebe eine Seite
    # wirksam und das Nettovermögen änderte sich allein durch den Ausschluss
    if peer is not None:
        _assert_editable(session, peer)
    for side in (tx, peer) if peer is not None else (tx,):
        side.excluded_at = datetime.now(UTC) if reason else None
        side.excluded_reason = reason
    session.flush()
    return tx


def create_transfer(session: Session, user: User, data: TransferCreate) -> tuple[Transaction, Transaction]:
    if data.from_account_id == data.to_account_id:
        raise Invalid("Quell- und Zielkonto sind identisch", code="transfer_same_account")
    source = bookable_account(session, user, data.from_account_id, data.booking_date)
    target = bookable_account(session, user, data.to_account_id, data.booking_date)

    def _side(account: Account, amount: Decimal, other: Account) -> Transaction:
        return Transaction(
            user_id=user.id,
            account_id=account.id,
            booking_date=data.booking_date,
            amount=amount,
            description=data.description,
            counterparty=other.name,
            counterparty_iban=other.iban_normalized,
            kind=TransactionKind.TRANSFER,
            review_status=ReviewStatus.CONFIRMED,
            category_source=CategorySource.MANUAL,
            source=TransactionSource.MANUAL,
        )

    outgoing = _side(source, -data.amount, target)
    incoming = _side(target, data.amount, source)
    session.add_all([outgoing, incoming])
    session.flush()
    outgoing.transfer_peer_id = incoming.id
    incoming.transfer_peer_id = outgoing.id
    session.flush()
    return outgoing, incoming
