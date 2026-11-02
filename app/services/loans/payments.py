"""Raten buchen/stornieren und Belastungen des Kreditkontos.

Eine Rate wird auf der Zahlung (z. B. Girokonto) aufgeteilt:
Tilgung = Umbuchung aufs Kreditkonto, Zinsen und Gebühren = Ausgaben in den
Systemkategorien. Die Tilgung erscheint als Gegenbuchung auf dem Kreditkonto.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import extract
from sqlmodel import Session, func, select

from app import clock
from app.errors import Conflict, Invalid, NotFound
from app.models import (
    Account,
    AccountType,
    Category,
    CategorySource,
    ReviewStatus,
    Transaction,
    TransactionKind,
    TransactionSource,
    TransactionSplit,
    User,
)
from app.models.loan import Loan, LoanPayment, LoanScheduleEntry, LoanStatus, ScheduleStatus
from app.schemas.loan import LoanChargeCreate, LoanPaymentCreate
from app.services.categories import get_system_category
from app.services.common import get_owned
from app.services.loans.core import (
    _loan_transaction,
    get_entry,
    open_entries,
    rebuild_schedule,
    remaining_debt,
)
from app.services.loans.schedule import ZERO, accrued_interest, split_payment
from app.services.transactions import bookable_account, check_booking_date

LOAN_INTEREST = "loan_interest"
LOAN_FEES = "loan_fees"


def _payment_transaction(
    session: Session, user: User, loan: Loan, data: LoanPaymentCreate
) -> tuple[Transaction, bool]:
    """Vorhandene Zahlung prüfen oder eine neue anlegen; zweiter Wert: neu angelegt?"""
    if data.transaction_id is not None:
        if any(v is not None for v in (data.account_id, data.booking_date, data.amount, data.description)):
            raise Invalid(
                "Entweder eine vorhandene Zahlung (transaction_id) oder eine neue Zahlung angeben",
                code="payment_source_ambiguous",
            )
        tx = get_owned(session, Transaction, data.transaction_id, user.id, "Buchung")
        linked = session.exec(
            select(LoanPayment).where(LoanPayment.payment_transaction_id == tx.id)
        ).first()
        if linked is not None:
            raise Conflict("Zahlung ist bereits einer Kreditrate zugeordnet", code="payment_already_linked")
        if tx.amount >= 0 or tx.source == TransactionSource.LOAN or tx.excluded_at is not None:
            raise Invalid("Zahlung muss eine gültige Abbuchung sein", code="invalid_payment_transaction")
        if tx.transfer_peer_id is not None:
            raise Invalid("Teil einer Umbuchung – kann keine Kreditrate sein", code="invalid_payment_transaction")
        if session.get(Account, tx.account_id).type == AccountType.LOAN:
            raise Invalid("Zahlung muss von einem Zahlkonto kommen", code="invalid_payment_transaction")
        return tx, False

    if data.booking_date is None or data.amount is None:
        raise Invalid("Für eine neue Zahlung booking_date und amount angeben", code="payment_data_missing")
    account_id = data.account_id or loan.payment_account_id
    if account_id is None:
        raise Invalid("Zahlkonto angeben (account_id) oder beim Kredit hinterlegen", code="payment_account_missing")
    bookable_account(session, user, account_id, data.booking_date)
    tx = Transaction(
        user_id=user.id,
        account_id=account_id,
        booking_date=data.booking_date,
        amount=-data.amount,
        description=data.description or f"Kreditrate {loan.lender_name}",
        counterparty=loan.lender_name,
        counterparty_iban=loan.lender_iban,
        review_status=ReviewStatus.CONFIRMED,
        category_source=CategorySource.LOAN,
        source=TransactionSource.MANUAL,
    )
    session.add(tx)
    return tx, True


def _target_entry(session: Session, loan: Loan, seq: int | None) -> LoanScheduleEntry | None:
    if seq is None:
        entries = open_entries(session, loan)
        return entries[0] if entries else None
    entry = get_entry(session, loan, seq)
    if entry.status != ScheduleStatus.PLANNED:
        raise Conflict(f"Rate {seq} ist nicht offen", code="installment_not_open")
    return entry


def _last_payment_date(session: Session, loan: Loan) -> date:
    last = session.exec(select(func.max(LoanPayment.booking_date)).where(LoanPayment.loan_id == loan.id)).one()
    return last or session.get(Account, loan.account_id).opening_balance_date


def suggest_split(
    session: Session, loan: Loan, amount: Decimal, booking_date: date, entry: LoanScheduleEntry | None
) -> tuple[Decimal, Decimal, Decimal]:
    """(Zinsen, Tilgung, Gebühren): zuerst Gebühren, dann Zinsen, Rest Tilgung."""
    if entry is not None:
        interest_due, extra_due = entry.planned_interest, entry.planned_extra
    else:
        # Ohne Plan (Privatkredit): taggenau aufgelaufene Zinsen seit der letzten Zahlung
        days = (booking_date - _last_payment_date(session, loan)).days
        interest_due = accrued_interest(remaining_debt(session, loan), loan.annual_interest_rate, days)
        extra_due = loan.extra_amount
    return split_payment(amount, interest_due=interest_due, extra_due=extra_due)


def _apply_lines(
    session: Session, user: User, tx: Transaction, interest: Decimal, principal: Decimal, extra: Decimal
) -> None:
    """Teilt die Zahlung auf; mit nur einem Anteil ohne Split-Zeilen."""
    lines: list[tuple[Decimal, str, Category | None]] = []
    if principal:
        lines.append((principal, TransactionKind.TRANSFER, None))
    if interest:
        lines.append((interest, TransactionKind.REGULAR, get_system_category(session, user.id, LOAN_INTEREST)))
    if extra:
        lines.append((extra, TransactionKind.REGULAR, get_system_category(session, user.id, LOAN_FEES)))

    tx.splits.clear()
    session.flush()
    if len(lines) == 1:
        _, tx.kind, category = lines[0]
        tx.category_id = category.id if category else None
    else:
        tx.kind, tx.category_id = TransactionKind.REGULAR, None
        tx.splits.extend(
            TransactionSplit(
                user_id=user.id, line_no=i, amount=-amount, kind=kind,
                category_id=category.id if category else None,
            )
            for i, (amount, kind, category) in enumerate(lines, start=1)
        )
    tx.review_status = ReviewStatus.CONFIRMED
    tx.category_source = CategorySource.LOAN
    tx.applied_rule_id = None


def record_payment(session: Session, user: User, loan: Loan, data: LoanPaymentCreate) -> LoanPayment:
    if loan.status == LoanStatus.PAID_OFF:
        raise Conflict("Kredit ist bereits vollständig getilgt", code="loan_paid_off")
    tx, owns_tx = _payment_transaction(session, user, loan, data)
    amount = -tx.amount
    loan_account = session.get(Account, loan.account_id)
    check_booking_date(loan_account, tx.booking_date)
    entry = _target_entry(session, loan, data.schedule_seq)

    overrides = (data.interest, data.principal, data.extra)
    if any(v is not None for v in overrides):
        if any(v is None for v in overrides):
            raise Invalid("interest, principal und extra zusammen angeben", code="split_override_incomplete")
        interest, principal, extra = overrides
        if interest + principal + extra != amount:
            raise Invalid(
                "Aufteilung entspricht nicht dem Zahlbetrag",
                code="split_sum_mismatch",
                details={"amount": amount, "split_sum": interest + principal + extra},
            )
    else:
        interest, principal, extra = suggest_split(session, loan, amount, tx.booking_date, entry)

    remaining = remaining_debt(session, loan)
    if principal > remaining:
        raise Invalid(
            "Tilgungsanteil ist höher als die Restschuld",
            code="principal_exceeds_debt",
            details={"principal": principal, "remaining_debt": remaining},
        )

    _apply_lines(session, user, tx, interest, principal, extra)
    session.flush()
    loan_tx = None
    if principal > 0:
        payer = session.get(Account, tx.account_id)
        loan_tx = _loan_transaction(
            user, loan.account_id, tx.booking_date, principal, "Tilgung",
            kind=TransactionKind.TRANSFER, counterparty=payer.name,
        )
        session.add(loan_tx)
        session.flush()

    payment = LoanPayment(
        loan_id=loan.id,
        payment_transaction_id=tx.id,
        loan_transaction_id=loan_tx.id if loan_tx else None,
        owns_payment_transaction=owns_tx,
        booking_date=tx.booking_date,
        interest=interest,
        principal=principal,
        extra=extra,
    )
    session.add(payment)
    session.flush()
    if entry is not None:
        entry.status = ScheduleStatus.PAID
        entry.payment_id = payment.id
    session.flush()
    rebuild_schedule(session, loan)
    return payment


def list_payments(session: Session, loan: Loan) -> list[tuple[LoanPayment, int | None]]:
    rows = session.exec(
        select(LoanPayment, LoanScheduleEntry.seq)
        .join(LoanScheduleEntry, LoanScheduleEntry.payment_id == LoanPayment.id, isouter=True)
        .where(LoanPayment.loan_id == loan.id)
        .order_by(LoanPayment.booking_date, LoanPayment.id)
    )
    return list(rows)


def delete_payment(session: Session, loan: Loan, payment_id: int) -> None:
    """Storniert die zuletzt gebuchte Rate (spätere Raten bauen auf ihr auf)."""
    payment = session.get(LoanPayment, payment_id)
    if payment is None or payment.loan_id != loan.id:
        raise NotFound(f"Zahlung {payment_id} nicht gefunden")
    latest = session.exec(
        select(LoanPayment)
        .where(LoanPayment.loan_id == loan.id)
        .order_by(LoanPayment.booking_date.desc(), LoanPayment.id.desc())
    ).first()
    if latest.id != payment.id:
        raise Conflict("Nur die zuletzt gebuchte Rate kann storniert werden", code="payment_not_latest")

    entry = session.exec(select(LoanScheduleEntry).where(LoanScheduleEntry.payment_id == payment.id)).first()
    if entry is not None:
        entry.status, entry.payment_id = ScheduleStatus.PLANNED, None
    tx = session.get(Transaction, payment.payment_transaction_id)
    loan_tx = session.get(Transaction, payment.loan_transaction_id) if payment.loan_transaction_id else None
    session.delete(payment)
    session.flush()
    if loan_tx is not None:
        session.delete(loan_tx)
    if payment.owns_payment_transaction:
        session.delete(tx)
    else:
        # Vorhandene (z. B. importierte) Zahlung bleibt, wird aber wieder zur offenen Prüfung
        tx.splits.clear()
        tx.kind, tx.category_id = TransactionKind.REGULAR, None
        tx.review_status, tx.category_source = ReviewStatus.NEEDS_REVIEW, CategorySource.NONE
    session.flush()
    rebuild_schedule(session, loan)


def is_loan_payment(session: Session, tx: Transaction) -> bool:
    return session.exec(
        select(LoanPayment.id).where(LoanPayment.payment_transaction_id == tx.id)
    ).first() is not None


# --- Belastungen direkt auf dem Kreditkonto -----------------------------------


def add_charge(session: Session, user: User, loan: Loan, data: LoanChargeCreate) -> Transaction:
    """Zinsen/Gebühren, die dem Kreditkonto belastet werden (z. B. kapitalisierte Zinsen)."""
    loan_account = session.get(Account, loan.account_id)
    check_booking_date(loan_account, data.booking_date)
    is_interest = data.charge_type == "interest"
    category = get_system_category(session, user.id, LOAN_INTEREST if is_interest else LOAN_FEES)
    tx = _loan_transaction(
        user, loan.account_id, data.booking_date, -data.amount,
        data.description or ("Zinsbelastung" if is_interest else "Gebühr"),
        kind=TransactionKind.REGULAR, category_id=category.id,
    )
    session.add(tx)
    session.flush()
    rebuild_schedule(session, loan)
    return tx


def delete_charge(session: Session, loan: Loan, transaction_id: int) -> None:
    tx = session.get(Transaction, transaction_id)
    if (
        tx is None
        or tx.account_id != loan.account_id
        or tx.source != TransactionSource.LOAN
        or tx.kind != TransactionKind.REGULAR
    ):
        raise NotFound(f"Belastung {transaction_id} nicht gefunden")
    session.delete(tx)
    session.flush()
    rebuild_schedule(session, loan)


# --- Auswertungen -------------------------------------------------------------


def upcoming(session: Session, user: User, days: int, today: date | None = None) -> list[dict]:
    today = today or clock.today()
    horizon = date.fromordinal(today.toordinal() + days)
    rows = session.exec(
        select(LoanScheduleEntry, Loan, Account.name)
        .join(Loan, Loan.id == LoanScheduleEntry.loan_id)
        .join(Account, Account.id == Loan.account_id)
        .where(
            Loan.user_id == user.id,
            Loan.status == LoanStatus.ACTIVE,
            LoanScheduleEntry.status == ScheduleStatus.PLANNED,
            LoanScheduleEntry.due_date <= horizon,
        )
        .order_by(LoanScheduleEntry.due_date, Loan.id)
    )
    return [
        {
            "loan_id": loan.id,
            "loan_name": name,
            "seq": entry.seq,
            "due_date": entry.due_date,
            "planned_installment": entry.planned_installment,
            "payment_account_id": loan.payment_account_id,
            "overdue": entry.due_date < today,
        }
        for entry, loan, name in rows
    ]


def year_summary(session: Session, user: User, loan: Loan, year: int) -> dict:
    """Gezahlte Zinsen/Tilgung/Gebühren und Belastungen eines Jahres (z. B. für die Steuer)."""
    count, interest, principal, extra = session.exec(
        select(
            func.count(LoanPayment.id),
            func.coalesce(func.sum(LoanPayment.interest), 0),
            func.coalesce(func.sum(LoanPayment.principal), 0),
            func.coalesce(func.sum(LoanPayment.extra), 0),
        ).where(LoanPayment.loan_id == loan.id, extract("year", LoanPayment.booking_date) == year)
    ).one()
    interest_cat = get_system_category(session, user.id, LOAN_INTEREST)
    charges = session.exec(
        select(Transaction.category_id, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.account_id == loan.account_id,
            Transaction.source == TransactionSource.LOAN,
            Transaction.kind == TransactionKind.REGULAR,
            Transaction.excluded_at.is_(None),
            extract("year", Transaction.booking_date) == year,
        )
        .group_by(Transaction.category_id)
    )
    interest_charged = fees_charged = ZERO
    for category_id, total in charges:
        if category_id == interest_cat.id:
            interest_charged += -total
        else:
            fees_charged += -total
    return {
        "year": year,
        "payments": count,
        "interest_paid": interest,
        "principal_paid": principal,
        "extra_paid": extra,
        "interest_charged": interest_charged,
        "fees_charged": fees_charged,
        "remaining_debt_end_of_year": remaining_debt(session, loan, date(year, 12, 31)),
    }
