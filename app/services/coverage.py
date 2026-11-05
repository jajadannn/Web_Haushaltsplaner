"""Importabdeckung: für welche Zeiträume liegen die Bankbuchungen eines Kontos vollständig vor?

Grundlage sind die Buchungstage der abgeschlossenen Importe je Konto (`import_row`). Zeiträume, die
höchstens `GAP_DAYS` auseinanderliegen (Wochenende), werden zusammengefasst. Ein Hinweis „Zahlung
fehlt“ ist nur innerhalb abgedeckter Zeiträume zulässig – das Datum der letzten Buchung allein
beweist keine vollständige Abdeckung.
"""

from datetime import date, timedelta

from sqlmodel import Session, func, select

from app.models import ImportBatch, ImportRow
from app.models.imports import BatchStatus

GAP_DAYS = 3


def covered_ranges(session: Session, account_id: int) -> list[tuple[date, date]]:
    rows = session.exec(
        select(func.min(ImportRow.booking_date), func.max(ImportRow.booking_date))
        .join(ImportBatch, ImportBatch.id == ImportRow.batch_id)
        .where(ImportRow.account_id == account_id, ImportBatch.status == BatchStatus.DONE)
        .group_by(ImportRow.batch_id)
    ).all()
    merged: list[tuple[date, date]] = []
    for start, end in sorted(rows):
        if merged and start <= merged[-1][1] + timedelta(days=GAP_DAYS):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def has_imports(session: Session, account_id: int) -> bool:
    return bool(covered_ranges(session, account_id))


def is_covered(session: Session, account_id: int, day: date) -> bool:
    return covers(session, account_id, day, day)


def covers(session: Session, account_id: int, start: date, end: date) -> bool:
    """Liegt [start, end] vollständig in einem importierten Zeitraum?"""
    return any(a <= start and end <= b for a, b in covered_ranges(session, account_id))
