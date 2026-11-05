"""Kredite anlegen, ändern, löschen und den Tilgungsplan aktuell halten."""

from datetime import date
from decimal import Decimal

from sqlalchemy import delete
from sqlmodel import Session, func, select

from app import clock
from app.errors import Conflict, Invalid, NotFound
from app.models import (
    Account,
    AccountType,
    CategorySource,
    Institution,
    ReviewStatus,
    Transaction,
    TransactionKind,
    TransactionSource,
    User,
)
from app.models.loan import Loan, LoanPayment, LoanScheduleEntry, LoanStatus, LoanType, ScheduleStatus
from app.schemas.loan import LoanCreate
from app.services.accounts import _UNIQUE as ACCOUNT_UNIQUE
from app.services.balances import balances
from app.services.common import flush_or_conflict, get_owned
from app.services.iban import normalize_iban
from app.services.loans.schedule import (
    PlannedInstallment,
    ScheduleError,
    add_months,
    build_plan,
    check_term_matches,
    installments_for_term,
)
from app.services.transactions import bookable_account

FAR_FUTURE = date(9999, 12, 31)


def plan_or_invalid(func_, *args, **kwargs):
    try:
        return func_(*args, **kwargs)
    except ScheduleError as exc:
        raise Invalid(str(exc), code=exc.code, details=exc.details) from exc


# --- Lesen --------------------------------------------------------------------


def get_loan(session: Session, user: User, loan_id: int) -> Loan:
    return get_owned(session, Loan, loan_id, user.id, "Kredit")


def lock_loan(session: Session, loan: Loan) -> Loan:
    """Sperrt den Kredit bis zum Ende der Transaktion und lädt ihn frisch.

    Gemeinsame Konvention für alle ändernden Kreditoperationen (Zahlung, Storno, Belastung,
    Konditionen, Ratenpause): Wer Status, Plan oder Restschuld liest und daraufhin bucht, hält
    vorher diese Sperre – sonst könnten zwei parallele Zahlungen dieselbe Restschuld tilgen.
    """
    session.execute(select(Loan.id).where(Loan.id == loan.id).with_for_update())
    session.refresh(loan)
    return loan


def list_loans(session: Session, user: User) -> list[Loan]:
    return list(session.exec(select(Loan).where(Loan.user_id == user.id).order_by(Loan.id)))


def remaining_debt(session: Session, loan: Loan, as_of: date = FAR_FUTURE) -> Decimal | None:
    """Restschuld = −Saldo des Kreditkontos (None vor dem Stichtag)."""
    balance = balances(session, loan.user_id, as_of, [loan.account_id])[loan.account_id]
    return None if balance is None else -balance


def open_entries(session: Session, loan: Loan) -> list[LoanScheduleEntry]:
    return list(
        session.exec(
            select(LoanScheduleEntry)
            .where(LoanScheduleEntry.loan_id == loan.id, LoanScheduleEntry.status == ScheduleStatus.PLANNED)
            .order_by(LoanScheduleEntry.seq)
        )
    )


def schedule(session: Session, loan: Loan) -> list[LoanScheduleEntry]:
    return list(
        session.exec(
            select(LoanScheduleEntry)
            .where(LoanScheduleEntry.loan_id == loan.id)
            .order_by(LoanScheduleEntry.seq)
        )
    )


def loan_view(session: Session, loan: Loan, today: date | None = None) -> dict:
    """Konditionen plus berechnete Kennzahlen für die API."""
    today = today or clock.today()
    account = session.get(Account, loan.account_id)
    entries = open_entries(session, loan)
    data = loan.model_dump()
    data.update(
        name=account.name,
        institution_id=account.institution_id,
        remaining_debt=remaining_debt(session, loan),
        principal_repaid=session.exec(
            select(func.coalesce(func.sum(LoanPayment.principal), 0)).where(LoanPayment.loan_id == loan.id)
        ).one(),
        next_due_date=entries[0].due_date if entries else None,
        next_installment=entries[0].planned_installment if entries else None,
        open_installments=len(entries),
        overdue_installments=sum(1 for e in entries if e.due_date < today),
    )
    return data


