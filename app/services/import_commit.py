"""Übernahme geklärter Importzeilen als Buchungen – in einer Datenbanktransaktion."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import Session, func, select

from app.errors import Conflict, Invalid
from app.importers.base import looks_like_iban
from app.models import (
    Account,
    CategorySource,
    ReviewStatus,
    Transaction,
    TransactionKind,
    TransactionSource,
    User,
)
from app.models.imports import (
    BatchStatus,
    ImportBatch,
    ImportProfile,
    ImportRow,
    MatchKind,
    RowDecision,
    RowResolution,
    TransactionImportLink,
)

OPEN_DECISIONS = (RowDecision.AMBIGUOUS, RowDecision.BEFORE_OPENING)


def namespace_for(session: Session, batch: ImportBatch) -> str:
    return session.get(ImportProfile, batch.import_profile_id).format


def effective_action(row: ImportRow) -> str | None:
    """Was mit der Zeile passiert; None = Entscheidung des Nutzers steht noch aus."""
    if row.resolution:
        return row.resolution
    return {
        RowDecision.NEW: RowResolution.IMPORT,
        RowDecision.DUPLICATE: RowResolution.DUPLICATE,
        RowDecision.SKIPPED: RowResolution.SKIP,
    }.get(row.decision)


def open_row_count(session: Session, batch_id: int) -> int:
    return session.exec(
        select(func.count()).where(
            ImportRow.batch_id == batch_id,
            ImportRow.resolution.is_(None),
            ImportRow.decision.in_(OPEN_DECISIONS),
        )
    ).one()


def _external_link(session: Session, account_id: int, namespace: str, external_id: str):
    return session.exec(
        select(TransactionImportLink).where(
            TransactionImportLink.account_id == account_id,
            TransactionImportLink.id_namespace == namespace,
            TransactionImportLink.external_id == external_id,
        )
    ).first()


def _link(session: Session, row: ImportRow, tx_id: int, namespace: str) -> None:
    """Importidentität festhalten; eine schon vergebene Bank-ID wird nicht doppelt belegt."""
    external_id = row.external_id
    if external_id and _external_link(session, row.account_id, namespace, external_id):
        external_id = None
    if external_id is None:
        exists = session.exec(
            select(TransactionImportLink.id).where(
                TransactionImportLink.transaction_id == tx_id,
                TransactionImportLink.fingerprint == row.fingerprint,
            )
        ).first()
        if exists:
            return
    session.add(
        TransactionImportLink(
            transaction_id=tx_id,
            import_row_id=row.id,
            account_id=row.account_id,
            id_namespace=namespace,
            external_id=external_id,
            fingerprint=row.fingerprint,
        )
    )


@dataclass
class CommitResult:
    created: list[tuple[ImportRow, Transaction]] = field(default_factory=list)
    new_conflicts: list[int] = field(default_factory=list)


def _recheck(session: Session, batch: ImportBatch, rows: list[ImportRow], namespace: str) -> list[int]:
    """Zeilen, die seit der Prüfung ein anderer Import übernommen hat.

    Geprüft werden Bank-ID und – für Zeilen ohne Bank-ID – der Fingerprint. Neue Zeilen
    hatten bei der Prüfung keinen Treffer; ein Treffer aus einem anderen Auftrag heißt also,
    dass dieselbe Datei (z. B. einmal mit, einmal ohne Kontoauswahl) parallel verarbeitet wurde.
    """
    conflicts = []
    for row in rows:
        if effective_action(row) != RowResolution.IMPORT or row.resolution or row.created_transaction_id:
            continue
        if row.external_id:
            link = _external_link(session, row.account_id, namespace, row.external_id)
        else:
            link = session.exec(
                select(TransactionImportLink)
                .outerjoin(ImportRow, ImportRow.id == TransactionImportLink.import_row_id)
                .where(
                    TransactionImportLink.account_id == row.account_id,
                    TransactionImportLink.fingerprint == row.fingerprint,
                    ImportRow.batch_id.is_distinct_from(batch.id),
                )
            ).first()
        if link is not None:
            row.decision = RowDecision.AMBIGUOUS
            row.match_kind = MatchKind.EXTERNAL_ID if row.external_id else MatchKind.FINGERPRINT
            row.matched_transaction_id = link.transaction_id
            row.note = "Inzwischen durch einen anderen Import übernommen"
            conflicts.append(row.row_no)
    return conflicts


def commit_batch(session: Session, user: User, batch: ImportBatch) -> CommitResult:
    if open_row_count(session, batch.id):
        raise Conflict("Es gibt noch ungeklärte Zeilen", code="import_rows_open")
    namespace = namespace_for(session, batch)
    rows = list(session.exec(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.row_no)))

    result = CommitResult(new_conflicts=_recheck(session, batch, rows, namespace))
    if result.new_conflicts:
        batch.status = BatchStatus.AWAITING_REVIEW
        batch.rows_review = open_row_count(session, batch.id)
        session.flush()
        return result

    accounts: dict[int, Account] = {}
    for row in rows:
        action = effective_action(row)
        if action == RowResolution.IMPORT:
            if row.created_transaction_id is not None:
                continue  # schon übernommen – nie doppelt buchen
            account = accounts.setdefault(row.account_id, session.get(Account, row.account_id))
            if row.booking_date < account.opening_balance_date:
                raise Invalid(
                    f"Zeile {row.row_no} liegt vor dem Stichtag von „{account.name}“ – "
                    "Stichtag anpassen oder Zeile überspringen",
                    code="before_opening",
                )
            tx = Transaction(
                user_id=user.id,
                account_id=row.account_id,
                booking_date=row.booking_date,
                value_date=row.value_date,
                amount=row.amount,
                description=row.description,
                counterparty=(row.counterparty or "")[:200] or None,
                counterparty_iban=row.counterparty_iban if looks_like_iban(row.counterparty_iban) else None,
                kind=TransactionKind.REGULAR,
                review_status=ReviewStatus.NEEDS_REVIEW,
                category_source=CategorySource.NONE,
                source=TransactionSource.IMPORT,
            )
            session.add(tx)
            session.flush()
            row.created_transaction_id = tx.id
            _link(session, row, tx.id, namespace)
            result.created.append((row, tx))
        elif action == RowResolution.DUPLICATE:
            if row.matched_transaction_id is None:
                raise Invalid(f"Zeile {row.row_no}: Dublette ohne zugeordnete Buchung", code="duplicate_without_match")
            _link(session, row, row.matched_transaction_id, namespace)

    batch.rows_new = sum(1 for r in rows if effective_action(r) == RowResolution.IMPORT)
    batch.rows_duplicate = sum(1 for r in rows if effective_action(r) == RowResolution.DUPLICATE)
    batch.rows_skipped = sum(1 for r in rows if effective_action(r) == RowResolution.SKIP)
    batch.rows_review = 0
    batch.status = BatchStatus.DONE
    batch.finished_at = datetime.now(UTC)
    session.flush()
    return result
