"""Erkennt Kreditraten unter importierten Abbuchungen.

Kandidat ist die nächste offene Planrate eines aktiven Kredits, wenn die Abbuchung vom
hinterlegten Zahlkonto kommt, Gegen-IBAN oder Verwendungszweck zum Kreditgeber passen
und die Fälligkeit höchstens 7 Tage entfernt liegt. Automatisch gebucht wird nur bei
genau einem Kandidaten mit exakt passendem Betrag – sonst bleibt es ein Vorschlag.
"""

from datetime import timedelta

from sqlmodel import Session, select

from app.errors import AppError
from app.models import Loan, LoanScheduleEntry, LoanStatus, ScheduleStatus, Transaction, User
from app.models.imports import ImportRow
from app.schemas.loan import LoanPaymentCreate
from app.services.loans.payments import record_payment

DUE_WINDOW = timedelta(days=7)


def _matches_lender(loan: Loan, tx: Transaction) -> bool:
    by_iban = bool(loan.lender_iban) and tx.counterparty_iban == loan.lender_iban
    by_reference = bool(loan.payment_reference) and (
        loan.payment_reference.casefold() in tx.description.casefold()
    )
    return by_iban or by_reference


def _next_open_id(session: Session, loan: Loan) -> int | None:
    return session.exec(
        select(LoanScheduleEntry.id)
        .where(LoanScheduleEntry.loan_id == loan.id, LoanScheduleEntry.status == ScheduleStatus.PLANNED)
        .order_by(LoanScheduleEntry.seq)
    ).first()


def candidates(session: Session, user: User, tx: Transaction) -> list[tuple[Loan, LoanScheduleEntry]]:
    if tx.amount >= 0:
        return []
    loans = session.exec(
        select(Loan).where(
            Loan.user_id == user.id,
            Loan.status == LoanStatus.ACTIVE,
            Loan.payment_account_id == tx.account_id,
        )
    )
    found = []
    for loan in loans:
        if not _matches_lender(loan, tx):
            continue
        entries = session.exec(
            select(LoanScheduleEntry).where(
                LoanScheduleEntry.loan_id == loan.id,
                LoanScheduleEntry.status == ScheduleStatus.PLANNED,
                LoanScheduleEntry.id == _next_open_id(session, loan),  # nur die nächste offene Rate
                LoanScheduleEntry.due_date.between(tx.booking_date - DUE_WINDOW, tx.booking_date + DUE_WINDOW),
            )
        )
        found.extend((loan, entry) for entry in entries)
    return found


def match_imported_payment(session: Session, user: User, row: ImportRow, tx: Transaction) -> bool:
    """Bucht eine eindeutige Rate automatisch; gibt True zurück, wenn gebucht wurde."""
    found = candidates(session, user, tx)
    if not found:
        return False
    paid = -tx.amount
    if len(found) == 1 and found[0][1].planned_installment == paid:
        loan, entry = found[0]
        try:
            with session.begin_nested():
                record_payment(session, user, loan, LoanPaymentCreate(transaction_id=tx.id, schedule_seq=entry.seq))
            return True
        except AppError:
            pass  # z. B. nicht die nächste offene Rate – dann nur als Vorschlag

    best = min(
        found,
        key=lambda c: (c[1].planned_installment != paid, abs((c[1].due_date - tx.booking_date).days), c[1].id),
    )
    row.suggested_loan_entry_id = best[1].id
    return False