# --- Tilgungsplan ---------------------------------------------------------------


def _plan_basis(loan: Loan) -> tuple[Decimal | None, Decimal | None]:
    if loan.loan_type == LoanType.INSTALLMENT:
        return None, loan.fixed_principal
    return loan.installment_amount, None  # Annuität bzw. Privatkredit mit vereinbarter Rate


def _derive_basis(
    loan_type: str,
    remaining: Decimal,
    rate: Decimal,
    *,
    installment: Decimal | None,
    fixed_principal: Decimal | None,
    term: int | None,
) -> tuple[Decimal | None, Decimal | None, bool]:
    """Prüft die Angaben je Kreditart und leitet Rate bzw. Tilgung aus der Laufzeit ab.

    Dritter Wert: True, wenn Rate/Tilgung aus der Laufzeit abgeleitet wurde (dann passt
    der Plan per Konstruktion genau zur Laufzeit).
    """
    if loan_type == LoanType.INSTALLMENT:
        if installment is not None:
            raise Invalid(
                "Beim Tilgungsdarlehen die feste Tilgung (fixed_principal) angeben, nicht die Rate",
                code="invalid_plan_basis",
            )
        if fixed_principal is None and term is None:
            raise Invalid("Feste Tilgung oder Laufzeit angeben", code="invalid_plan_basis")
        if fixed_principal is None:
            _, derived = plan_or_invalid(installments_for_term, remaining, rate, term, annuity=False)
            return None, derived, True
        return None, fixed_principal, False

    if fixed_principal is not None:
        raise Invalid(
            "Feste Tilgung gibt es nur beim Tilgungsdarlehen (loan_type=installment)",
            code="invalid_plan_basis",
        )
    if installment is None and term is not None:
        derived, _ = plan_or_invalid(installments_for_term, remaining, rate, term, annuity=True)
        return derived, None, True
    if installment is None and loan_type == LoanType.ANNUITY:
        raise Invalid("Rate oder Laufzeit angeben", code="invalid_plan_basis")
    return installment, None, False


def _check_user_terms(loan: Loan, plan: list[PlannedInstallment], term: int | None, derived: bool) -> None:
    """Hat der Nutzer Rate/Tilgung UND Laufzeit angegeben, müssen sie zusammenpassen."""
    if term is not None and not derived and plan:
        plan_or_invalid(check_term_matches, plan, term, loan.installment_amount)


def _make_plan(
    loan: Loan, remaining: Decimal, first_due: date, start_seq: int, final_due: date | None
) -> list[PlannedInstallment]:
    installment, fixed_principal = _plan_basis(loan)
    if installment is None and fixed_principal is None:
        return []  # Privatkredit ohne vereinbarte Rate: kein Plan
    return plan_or_invalid(
        build_plan,
        remaining=remaining,
        annual_percent=loan.annual_interest_rate,
        first_due=first_due,
        payment_day=loan.payment_day,
        installment=installment,
        fixed_principal=fixed_principal,
        extra=loan.extra_amount,
        start_seq=start_seq,
        final_due=final_due,
    )


def _next_due(session: Session, loan: Loan) -> tuple[date, int]:
    """Fälligkeit und Nummer der nächsten noch nicht erledigten Rate."""
    last_done = session.exec(
        select(LoanScheduleEntry)
        .where(LoanScheduleEntry.loan_id == loan.id, LoanScheduleEntry.status != ScheduleStatus.PLANNED)
        .order_by(LoanScheduleEntry.seq.desc())
    ).first()
    if last_done is None:
        return loan.first_due_date, 1
    return add_months(last_done.due_date, 1, loan.payment_day), last_done.seq + 1


def _remaining_months(session: Session, loan: Loan) -> int:
    """Raten von der nächsten Fälligkeit bis zum vereinbarten Laufzeitende (einschließlich)."""
    next_due, _ = _next_due(session, loan)
    end = loan.final_due_date
    return max((end.year - next_due.year) * 12 + end.month - next_due.month + 1, 1)


