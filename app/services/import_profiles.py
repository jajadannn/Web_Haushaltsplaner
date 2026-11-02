from sqlmodel import Session, func, select

from app.config import get_settings
from app.errors import Conflict, Invalid
from app.models import Institution, User
from app.models.imports import ImportBatch, ImportProfile, WatchFolder
from app.schemas.imports import ImportProfileCreate, WatchFolderCreate, check_csv_settings
from app.services.common import flush_or_conflict, get_owned
from app.services.import_jobs import validate_target_account

_UNIQUE = {
    "uq_import_profile_user_id_name": "Ein Importprofil mit diesem Namen existiert bereits",
    "uq_watch_folder_subdir": "Dieser Ordnername ist bereits vergeben",
}
_READ_RULES = {"delimiter", "encoding", "skip_rows", "column_map", "date_format", "decimal_sep",
               "thousands_sep", "sign_mode", "debit_indicators", "pending_values"}


def list_profiles(session: Session, user: User) -> list[ImportProfile]:
    query = select(ImportProfile).where(ImportProfile.user_id == user.id)
    return list(session.exec(query.order_by(func.lower(ImportProfile.name), ImportProfile.id)))


def get_profile(session: Session, user: User, profile_id: int) -> ImportProfile:
    return get_owned(session, ImportProfile, profile_id, user.id, "Importprofil")


def create_profile(session: Session, user: User, data: ImportProfileCreate) -> ImportProfile:
    get_owned(session, Institution, data.institution_id, user.id, "Bank")
    profile = ImportProfile(user_id=user.id, **data.model_dump())
    session.add(profile)
    flush_or_conflict(session, _UNIQUE)
    return profile


def update_profile(session: Session, profile: ImportProfile, changes: dict) -> ImportProfile:
    merged = {key: getattr(profile, key) for key in _READ_RULES} | changes
    try:
        check_csv_settings(profile.format, merged)
    except ValueError as exc:
        raise Invalid(str(exc), code="invalid_profile") from exc
    if any(changes.get(key, getattr(profile, key)) != getattr(profile, key) for key in _READ_RULES & changes.keys()):
        profile.version += 1  # nachvollziehbar, mit welchen Leseregeln ein Import lief
    for key, value in changes.items():
        setattr(profile, key, value)
    flush_or_conflict(session, _UNIQUE)
    return profile


def delete_profile(session: Session, profile: ImportProfile) -> None:
    usage = {
        "imports": session.exec(select(func.count()).where(ImportBatch.import_profile_id == profile.id)).one(),
        "watch_folders": session.exec(select(func.count()).where(WatchFolder.import_profile_id == profile.id)).one(),
    }
    usage = {k: v for k, v in usage.items() if v}
    if usage:
        raise Conflict("Importprofil wird noch verwendet", code="profile_in_use", details=usage)
    session.delete(profile)
    session.flush()


def inbox_path(subdir: str):
    return get_settings().import_dir / "inbox" / subdir


def list_watch_folders(session: Session, user: User) -> list[WatchFolder]:
    return list(session.exec(select(WatchFolder).where(WatchFolder.user_id == user.id).order_by(WatchFolder.subdir)))


def create_watch_folder(session: Session, user: User, data: WatchFolderCreate) -> WatchFolder:
    profile = get_profile(session, user, data.import_profile_id)
    if data.account_id is not None:
        validate_target_account(session, user.id, profile, data.account_id)
    folder = WatchFolder(user_id=user.id, **data.model_dump())
    session.add(folder)
    flush_or_conflict(session, _UNIQUE)
    inbox_path(folder.subdir).mkdir(parents=True, exist_ok=True)
    return folder


def delete_watch_folder(session: Session, user: User, folder_id: int) -> None:
    session.delete(get_owned(session, WatchFolder, folder_id, user.id, "Watch-Ordner"))
    session.flush()
