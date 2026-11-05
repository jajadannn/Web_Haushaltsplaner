from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import get_settings
from app.deps import CurrentUser, SessionDep
from app.errors import AppError, PayloadTooLarge
from app.services import documents as service

router = APIRouter(prefix="/documents", tags=["Belege"])


class LinkIn(BaseModel):
    transaction_id: int | None = None
    fixed_cost_id: int | None = None
    contract_id: int | None = None


def _read(doc, session) -> dict[str, Any]:
    return {
        "id": doc.id, "kind": doc.kind, "original_filename": doc.original_filename, "mime": doc.mime,
        "size": doc.size, "status": doc.status, "extracted": doc.extracted, "error": doc.error,
        "created_at": doc.created_at,
        "links": [{"id": link.id, "transaction_id": link.transaction_id, "fixed_cost_id": link.fixed_cost_id,
                   "contract_id": link.contract_id} for link in service.links(session, doc)],
    }


@router.get("")
def list_documents(session: SessionDep, user: CurrentUser) -> list[dict[str, Any]]:
    from sqlmodel import select

    from app.models import Document

    docs = session.exec(select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc()))
    return [_read(d, session) for d in docs]


@router.post("", status_code=201)
def upload_document(
    session: SessionDep,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="Beleg, Rechnung oder Vertrag (PDF, JPEG, PNG, WebP)")],
    kind: Annotated[Literal["receipt", "invoice", "contract"], Form()] = "receipt",
) -> dict[str, Any]:
    """Hochladen; das Auslesen übernimmt die lokale KI im Hintergrund (Status `pending` → `extracted`)."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise PayloadTooLarge(f"Datei größer als {get_settings().max_upload_mb} MB")
    if not content:
        raise AppError("Datei ist leer", code="file_empty")
    doc = service.upload(session, user, content, file.filename or "datei", kind)
    session.commit()
    return _read(doc, session)


@router.get("/{document_id}")
def get_document(document_id: int, session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    return _read(service.get_document(session, user, document_id), session)


@router.get("/{document_id}/file")
def document_file(document_id: int, session: SessionDep, user: CurrentUser):
    doc = service.get_document(session, user, document_id)
    return FileResponse(service.file_path(doc), media_type=doc.mime, filename=doc.original_filename)


@router.post("/{document_id}/links", status_code=201)
def link_document(document_id: int, data: LinkIn, session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    doc = service.get_document(session, user, document_id)
    service.add_link(session, user, doc, **data.model_dump())
    session.commit()
    return _read(doc, session)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, session: SessionDep, user: CurrentUser):
    service.delete_document(session, service.get_document(session, user, document_id))
    session.commit()
    return Response(status_code=204)
