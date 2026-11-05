"""Importaufträge: Datei entgegennehmen, verarbeiten, übernehmen, archivieren.

Upload und Watcher nutzen denselben Ablauf. Jeder Auftrag wird dauerhaft angelegt
(`queued`) und von genau einem Prozess per `FOR UPDATE SKIP LOCKED` übernommen.
Die Arbeitskopie liegt unveränderlich unter `processing/`; Hash und Parser lesen
dieselben Bytes. Das Archivieren ist vom fachlichen Ergebnis getrennt (`archive_state`).
"""

import fcntl
import hashlib
import logging
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select

from app.config import get_settings
from app.errors import Conflict, Invalid, NotFound
from app.importers import PARSER_VERSION, CsvOptions, ParseError, ParseResult, parse_csv, parse_mt940, parse_ofx
from app.importers.base import compact_account, german_account_number, looks_like_iban
from app.models import Account, AccountType, Transaction, User
from app.models.imports import (
    ArchiveState,
    BatchStatus,
    ImportBatch,
    ImportFormat,
    ImportProfile,
    ImportRow,
    RowDecision,
    RowResolution,
    WatchFolder,
)
from app.services.categorization import categorize_new
from app.services.common import get_owned
from app.services.dedup import Classifier
from app.services.import_commit import OPEN_DECISIONS, commit_batch, effective_action, open_row_count
from app.services.loans.matching import match_imported_payment

log = logging.getLogger("finanzplaner.import")


class ImportFailure(Exception):
    """Fachlicher Fehler der Datei (Format, Konto) – Auftrag wird `failed`, nichts gebucht."""

    def __init__(self, message: str, code: str, details=None):
        super().__init__(message)
        self.message, self.code, self.details = message, code, details


# --- Ablage -------------------------------------------------------------------


def import_dir(name: str) -> Path:
    path = get_settings().import_dir / name
    path.mkdir(parents=True, exist_ok=True)
    return path


IMPORT_FOLDERS = ("inbox", "processing", "failed", "archive")


def to_stored(path: Path) -> str:
    """Speicherform eines Dateipfads: relativ zum Importordner, damit ein Restore an einen
    anderen Ort (anderes IMPORT_DIR) die Verweise nicht ungültig macht."""
    root = get_settings().import_dir
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def stored_file(stored: str) -> Path:
    """Tatsächlicher Pfad zu `stored_path` unter dem aktuellen Importordner.

    Ältere Datensätze enthalten absolute Pfade. Existiert die Datei dort nicht mehr (z. B. nach
    einem Restore in ein anderes IMPORT_DIR), wird der Teil ab dem Unterordner
    (inbox/processing/failed/archive) auf den aktuellen Importordner umgelenkt.
    """
    path = Path(stored)
    root = get_settings().import_dir
    if not path.is_absolute():
        return root / path
    if path.exists():
        return path
    parts = path.parts
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] in IMPORT_FOLDERS:
            return root.joinpath(*parts[i:])
    return path


def safe_filename(name: str) -> str:
    base = Path(name or "datei").name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:100] or "datei"


def store_bytes(content: bytes, filename: str) -> Path:
    """Unveränderliche Arbeitskopie unter processing/ (atomar geschrieben)."""
    target = import_dir("processing") / f"{uuid.uuid4().hex}_{safe_filename(filename)}"
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(content)
    os.replace(tmp, target)
    return target


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# --- Aufträge anlegen ----------------------------------------------------------


def validate_target_account(session: Session, user_id: int, profile: ImportProfile, account_id: int) -> Account:
    account = get_owned(session, Account, account_id, user_id, "Konto")
    if account.type == AccountType.LOAN:
        raise Invalid("Kreditkonten werden nicht importiert", code="loan_account_via_loans")
    if account.institution_id not in (None, profile.institution_id):
        raise Invalid("Konto gehört zu einer anderen Bank als das Importprofil", code="institution_mismatch")
    return account