def rebuild_schedule(
    session: Session, loan: Loan, *, new_terms: bool = False, term: int | None = None
) -> list[PlannedInstallment]:
    """Ersetzt alle offenen Raten durch einen neuen Plan ab der tatsächlichen Restschuld.

    Bezahlte und ausgesetzte Raten bleiben als Historie erhalten. Bei vereinbarter Laufzeit
    ist die Rate am Laufzeitende die Schlussrate (nie mehr Raten als vereinbart); bei neuen
    Konditionen (`new_terms`) ergibt sich das Laufzeitende aus der (Rest-)Laufzeit `term`.
    Ohne Laufzeit läuft der Plan mit fester Rate bis zur Tilgung.
    """
    session.execute(
        delete(LoanScheduleEntry).where(
            LoanScheduleEntry.loan_id == loan.id, LoanScheduleEntry.status == ScheduleStatus.PLANNED
        )
    )
    session.flush()
    remaining = remaining_debt(session, loan)
    if remaining is None or remaining <= 0:
        loan.status = LoanStatus.PAID_OFF
        session.flush()
        return
    loan.status = LoanStatus.ACTIVE

    first_due, start_seq = _next_due(session, loan)
    if loan.term_months is None:
        final_due = None
    elif new_terms and term:
        final_due = add_months(first_due, term - 1, loan.payment_day)
    else:
        final_due = loan.final_due_date
    plan = _make_plan(loan, remaining, first_due, start_seq, final_due)
    if new_terms or loan.term_months is None:
        loan.final_due_date = plan[-1].due_date if plan else None
    for item in plan:
        session.add(
            LoanScheduleEntry(
                loan_id=loan.id,
                seq=item.seq,
                due_date=item.due_date,
                planned_interest=item.interest,
                planned_principal=item.principal,
                planned_extra=item.extra,
                planned_remaining_after=item.remaining_after,
            )
        )
    session.flush()
    return plan


# --- Anlegen / Ändern / Löschen -----------------------------------------------


def _payment_account(session: Session, user: User, account_id: int | None) -> int | None:
    if account_id is None:
        return None
    account = get_owned(session, Account, account_id, user.id, "Zahlkonto")
    if account.type == AccountType.LOAN:
        raise Invalid("Zahlkonto darf kein Kreditkonto sein", code="invalid_payment_account")
    return account.id


def _loan_transaction(
    user: User, account_id: int, booking_date: date, amount: Decimal, description: str, **extra
) -> Transaction:
    return Transaction(
        user_id=user.id,
        account_id=account_id,
        booking_date=booking_date,
        amount=amount,
        description=description,
        review_status=ReviewStatus.CONFIRMED,
        category_source=CategorySource.LOAN,
        source=TransactionSource.LOAN,
        **extra,
    )


