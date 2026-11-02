from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from sqlmodel import select

from app.config import get_settings
from app.deps import CurrentUser, SessionDep
from app.errors import AppError, Conflict, PayloadTooLarge
from app.models.imports import BatchSource, BatchStatus, ImportBatch, ImportRow, RowDecision
from app.schemas.imports import (
    ImportBatchRead,
    ImportProfileCreate,
    ImportProfileRead,
    ImportProfileUpdate,
    ImportRowRead,
    RetryRequest,
    RowResolve,
    WatchFolderCreate,
    WatchFolderRead,
)
from app.services import import_jobs as jobs
from app.services import import_profiles as profiles
from app.services.import_commit import OPEN_DECISIONS

router = APIRouter(tags=["Import"])


# --- Importprofile ------------------------------------------------------------


@router.get("/import-profiles", response_model=list[ImportProfileRead])
def list_profiles(session: SessionDep, user: CurrentUser):
    return profiles.list_profiles(session, user)


@router.post("/import-profiles", response_model=ImportProfileRead, status_code=201)
def create_profile(data: ImportProfileCreate, session: SessionDep, user: CurrentUser):
    """Dateiformat einer Bank (CSV mit Spaltenzuordnung, OFX oder MT940)."""
    profile = profiles.create_profile(session, user, data)
    session.commit()
    return profile


@router.get("/import-profiles/{profile_id}", response_model=ImportProfileRead)
def get_profile(profile_id: int, session: SessionDep, user: CurrentUser):
    return profiles.get_profile(session, user, profile_id)


@router.patch("/import-profiles/{profile_id}", response_model=ImportProfileRead)
def update_profile(profile_id: int, data: ImportProfileUpdate, session: SessionDep, user: CurrentUser):
    profile = profiles.update_profile(session, profiles.get_profile(session, user, profile_id), data.changes())
    session.commit()
    return profile