def existing_batch(
    session: Session, user_id: int, profile_id: int, file_hash: str, target_account_id: int | None
) -> ImportBatch | None:
    """Erfolgreicher/laufender Auftrag für dieselbe Datei im selben Zuordnungskontext.

    Das Zielkonto gehört dazu: Dateien ohne Kontokennung können für zwei Konten derselben
    Bank byte-gleich sein und sind trotzdem verschiedene Auszüge.
    """
    return session.exec(
        select(ImportBatch).where(
            ImportBatch.user_id == user_id,
            ImportBatch.import_profile_id == profile_id,
            ImportBatch.file_sha256 == file_hash,
            ImportBatch.target_account_id.is_not_distinct_from(target_account_id),
            ImportBatch.status != BatchStatus.FAILED,
        )
    ).first()


def create_batch(
    session: Session,
    *,
    user_id: int,
    profile: ImportProfile,
    content: bytes,
    original_filename: str,
    source: str,
    account_id: int | None = None,
    stored_path: Path | None = None,
) -> tuple[ImportBatch, bool]:
    """Legt einen Auftrag an; dieselbe Datei liefert den vorhandenen Auftrag (zweiter Wert False)."""
    file_hash = sha256(content)
    found = existing_batch(session, user_id, profile.id, file_hash, account_id)
    if found is not None:
        return found, False
    path = stored_path or store_bytes(content, original_filename)
    batch = ImportBatch(
        user_id=user_id,
        import_profile_id=profile.id,
        account_id=account_id,
        target_account_id=account_id,
        profile_version=profile.version,
        parser_version=PARSER_VERSION,
        original_filename=Path(original_filename).name[:255] or "datei",
        stored_path=to_stored(path),
        file_sha256=file_hash,
        source=source,
    )
    try:
        with session.begin_nested():
            session.add(batch)
    except IntegrityError:
        # Gleichzeitig über einen anderen Weg angelegt (z. B. Upload und Watcher)
        found = existing_batch(session, user_id, profile.id, file_hash, account_id)
        if found is None:
            raise
        if stored_path is None:
            path.unlink(missing_ok=True)
        return found, False
    return batch, True


# --- Verarbeitung --------------------------------------------------------------


def parse(profile: ImportProfile, content: bytes) -> ParseResult:
    if profile.format == ImportFormat.OFX:
        return parse_ofx(content)
    if profile.format == ImportFormat.MT940:
        return parse_mt940(content)
    options = CsvOptions(
        column_map=profile.column_map,
        delimiter=profile.delimiter,
        encoding=profile.encoding,
        skip_rows=profile.skip_rows,
        date_format=profile.date_format,
        decimal_sep=profile.decimal_sep,
        thousands_sep=profile.thousands_sep,
        sign_mode=profile.sign_mode,
        debit_indicators=profile.debit_indicators,
        pending_values=profile.pending_values,
    )
    return parse_csv(content, options)


def _identifies(account: Account, identifier: str) -> bool:
    """Passt die Kontoangabe der Datei zum Konto?

    Neben dem genauen Treffer (IBAN oder Kontokennung) zählt auch die deutsche Kontonummer:
    Manche Banken liefern nur die Kontonummer (OFX), und manches Konto ist nur mit
    Kontonummer statt IBAN angelegt.
    """
    iban, ref = account.iban_normalized, compact_account(account.bank_account_ref)
    if identifier in (iban, ref):
        return True
    number = german_account_number(identifier)
    if number is None:
        return False
    if looks_like_iban(identifier):
        # Volle IBAN in der Datei: Kontonummer nur vergleichen, wenn das Konto keine IBAN hat
        return iban is None and german_account_number(ref) == number
    return number in (german_account_number(iban), german_account_number(ref))