def create_loan(session: Session, user: User, data: LoanCreate) -> Loan:
    if data.institution_id is not None:
        get_owned(session, Institution, data.institution_id, user.id, "Bank")
    payment_account_id = _payment_account(session, user, data.payment_account_id)
    if data.disbursement_account_id is not None:
        disbursement = bookable_account(session, user, data.disbursement_account_id, data.balance_date)

    payment_day = data.payment_day or (data.first_due_date or data.balance_date).day
    first_due = data.first_due_date or add_months(data.balance_date, 1, payment_day)
    if first_due < data.balance_date:
        raise Invalid("Erste Fälligkeit liegt vor dem Stichtag", code="first_due_before_balance_date")

    installment, fixed_principal, derived = _derive_basis(
        data.loan_type,
        data.current_balance,
        data.annual_interest_rate,
        installment=data.installment_amount,
        fixed_principal=data.fixed_principal,
        term=data.term_months,
    )
    loan = Loan(
        user_id=user.id,
        account_id=0,  # wird nach dem Anlegen des Kontos gesetzt
        loan_type=data.loan_type,
        lender_name=data.lender_name,
        lender_iban=normalize_iban(data.lender_iban) if data.lender_iban else None,
        payment_reference=data.payment_reference,
        payment_account_id=payment_account_id,
        principal_original=data.principal_original,
        annual_interest_rate=data.annual_interest_rate,
        start_date=data.start_date,
        first_due_date=first_due,
        payment_day=payment_day,
        term_months=data.term_months,
        installment_amount=installment,
        fixed_principal=fixed_principal,
        extra_amount=data.extra_amount,
        fixed_rate_until=data.fixed_rate_until,
    )
    account = Account(
        user_id=user.id,
        institution_id=data.institution_id,
        name=data.name,
        type=AccountType.LOAN,
        opening_balance=Decimal("0.00") if data.disbursement_account_id else -data.current_balance,
        opening_balance_date=data.balance_date,
        bank_account_ref=data.bank_account_ref,
    )
    session.add(account)
    flush_or_conflict(session, ACCOUNT_UNIQUE)
    loan.account_id = account.id
    session.add(loan)
    session.flush()

    if data.disbursement_account_id is not None:
        payout = _loan_transaction(
            user, account.id, data.balance_date, -data.current_balance,
            f"Auszahlung {data.lender_name}", kind=TransactionKind.TRANSFER,
            counterparty=disbursement.name,
        )
        received = _loan_transaction(
            user, disbursement.id, data.balance_date, data.current_balance,
            f"Kreditauszahlung {data.lender_name}", kind=TransactionKind.TRANSFER,
            counterparty=data.lender_name,
        )
        session.add_all([payout, received])
        session.flush()
        payout.transfer_peer_id, received.transfer_peer_id = received.id, payout.id
        session.flush()

    plan = rebuild_schedule(session, loan, new_terms=True, term=data.term_months)
    _check_user_terms(loan, plan, data.term_months, derived)
    return loan


_PLAN_FIELDS = {"annual_interest_rate", "payment_day", "term_months", "installment_amount",
                "fixed_principal", "extra_amount"}


def update_loan(session: Session, user: User, loan: Loan, changes: dict) -> Loan:
    lock_loan(session, loan)
    # Unveränderte Werte zählen nicht als Änderung: Ein Formular, das beim Umbenennen die
    # gespeicherte Laufzeit oder Rate mitschickt, darf den Plan nicht neu berechnen lassen
    if changes.get("lender_iban"):
        changes["lender_iban"] = normalize_iban(changes["lender_iban"])
    if changes.get("name") == session.get(Account, loan.account_id).name:
        changes.pop("name")
    changes = {k: v for k, v in changes.items() if k == "name" or getattr(loan, k) != v}
    if "name" in changes:
        session.get(Account, loan.account_id).name = changes.pop("name")
        flush_or_conflict(session, ACCOUNT_UNIQUE)
    if "payment_account_id" in changes:
        changes["payment_account_id"] = _payment_account(session, user, changes["payment_account_id"])

    plan_changed = bool(_PLAN_FIELDS & changes.keys())
    term, derived = None, True
    if plan_changed:
        explicit_rate = "installment_amount" in changes or "fixed_principal" in changes
        term = changes.get("term_months")
        if "term_months" not in changes and loan.term_months is not None:
            if explicit_rate:
                changes["term_months"] = None  # neue feste Rate: die Laufzeit ergibt sich daraus
            else:
                # Vereinbarte Laufzeit bleibt (z. B. neuer Zins): Rate für die Restlaufzeit neu
                term = changes["term_months"] = _remaining_months(session, loan)
        if term is not None:
            # (Rest-)Laufzeit: Rate bzw. Tilgung aus der aktuellen Restschuld ableiten,
            # sofern sie nicht ausdrücklich mitgegeben wird
            installment = changes.get("installment_amount")
            fixed_principal = changes.get("fixed_principal")
        else:
            installment = changes.get("installment_amount", loan.installment_amount)
            fixed_principal = changes.get("fixed_principal", loan.fixed_principal)
        remaining = remaining_debt(session, loan) or Decimal("0")
        if remaining > 0:
            installment, fixed_principal, derived = _derive_basis(
                loan.loan_type,
                remaining,
                changes.get("annual_interest_rate", loan.annual_interest_rate),
                installment=installment,
                fixed_principal=fixed_principal,
                term=term,
            )
        changes["installment_amount"], changes["fixed_principal"] = installment, fixed_principal

    for key, value in changes.items():
        setattr(loan, key, value)
    session.flush()
    if plan_changed:
        plan = rebuild_schedule(session, loan, new_terms=True, term=term)
        _check_user_terms(loan, plan, term, derived)
    return loan


