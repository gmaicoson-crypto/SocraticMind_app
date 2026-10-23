from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from core.database import get_db
from core.deps import get_current_user
from models.attachment import Attachment, AttachmentChunk
from models.user import User
from schemas.attachments import AttachmentSummary, CoverageConfirmation
from services.attachments import service
from services.attachments.storage import AttachmentStorage

router = APIRouter(prefix="/api/attachments", tags=["附件"])


@router.get("/capabilities")
def capabilities(current_user: User = Depends(get_current_user)):
    return service.capabilities()


@router.post("", response_model=AttachmentSummary)
def upload(
    file: UploadFile = File(...),
    client_upload_id: str = Form(..., min_length=1, max_length=100),
    session_id: str = Form(..., min_length=1, max_length=100),
    mode: str = Form(...),
    topic_id: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.summary(
        service.upload_attachment(
            db,
            user_id=current_user.id,
            file=file,
            client_upload_id=client_upload_id,
            session_id=session_id,
            topic_id=topic_id,
            mode=mode,
        )
    )


@router.get("", response_model=list[AttachmentSummary])
def statuses(
    ids: Annotated[list[str], Query(max_length=50)],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    identifiers = [identifier for group in ids for identifier in group.split(",") if identifier]
    if not identifiers or len(identifiers) > 50:
        service.error("ATTACHMENT_TOO_MANY", "每次最多查询 50 个附件")
    rows = (
        db.query(Attachment)
        .filter(
            Attachment.user_id == current_user.id,
            Attachment.id.in_(identifiers),
            Attachment.status != "deleted",
        )
        .all()
    )
    by_id = {
        row.id: row
        for row in rows
        if row.session_id is not None or not service.expired(row.expires_at)
    }
    if any(identifier not in by_id for identifier in identifiers):
        service.error("ATTACHMENT_NOT_FOUND", "资料不存在、已过期或已删除", 404)
    return [service.summary(by_id[identifier]) for identifier in dict.fromkeys(identifiers)]


@router.post("/{attachment_id}/retry", response_model=AttachmentSummary)
def retry(
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = service.get_owned_attachment(db, current_user.id, attachment_id, lock=True)
    if not service.summary(row)["retryable"]:
        service.error("ATTACHMENT_RETRY_UNAVAILABLE", "该附件不能重试，请移除后重新上传", 409)
    row.status = "pending"
    row.error_code = row.error_message = None
    row.next_retry_at = None
    row.revision += 1
    row.accepted_coverage = row.accepted_revision = None
    db.commit()
    return service.summary(row)


@router.post("/{attachment_id}/accept-text-coverage", response_model=AttachmentSummary)
def accept_coverage(
    attachment_id: str,
    request: CoverageConfirmation,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = service.get_owned_attachment(db, current_user.id, attachment_id, lock=True)
    if (
        row.session_id is not None
        or row.status != "needs_confirmation"
        or row.revision != request.revision
    ):
        service.error("ATTACHMENT_REVISION_CONFLICT", "资料状态已变化，请刷新后确认", 409)
    row.accepted_coverage = row.coverage
    row.accepted_revision = row.revision
    row.status = "ready"
    db.commit()
    return service.summary(row)


def _file_response(row, key, *, inline=False):
    if not key:
        service.error("ATTACHMENT_NOT_READY", "图片预览尚未就绪", 409, True)
    path = AttachmentStorage().path(key)
    if not path.is_file():
        service.error("ATTACHMENT_NOT_FOUND", "资料不存在或已删除", 404)
    return FileResponse(
        path,
        media_type="image/jpeg" if inline else row.mime_type,
        filename=Path(row.name).name,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/{attachment_id}/content")
def content(
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = service.get_owned_attachment(db, current_user.id, attachment_id)
    return _file_response(row, row.storage_key)


@router.get("/{attachment_id}/preview")
def preview(
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = service.get_owned_attachment(db, current_user.id, attachment_id)
    if row.kind != "image":
        service.error("ATTACHMENT_TYPE_UNSUPPORTED", "文档不提供图片预览", 404)
    return _file_response(row, row.preview_key, inline=True)


@router.get("/{attachment_id}/chunks/{chunk_id}")
def chunk(
    attachment_id: str,
    chunk_id: str,
    revision: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    attachment = service.get_owned_attachment(db, current_user.id, attachment_id)
    row = (
        db.query(AttachmentChunk)
        .filter(
            AttachmentChunk.attachment_id == attachment.id,
            AttachmentChunk.revision == (revision or attachment.revision),
            AttachmentChunk.chunk_id == chunk_id,
        )
        .first()
    )
    if row is None:
        service.error("ATTACHMENT_SOURCE_NOT_FOUND", "资料摘录不存在或已删除", 404)
    return {
        name: getattr(row, name)
        for name in (
            "attachment_id",
            "revision",
            "chunk_id",
            "text",
            "locator",
            "block_type",
            "title_path",
        )
    }


@router.delete("/{attachment_id}", status_code=204)
def delete(
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = service.get_owned_attachment(db, current_user.id, attachment_id, lock=True)
    if row.session_id is not None:
        service.error("ATTACHMENT_ALREADY_SENT", "已发送资料请随原消息或会话删除", 409)
    service.mark_deleted(db, [row])
    db.commit()
    return Response(status_code=204)


class AttachmentUploadLimitMiddleware:
    """Bound multipart bytes before Starlette spools an UploadFile to disk."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path", "").rstrip("/") != "/api/attachments"
        ):
            return await self.app(scope, receive, send)
        from fastapi.responses import JSONResponse
        from core.errors import ApiError
        from services.attachments.config import LIMITS

        limit = max(LIMITS["max_document_bytes"], LIMITS["max_image_bytes"]) + 64 * 1024
        headers = dict(scope.get("headers", []))
        response = JSONResponse(
            status_code=413,
            content={
                "code": "ATTACHMENT_TOO_LARGE",
                "message": "上传内容超过大小限制",
                "retryable": False,
            },
        )
        try:
            if int(headers.get(b"content-length", b"0")) > limit:
                return await response(scope, receive, send)
        except ValueError:
            return await response(scope, receive, send)
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise ApiError(
                        status_code=413,
                        code="ATTACHMENT_TOO_LARGE",
                        message="上传内容超过大小限制",
                        retryable=False,
                    )
            return message

        overflow_sent = False

        async def bounded_send(message):
            nonlocal overflow_sent
            if consumed > limit:
                if not overflow_sent:
                    overflow_sent = True
                    await response(scope, receive, send)
                return
            await send(message)

        try:
            return await self.app(scope, bounded_receive, bounded_send)
        except ApiError:
            if consumed <= limit:
                raise
            if not overflow_sent:
                await response(scope, receive, send)