def resolve_accounts(
    session: Session, batch: ImportBatch, profile: ImportProfile, result: ParseResult
) -> list[Account]:
    """Konto je Zeile: Vorgabe aus Upload/Watch-Ordner oder Kontoangabe in der Datei."""
    per_row = [row.own_account or result.statement_account for row in result.rows]
    in_file = sorted({i for i in per_row if i})

    if batch.target_account_id is not None:
        account = session.get(Account, batch.target_account_id)
        foreign = [i for i in in_file if not _identifies(account, i)]
        if foreign:
            raise ImportFailure(
                f"Datei gehört nicht zum gewählten Konto „{account.name}“ (in der Datei: {', '.join(foreign)}) – "
                "Auswahl oder IBAN des Kontos prüfen",
                code="account_mismatch",
                details={"selected_account_id": account.id, "accounts_in_file": foreign},
            )
        targets = [account] * len(result.rows)
    else:
        if not in_file:
            raise ImportFailure(
                "Konto nicht erkennbar – beim Upload bzw. im Watch-Ordner ein Konto festlegen",
                code="account_unknown",
            )
        if any(i is None for i in per_row):
            raise ImportFailure("Zeilen ohne Kontoangabe in einer Datei mit Kontospalte", code="account_unknown")
        accounts = list(session.exec(select(Account).where(Account.user_id == batch.user_id)))
        mapping, unknown = {}, []
        for identifier in in_file:
            # Eine IBAN ist eindeutig; alles andere (Kontonummer) nur bei der Bank des Profils suchen
            match = next((a for a in accounts if a.iban_normalized == identifier), None) or next(
                (a for a in accounts if a.institution_id == profile.institution_id and _identifies(a, identifier)),
                None,
            )
            if match is None:
                unknown.append(identifier)
            else:
                mapping[identifier] = match
        if unknown:
            raise ImportFailure(
                f"Kein passendes Konto bei dieser Bank für {', '.join(unknown)} – "
                "beim Konto die IBAN eintragen oder beim Upload das Konto auswählen",
                code="unknown_accounts",
                details={"accounts": unknown},
            )
        targets = [mapping[i] for i in per_row]

    for account in {a.id: a for a in targets}.values():
        if account.type == AccountType.LOAN:
            raise ImportFailure("Kreditkonten werden nicht importiert", code="loan_account_via_loans")
        if account.institution_id not in (None, profile.institution_id):
            raise ImportFailure(
                f"Konto „{account.name}“ gehört zu einer anderen Bank als das Profil",
                code="institution_mismatch",
            )
        if account.archived_at is not None:
            raise ImportFailure(f"Konto „{account.name}“ ist archiviert", code="account_archived")
    return targets


def process_batch(session: Session, batch: ImportBatch) -> None:
    """Liest die Datei, bewertet jede Zeile und übernimmt sofort, wenn nichts zu klären ist."""
    profile = session.get(ImportProfile, batch.import_profile_id)
    try:
        content = stored_file(batch.stored_path).read_bytes()
    except OSError as exc:
        raise ImportFailure("Arbeitskopie der Datei fehlt", code="file_missing") from exc
    if sha256(content) != batch.file_sha256:
        raise ImportFailure("Arbeitskopie wurde verändert", code="file_changed")
    try:
        result = parse(profile, content)
    except ParseError as exc:
        raise ImportFailure(str(exc), code="parse_error") from exc
    if result.errors:
        raise ImportFailure(
            f"{len(result.errors)} Zeile(n) nicht lesbar – nichts übernommen",
            code="row_errors",
            details=[{"row": e.row_no, "message": e.message} for e in result.errors[:200]],
        )
    targets = resolve_accounts(session, batch, profile, result)

    session.exec(delete(ImportRow).where(ImportRow.batch_id == batch.id))
    classifier = Classifier(session, profile.format)
    for parsed, account in zip(result.rows, targets, strict=True):
        c = classifier.classify(parsed, account)
        session.add(
            ImportRow(
                batch_id=batch.id,
                row_no=parsed.row_no,
                account_id=account.id,
                raw=parsed.raw,
                booking_date=parsed.booking_date,
                value_date=parsed.value_date,
                amount=parsed.amount,
                description=parsed.description,
                counterparty=(parsed.counterparty or "")[:200] or None,
                counterparty_iban=parsed.counterparty_iban,
                external_id=parsed.external_id,
                fingerprint=c.fingerprint,
                decision=c.decision,
                match_kind=c.match_kind,
                note=c.note,
                matched_transaction_id=c.matched_transaction_id,
            )
        )
    session.flush()
    batch.account_id = targets[0].id if len({a.id for a in targets}) == 1 else batch.account_id
    batch.rows_total = len(result.rows)
    batch.rows_pending = result.pending_skipped
    batch.rows_review = open_row_count(session, batch.id)
    batch.errors = []
    if batch.rows_review:
        batch.status = BatchStatus.AWAITING_REVIEW
        session.flush()
    else:
        commit(session, batch)


