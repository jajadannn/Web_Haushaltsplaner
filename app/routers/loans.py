from typing import Annotated

from fastapi import APIRouter, Query, Response

from app import clock
from app.deps import CurrentUser, SessionDep
from app.schemas.loan import (
    LoanChargeCreate,
    LoanCreate,
    LoanPaymentCreate,
    LoanPaymentRead,
    LoanRead,
    LoanUpdate,
    LoanYearSummary,
    ScheduleEntryRead,
    UpcomingInstallment,
)
from app.schemas.transaction import TransactionRead
from app.services.loans import core, payments

router = APIRouter(prefix="/loans", tags=["Kredite"])


def _payment_read(payment, seq: int | None) -> LoanPaymentRead:
    return LoanPaymentRead.model_validate(payment).model_copy(update={"schedule_seq": seq})


@router.get("", response_model=list[LoanRead])
def list_loans(session: SessionDep, user: CurrentUser):
    """Alle Kredite mit Restschuld, nächster Rate und Anzahl offener/überfälliger Raten."""
    return [core.loan_view(session, loan) for loan in core.list_loans(session, user)]


@router.get("/upcoming", response_model=list[UpcomingInstallment])
def upcoming_installments(
    session: SessionDep, user: CurrentUser, days: Annotated[int, Query(ge=0, le=366)] = 30
):
    """Fällige und überfällige Raten aller Kredite in den nächsten `days` Tagen."""
    return payments.upcoming(session, user, days)


@router.post("", response_model=LoanRead, status_code=201)
def create_loan(data: LoanCreate, session: SessionDep, user: CurrentUser):
    """Kredit anlegen: Kreditkonto (Saldo = −Restschuld), Konditionen und Tilgungsplan."""
    loan = core.create_loan(session, user, data)
    session.commit()
    return core.loan_view(session, loan)


@router.get("/{loan_id}", response_model=LoanRead)
def get_loan(loan_id: int, session: SessionDep, user: CurrentUser):
    return core.loan_view(session, core.get_loan(session, user, loan_id))


@router.patch("/{loan_id}", response_model=LoanRead)
def update_loan(loan_id: int, data: LoanUpdate, session: SessionDep, user: CurrentUser):
    """Geänderte Konditionen (z. B. neuer Zins nach Zinsbindung) gelten für alle offenen
    Raten; `term_months` ist dann die neue Restlaufzeit ab der nächsten Rate."""
    loan = core.get_loan(session, user, loan_id)
    core.update_loan(session, user, loan, data.changes())
    session.commit()
    return core.loan_view(session, loan)


@router.delete("/{loan_id}", status_code=204)
def delete_loan(loan_id: int, session: SessionDep, user: CurrentUser):
    """Nur ohne gebuchte Raten/Belastungen (sonst 409); entfernt auch das Kreditkonto."""
    core.delete_loan(session, core.get_loan(session, user, loan_id))
    session.commit()
    return Response(status_code=204)


@router.get("/{loan_id}/schedule", response_model=list[ScheduleEntryRead])
def get_schedule(loan_id: int, session: SessionDep, user: CurrentUser):
    """Tilgungsplan: bezahlte, ausgesetzte und offene Raten (`overdue` = fällig, nicht bezahlt)."""
    loan = core.get_loan(session, user, loan_id)
    today = clock.today()
    return [
        ScheduleEntryRead.model_validate(entry).model_copy(
            update={"overdue": entry.status == "planned" and entry.due_date < today}
        )
        for entry in core.schedule(session, loan)
    ]


@router.post("/{loan_id}/schedule/{seq}/skip", response_model=list[ScheduleEntryRead])
def skip_installment(loan_id: int, seq: int, session: SessionDep, user: CurrentUser):
    """Vereinbarte Ratenpause für die nächste offene Rate; die Laufzeit verlängert sich."""
    loan = core.get_loan(session, user, loan_id)
    core.skip_installment(session, loan, seq)
    session.commit()
    return get_schedule(loan_id, session, user)


@router.post("/{loan_id}/schedule/{seq}/unskip", response_model=list[ScheduleEntryRead])
def unskip_installment(loan_id: int, seq: int, session: SessionDep, user: CurrentUser):
    loan = core.get_loan(session, user, loan_id)
    core.unskip_installment(session, loan, seq)
    session.commit()
    return get_schedule(loan_id, session, user)


@router.get("/{loan_id}/payments", response_model=list[LoanPaymentRead])
def list_payments(loan_id: int, session: SessionDep, user: CurrentUser):
    loan = core.get_loan(session, user, loan_id)
    return [_payment_read(p, seq) for p, seq in payments.list_payments(session, loan)]


@router.post("/{loan_id}/payments", response_model=LoanPaymentRead, status_code=201)
def record_payment(loan_id: int, data: LoanPaymentCreate, session: SessionDep, user: CurrentUser):
    """Rate buchen: Zahlung wird in Tilgung (Umbuchung), Zinsen und Gebühren aufgeteilt;
    der Plan wird danach ab der tatsächlichen Restschuld neu berechnet."""
    loan = core.get_loan(session, user, loan_id)
    payment = payments.record_payment(session, user, loan, data)
    session.commit()
    seq = next((s for p, s in payments.list_payments(session, loan) if p.id == payment.id), None)
    return _payment_read(payment, seq)


@router.delete("/{loan_id}/payments/{payment_id}", status_code=204)
def delete_payment(loan_id: int, payment_id: int, session: SessionDep, user: CurrentUser):
    """Storniert die zuletzt gebuchte Rate."""
    payments.delete_payment(session, core.get_loan(session, user, loan_id), payment_id)
    session.commit()
    return Response(status_code=204)


@router.post("/{loan_id}/charges", response_model=TransactionRead, status_code=201)
def add_charge(loan_id: int, data: LoanChargeCreate, session: SessionDep, user: CurrentUser):
    """Zinsen/Gebühren direkt auf dem Kreditkonto (erhöhen die Restschuld)."""
    tx = payments.add_charge(session, user, core.get_loan(session, user, loan_id), data)
    session.commit()
    return tx


@router.delete("/{loan_id}/charges/{transaction_id}", status_code=204)
def delete_charge(loan_id: int, transaction_id: int, session: SessionDep, user: CurrentUser):
    payments.delete_charge(session, core.get_loan(session, user, loan_id), transaction_id)
    session.commit()
    return Response(status_code=204)


@router.get("/{loan_id}/summary", response_model=LoanYearSummary)
def year_summary(
    loan_id: int, session: SessionDep, user: CurrentUser, year: Annotated[int, Query(ge=1900, le=2200)]
):
    """Gezahlte Zinsen, Tilgung und Gebühren eines Jahres sowie Restschuld zum Jahresende."""
    return payments.year_summary(session, user, core.get_loan(session, user, loan_id), year)