def delete_loan(session: Session, loan: Loan) -> None:
    """Nur ohne gebuchte Raten/Belastungen; die Auszahlungsbuchung wird mit entfernt."""
    lock_loan(session, loan)
    payments = session.exec(select(func.count()).where(LoanPayment.loan_id == loan.id)).one()
    if payments:
        raise Conflict(
            "Kredit hat gebuchte Raten – erst stornieren oder Kreditkonto archivieren",
            code="loan_in_use",
            details={"payments": payments},
        )
    loan_txs = list(session.exec(select(Transaction).where(Transaction.account_id == loan.account_id)))
    if any(tx.kind != TransactionKind.TRANSFER for tx in loan_txs):
        raise Conflict("Kredit hat gebuchte Belastungen – erst stornieren", code="loan_in_use")
    for tx in loan_txs:
        if tx.transfer_peer_id:
            peer = session.get(Transaction, tx.transfer_peer_id)
            if peer is not None and peer.source == TransactionSource.LOAN:
                session.delete(peer)
        session.delete(tx)
    session.flush()
    account = session.get(Account, loan.account_id)
    session.delete(loan)
    session.flush()
    session.delete(account)
    session.flush()


def get_entry(session: Session, loan: Loan, seq: int) -> LoanScheduleEntry:
    entry = session.exec(
        select(LoanScheduleEntry).where(LoanScheduleEntry.loan_id == loan.id, LoanScheduleEntry.seq == seq)
    ).first()
    if entry is None:
        raise NotFound(f"Rate {seq} nicht gefunden")
    return entry


def skip_installment(session: Session, loan: Loan, seq: int) -> None:
    """Vereinbarte Ratenpause für die nächste offene Rate; der Plan verschiebt sich um einen Monat."""
    lock_loan(session, loan)
    entry = get_entry(session, loan, seq)
    entries = open_entries(session, loan)
    if entry.status != ScheduleStatus.PLANNED or entry.id != entries[0].id:
        raise Conflict("Nur die nächste offene Rate kann ausgesetzt werden", code="skip_not_next")
    entry.status = ScheduleStatus.SKIPPED
    if loan.term_months is not None and loan.final_due_date:
        loan.final_due_date = add_months(loan.final_due_date, 1, loan.payment_day)  # Laufzeit + 1 Monat
    session.flush()
    rebuild_schedule(session, loan)


def unskip_installment(session: Session, loan: Loan, seq: int) -> None:
    lock_loan(session, loan)
    entry = get_entry(session, loan, seq)
    latest = session.exec(
        select(LoanScheduleEntry)
        .where(LoanScheduleEntry.loan_id == loan.id, LoanScheduleEntry.status != ScheduleStatus.PLANNED)
        .order_by(LoanScheduleEntry.seq.desc())
    ).first()
    if entry.status != ScheduleStatus.SKIPPED or latest is None or latest.id != entry.id:
        raise Conflict("Nur die zuletzt ausgesetzte Rate kann zurückgenommen werden", code="unskip_not_latest")
    entry.status = ScheduleStatus.PLANNED
    if loan.term_months is not None and loan.final_due_date:
        loan.final_due_date = add_months(loan.final_due_date, -1, loan.payment_day)
    session.flush()
    rebuild_schedule(session, loan)