def commit(session: Session, batch: ImportBatch) -> list[int]:
    """Übernimmt den Auftrag; liefert Zeilennummern neuer Konflikte (dann keine Übernahme)."""
    user = session.get(User, batch.user_id)
    result = commit_batch(session, user, batch)
    if result.new_conflicts:
        return result.new_conflicts
    categorize_new(session, user, [tx for _, tx in result.created])
    # Chronologisch, da nur die jeweils nächste offene Rate gebucht werden kann
    # (viele Bankexporte listen die neuesten Umsätze zuerst)
    for row, tx in sorted(result.created, key=lambda item: (item[1].booking_date, item[0].row_no)):
        match_imported_payment(session, user, row, tx)
    # Auswertungen (Fixkosten, Erstattungen, …) nur vormerken – der Worker führt sie aus
    from app.services.analysis import mark_due

    mark_due(session, user.id)
    session.flush()
    return []


MAX_ATTEMPTS = 3
CLAIM_GRACE = timedelta(minutes=1)


def _mark_failed(batch: ImportBatch, failure: ImportFailure) -> None:
    batch.status = BatchStatus.FAILED
    batch.errors = [{"code": failure.code, "message": failure.message, "details": failure.details}]
    batch.finished_at = datetime.now(UTC)
    batch.rows_review = 0