@router.delete("/import-profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, session: SessionDep, user: CurrentUser):
    profiles.delete_profile(session, profiles.get_profile(session, user, profile_id))
    session.commit()
    return Response(status_code=204)


# --- Watch-Ordner -------------------------------------------------------------


def _folder_read(folder) -> WatchFolderRead:
    return WatchFolderRead.model_validate(folder).model_copy(
        update={"path": str(profiles.inbox_path(folder.subdir))}
    )


@router.get("/watch-folders", response_model=list[WatchFolderRead])
def list_watch_folders(session: SessionDep, user: CurrentUser):
    return [_folder_read(f) for f in profiles.list_watch_folders(session, user)]


@router.post("/watch-folders", response_model=WatchFolderRead, status_code=201)
def create_watch_folder(data: WatchFolderCreate, session: SessionDep, user: CurrentUser):
    """Unterordner der Import-Inbox. Ohne `account_id` wird jede Datei über die
    IBAN/Kontoangabe darin einem Konto dieser Bank zugeordnet."""
    folder = profiles.create_watch_folder(session, user, data)
    session.commit()
    return _folder_read(folder)


@router.delete("/watch-folders/{folder_id}", status_code=204)
def delete_watch_folder(folder_id: int, session: SessionDep, user: CurrentUser):
    profiles.delete_watch_folder(session, user, folder_id)
    session.commit()
    return Response(status_code=204)


# --- Importe ------------------------------------------------------------------


@router.post("/imports", response_model=ImportBatchRead, status_code=202)
def upload(
    session: SessionDep,
    user: CurrentUser,
    response: Response,
    file: Annotated[UploadFile, File(description="Kontoauszug (CSV, OFX oder MT940)")],
    import_profile_id: Annotated[int, Form()],
    account_id: Annotated[int | None, Form()] = None,
):
    """Datei hochladen. Der Auftrag wird vom Import-Worker verarbeitet (202).
    Dieselbe Datei ein zweites Mal liefert den vorhandenen Auftrag (200)."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise PayloadTooLarge(f"Datei größer als {get_settings().max_upload_mb} MB")
    if not content:
        raise AppError("Datei ist leer", code="file_empty")
    profile = profiles.get_profile(session, user, import_profile_id)
    if account_id is not None:
        jobs.validate_target_account(session, user.id, profile, account_id)
    batch, created = jobs.create_batch(
        session,
        user_id=user.id,
        profile=profile,
        content=content,
        original_filename=file.filename or "upload",
        source=BatchSource.UPLOAD,
        account_id=account_id,
    )
    session.commit()
    if not created:
        response.status_code = 200
    return ImportBatchRead.model_validate(batch).model_copy(update={"already_imported": not created})


@router.post("/imports/process")
def process_now(session: SessionDep, user: CurrentUser):
    """Verarbeitet wartende Aufträge sofort – Alternative, wenn kein Worker läuft."""
    return {"processed": jobs.process_queue(session)}


@router.get("/imports", response_model=list[ImportBatchRead])
def list_imports(
    session: SessionDep,
    user: CurrentUser,
    status: BatchStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    query = select(ImportBatch).where(ImportBatch.user_id == user.id)
    if status is not None:
        query = query.where(ImportBatch.status == status)
    return list(session.exec(query.order_by(ImportBatch.id.desc()).limit(limit)))


@router.get("/imports/{batch_id}", response_model=ImportBatchRead)
def get_import(batch_id: int, session: SessionDep, user: CurrentUser):
    return jobs.get_batch(session, user, batch_id)


@router.get("/imports/{batch_id}/rows", response_model=list[ImportRowRead])
def list_rows(
    batch_id: int,
    session: SessionDep,
    user: CurrentUser,
    decision: RowDecision | None = None,
    open_only: bool = False,
):
    """Importpositionen mit Entscheidung, Vorschlag (`matched_transaction_id`) und Hinweis."""
    batch = jobs.get_batch(session, user, batch_id)
    query = select(ImportRow).where(ImportRow.batch_id == batch.id)
    if decision is not None:
        query = query.where(ImportRow.decision == decision)
    if open_only:
        query = query.where(ImportRow.decision.in_(OPEN_DECISIONS), ImportRow.resolution.is_(None))
    return list(session.exec(query.order_by(ImportRow.row_no)))


@router.post("/imports/{batch_id}/rows/resolve")
def resolve_rows(batch_id: int, data: RowResolve, session: SessionDep, user: CurrentUser):
    """`import` = als neue Buchung übernehmen, `duplicate` = ist schon vorhanden
    (Vorschlag oder `matched_transaction_id`), `skip` = ignorieren."""
    batch = jobs.lock_batch(session, user, batch_id)
    count = jobs.resolve_rows(session, user, batch, jobs.Resolution(**data.model_dump()))
    session.commit()
    return {"resolved": count, "open_rows": batch.rows_review}


@router.post("/imports/{batch_id}/commit", response_model=ImportBatchRead)
def commit_import(batch_id: int, session: SessionDep, user: CurrentUser):
    """Übernimmt einen geklärten Import in einer Datenbanktransaktion."""
    batch = jobs.lock_batch(session, user, batch_id)
    if batch.status != BatchStatus.AWAITING_REVIEW:
        raise Conflict("Import wartet nicht auf Klärung", code="import_not_awaiting_review")
    conflicts = jobs.commit(session, batch)
    session.commit()
    if conflicts:
        raise Conflict(
            "Neue Konflikte seit der Prüfung – betroffene Zeilen erneut klären",
            code="import_new_conflicts",
            details={"rows": conflicts},
        )
    jobs.archive_file(session, batch)
    return batch


@router.post("/imports/{batch_id}/retry", response_model=ImportBatchRead)
def retry_import(batch_id: int, session: SessionDep, user: CurrentUser, data: RetryRequest | None = None):
    """Fehlgeschlagenen Import erneut einreihen – z. B. nach Korrektur des Profils
    oder mit anderem Konto (`account_id`)."""
    batch = jobs.retry(session, user, jobs.get_batch(session, user, batch_id), data.account_id if data else None)
    session.commit()
    return batch