def _lock(session: Session, batch_id: int, *, skip_locked: bool = False) -> ImportBatch | None:
    return session.exec(
        select(ImportBatch)
        .where(ImportBatch.id == batch_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    ).first()


def run_batch(session: Session, batch_id: int) -> ImportBatch:
    """Verarbeitet einen per `claim_next` übernommenen Auftrag.

    Während der Verarbeitung hält die Transaktion eine Zeilensperre (Lease). Fehler werden
    per Savepoint zurückgerollt und noch unter derselben Sperre als `failed` vermerkt – kein
    anderer Prozess kann den Auftrag dazwischen übernehmen. Bricht der Prozess ganz ab, fällt
    die Sperre weg und `requeue_stale` reiht ihn wieder ein.
    """
    batch = _lock(session, batch_id)
    if batch is None or batch.status != BatchStatus.PROCESSING:
        session.rollback()
        return batch
    try:
        with session.begin_nested():
            process_batch(session, batch)
    except ImportFailure as failure:
        _mark_failed(batch, failure)
    except Exception as exc:
        log.exception("Import %s fehlgeschlagen", batch_id)
        _mark_failed(batch, ImportFailure(f"Interner Fehler: {exc}", code="internal_error"))
    session.commit()
    batch = session.get(ImportBatch, batch_id)
    archive_file(session, batch)
    return batch


def claim_next(session: Session) -> int | None:
    """Übernimmt den nächsten wartenden Auftrag und speichert Status und Versuch sofort.

    Der gespeicherte Versuchszähler überlebt auch einen Absturz mitten in der Verarbeitung.
    """
    batch = session.exec(
        select(ImportBatch)
        .where(ImportBatch.status == BatchStatus.QUEUED)
        .order_by(ImportBatch.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if batch is None:
        session.rollback()
        return None
    now = datetime.now(UTC)
    batch.status = BatchStatus.PROCESSING
    batch.attempt += 1
    batch.started_at = batch.heartbeat_at = now
    session.commit()
    return batch.id


def process_queue(session: Session, limit: int | None = None) -> int:
    processed = 0
    while limit is None or processed < limit:
        batch_id = claim_next(session)
        if batch_id is None:
            break
        run_batch(session, batch_id)
        processed += 1
    return processed


def requeue_stale(session: Session, grace: timedelta = CLAIM_GRACE) -> int:
    """Abgebrochene Verarbeitungen wieder einreihen.

    Abgebrochen ist ein `processing`-Auftrag, dessen Zeilensperre niemand mehr hält (der
    verarbeitende Prozess ist weg) und der älter als die kurze Übernahmefrist ist. Nach
    `MAX_ATTEMPTS` Abbrüchen gilt er als fehlgeschlagen – eine Datei, die den Worker zum
    Absturz bringt, blockiert so nicht dauerhaft alle späteren Importe.
    """
    limit = datetime.now(UTC) - grace
    stale = list(
        session.exec(
            select(ImportBatch)
            .where(
                ImportBatch.status == BatchStatus.PROCESSING,
                or_(ImportBatch.started_at.is_(None), ImportBatch.started_at < limit),
            )
            .with_for_update(skip_locked=True)
        )
    )
    for batch in stale:
        if batch.attempt >= MAX_ATTEMPTS:
            _mark_failed(batch, ImportFailure(
                f"Verarbeitung {batch.attempt}-mal abgebrochen – Datei prüfen", code="processing_aborted"
            ))
        else:
            batch.status = BatchStatus.QUEUED
    session.commit()
    return len(stale)


# --- Archiv -------------------------------------------------------------------


@contextmanager
def file_moves() -> Iterator[None]:
    """Geteilte Sperre für Dateiverschiebungen samt zugehörigem DB-Commit.

    `scripts/backup.sh` hält dieselbe Sperre exklusiv, solange Dump und Dateiarchiv
    entstehen – so passen gesicherte Pfade und Dateien zusammen, auch wenn API und
    Worker weiterlaufen.
    """
    with open(import_dir(".") / ".files.lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def archive_file(session: Session, batch: ImportBatch) -> None:
    """Verschiebt die Datei nach archive/ (fertig) bzw. failed/ (Fehler) – getrennt vom Ergebnis."""
    if batch.status not in (BatchStatus.DONE, BatchStatus.FAILED) or batch.archive_state == ArchiveState.DONE:
        return
    folder = "archive" if batch.status == BatchStatus.DONE else "failed"
    source = stored_file(batch.stored_path)
    target = import_dir(folder) / f"{batch.id}_{safe_filename(batch.original_filename)}"
    with file_moves():
        try:
            if source != target:
                os.replace(source, target)
            batch.stored_path = to_stored(target)
            batch.archive_state = ArchiveState.DONE
        except OSError:
            log.exception("Archivieren von Import %s fehlgeschlagen", batch.id)
            batch.archive_state = ArchiveState.ERROR
        session.commit()


def archive_pending(session: Session) -> int:
    batches = session.exec(
        select(ImportBatch).where(
            ImportBatch.status.in_([BatchStatus.DONE, BatchStatus.FAILED]),
            ImportBatch.archive_state != ArchiveState.DONE,
        )
    )
    count = 0
    for batch in list(batches):
        archive_file(session, batch)
        count += 1
    return count


# --- Aktionen aus der API ------------------------------------------------------


def get_batch(session: Session, user: User, batch_id: int) -> ImportBatch:
    return get_owned(session, ImportBatch, batch_id, user.id, "Import")


def lock_batch(session: Session, user: User, batch_id: int) -> ImportBatch:
    """Lädt den Auftrag mit Zeilensperre und frischem Stand – parallele Freigaben warten
    aufeinander und sehen danach den neuen Status."""
    batch = session.exec(
        select(ImportBatch)
        .where(ImportBatch.id == batch_id, ImportBatch.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if batch is None:
        raise NotFound(f"Import {batch_id} nicht gefunden")
    return batch


def retry(session: Session, user: User, batch: ImportBatch, account_id: int | None) -> ImportBatch:
    if batch.status != BatchStatus.FAILED:
        raise Conflict("Nur fehlgeschlagene Importe können wiederholt werden", code="import_not_failed")
    profile = session.get(ImportProfile, batch.import_profile_id)
    if account_id is not None:
        validate_target_account(session, user.id, profile, account_id)
        batch.account_id = batch.target_account_id = account_id
    other = existing_batch(session, user.id, profile.id, batch.file_sha256, batch.target_account_id)
    if other is not None:
        raise Conflict(
            f"Diese Datei wurde inzwischen mit Import {other.id} verarbeitet",
            code="import_file_already_processed",
            details={"batch_id": other.id},
        )
    batch.status = BatchStatus.QUEUED
    batch.errors = []
    batch.archive_state = ArchiveState.PENDING
    batch.profile_version = profile.version
    batch.parser_version = PARSER_VERSION
    session.flush()
    return batch


@dataclass
class Resolution:
    action: str
    row_ids: list[int] | None = None
    decision: str | None = None
    match_kind: str | None = None
    matched_transaction_id: int | None = None


def resolve_rows(session: Session, user: User, batch: ImportBatch, req: Resolution) -> int:
    """Entscheidung für einzelne Zeilen oder alle offenen Zeilen einer Art (Sammelaktion)."""
    if batch.status != BatchStatus.AWAITING_REVIEW:
        raise Conflict("Import wartet nicht auf Klärung", code="import_not_awaiting_review")
    query = select(ImportRow).where(ImportRow.batch_id == batch.id)
    if req.row_ids:
        query = query.where(ImportRow.id.in_(req.row_ids))
    else:
        query = query.where(ImportRow.decision.in_(OPEN_DECISIONS), ImportRow.resolution.is_(None))
        if req.decision:
            query = query.where(ImportRow.decision == req.decision)
        if req.match_kind:
            query = query.where(ImportRow.match_kind == req.match_kind)
    rows = list(session.exec(query))
    if req.row_ids and len(rows) != len(set(req.row_ids)):
        raise NotFound("Zeilen gehören nicht zu diesem Import")

    for row in rows:
        if req.action == RowResolution.DUPLICATE:
            target_id = req.matched_transaction_id or row.matched_transaction_id
            if target_id is None:
                raise Invalid(f"Zeile {row.row_no}: keine Buchung zum Zuordnen", code="duplicate_without_match")
            target = get_owned(session, Transaction, target_id, user.id, "Buchung")
            if target.account_id != row.account_id:
                raise Invalid(
                    f"Zeile {row.row_no}: Buchung liegt auf einem anderen Konto", code="duplicate_other_account"
                )
            row.matched_transaction_id = target.id
        if req.action == RowResolution.IMPORT and row.decision == RowDecision.BEFORE_OPENING:
            account = session.get(Account, row.account_id)
            if row.booking_date < account.opening_balance_date:
                raise Invalid(
                    f"Zeile {row.row_no} liegt vor dem Stichtag – erst Stichtag/Anfangssaldo anpassen",
                    code="before_opening",
                )
        row.resolution = req.action
    batch.rows_review = open_row_count(session, batch.id)
    session.flush()
    return len(rows)


def row_summary(rows: list[ImportRow]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        key = effective_action(row) or "open"
        summary[key] = summary.get(key, 0) + 1
    return summary


def watch_folder_for(session: Session, subdir: str) -> WatchFolder | None:
    return session.exec(select(WatchFolder).where(WatchFolder.subdir == subdir)).first()

