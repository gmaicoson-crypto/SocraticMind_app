"""Attachment authorization and lifecycle; binding/deletion join the caller's transaction."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

from sqlalchemy.orm import Session

from core.errors import ApiError
from models.attachment import Attachment, AttachmentChunk, AttachmentCleanup, MessageAttachment
from models.chat_session import ChatSession
from models.topic import Topic
from models.user import User
from .config import (
    DRAFT_HOURS,
    EXTENSIONS,
    LIMITS,
    MAX_ATTEMPTS,
    isolation_available,
    libreoffice_path,
)
from .parsers import ParseFailure, validate_file_type
from .storage import AttachmentStorage


def utcnow():
    return datetime.now(timezone.utc)


def expired(value) -> bool:
    return bool(value and value.replace(tzinfo=timezone.utc) <= utcnow())


def error(code, message, status=422, retryable=False):
    raise ApiError(status_code=status, code=code, message=message, retryable=retryable)


def summary(attachment: Attachment) -> dict:
    fields = (
        "id",
        "name",
        "mime_type",
        "size",
        "kind",
        "status",
        "pages",
        "width",
        "height",
        "revision",
        "warnings",
        "coverage",
        "accepted_coverage",
        "error_code",
        "error_message",
    )
    result = {name: getattr(attachment, name) for name in fields}
    result["warnings"] = result["warnings"] or []
    result["retryable"] = (
        attachment.status == "failed"
        and attachment.attempts < MAX_ATTEMPTS
        and attachment.error_code == "ATTACHMENT_PARSE_FAILED"
        and attachment.session_id is None
    )
    return result


def capabilities() -> dict:
    converter = libreoffice_path()
    return {
        "allowed_extensions": list(EXTENSIONS),
        "limits": LIMITS,
        "parsers": {
            "legacy_office": bool(converter) and isolation_available(),
            "legacy_office_error": None
            if converter and isolation_available()
            else "旧版 Office 转换需要 LibreOffice 和操作系统解析沙箱",
            "parser_isolation": isolation_available(),
        },
        "ocr_available": False,
    }


def get_owned_attachment(db: Session, user_id: int, attachment_id: str, lock=False) -> Attachment:
    query = db.query(Attachment).filter(
        Attachment.id == attachment_id,
        Attachment.user_id == user_id,
        Attachment.status != "deleted",
    )
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None or (row.session_id is None and expired(row.expires_at)):
        error("ATTACHMENT_NOT_FOUND", "资料不存在、已过期或已删除", 404)
    return row


def _validate_scope(db, user_id, session_id, topic_id, mode):
    if mode not in {"normal", "socratic"} or not session_id or len(session_id) > 100:
        error("ATTACHMENT_SCOPE_MISMATCH", "附件会话范围无效")
    if mode == "normal" and topic_id is not None:
        error("ATTACHMENT_SCOPE_MISMATCH", "普通对话不能指定学习主题")
    if mode == "socratic" and topic_id is None:
        error("ATTACHMENT_SCOPE_MISMATCH", "学习附件需要选择已有主题和节点")
    if (
        topic_id is not None
        and not db.query(Topic.id).filter(Topic.id == topic_id, Topic.user_id == user_id).first()
    ):
        error("ATTACHMENT_SCOPE_MISMATCH", "学习主题不存在", 404)
    session = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user_id, ChatSession.session_id == session_id)
        .first()
    )
    if session and (session.topic_id != topic_id or session.mode != mode):
        error("ATTACHMENT_SCOPE_MISMATCH", "附件与会话的主题或模式不一致")


def upload_attachment(
    db, *, user_id, file, client_upload_id, session_id, topic_id, mode
) -> Attachment:
    _validate_scope(db, user_id, session_id, topic_id, mode)
    if not client_upload_id or len(client_upload_id) > 100:
        error("ATTACHMENT_UPLOAD_ID_INVALID", "上传标识无效")
    name = Path((file.filename or "").replace("\\", "/")).name[:255]
    extension = Path(name).suffix.lower()
    if extension not in EXTENSIONS:
        error("ATTACHMENT_TYPE_UNSUPPORTED", "仅支持 JPG、PNG、WebP、Word、PDF 和 PowerPoint")
    if not isolation_available():
        error("ATTACHMENT_PARSER_UNAVAILABLE", "附件解析沙箱不可用，请联系管理员", 503, True)
    if extension in {".doc", ".ppt"} and not libreoffice_path():
        error(
            "ATTACHMENT_CONVERTER_UNAVAILABLE",
            "服务未安装 LibreOffice，暂时无法接收旧版 Office 文件",
            503,
            True,
        )
    kind = "image" if EXTENSIONS[extension].startswith("image/") else "document"
    storage = AttachmentStorage()
    temporary, size, digest = storage.stage(file.file, LIMITS[f"max_{kind}_bytes"])
    published = None
    try:
        try:
            validate_file_type(temporary, extension)
        except ParseFailure as exc:
            error(exc.code, str(exc))
        except Exception:
            error("ATTACHMENT_PARSE_FAILED", "文件损坏或格式不受支持")
        # Serialize upload quota/idempotency per user; no hash-based sharing across users.
        if not db.query(User).filter(User.id == user_id).with_for_update().first():
            error("ATTACHMENT_NOT_FOUND", "用户不存在", 404)
        existing = (
            db.query(Attachment)
            .filter(Attachment.user_id == user_id, Attachment.client_upload_id == client_upload_id)
            .with_for_update()
            .first()
        )
        if existing:
            if (
                existing.sha256 != digest
                or existing.name != name
                or existing.draft_session_id != session_id
                or existing.mode != mode
                or existing.topic_id != topic_id
            ):
                error("ATTACHMENT_UPLOAD_CONFLICT", "相同上传标识不能用于不同文件或会话", 409)
            if existing.status == "deleted" or expired(existing.expires_at):
                error("ATTACHMENT_UPLOAD_EXPIRED", "该上传已删除或过期，请重新添加文件", 409)
            return existing
        reserve = 12 * 1024 * 1024 if kind == "image" else 20 * 1024 * 1024
        stored = (
            db.query(Attachment.size, Attachment.kind)
            .filter(Attachment.user_id == user_id, Attachment.status != "deleted")
            .with_for_update()
            .all()
        )
        used = sum(
            size + (12 if stored_kind == "image" else 20) * 1024 * 1024
            for size, stored_kind in stored
        )
        if used + size + reserve > LIMITS["max_user_bytes"]:
            error(
                "ATTACHMENT_QUOTA_EXCEEDED", "附件存储已达到 500 MiB 配额，请先删除不用的资料", 413
            )
        attachment_id = str(uuid.uuid4())
        key = f"{attachment_id}/original{extension}"
        storage.publish(temporary, key)
        published = attachment_id
        row = Attachment(
            id=attachment_id,
            user_id=user_id,
            client_upload_id=client_upload_id,
            draft_session_id=session_id,
            topic_id=topic_id,
            mode=mode,
            name=name,
            mime_type=EXTENSIONS[extension],
            size=size,
            sha256=digest,
            storage_key=key,
            kind=kind,
            status="pending",
            revision=1,
            warnings=[],
            attempts=0,
            expires_at=utcnow() + timedelta(hours=DRAFT_HOURS),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except BaseException:
        db.rollback()
        if published:
            storage.delete(published)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def summaries_for_messages(db, message_ids) -> dict[int, list[dict]]:
    result = {message_id: [] for message_id in message_ids}
    if not result:
        return result
    rows = (
        db.query(MessageAttachment, Attachment)
        .join(Attachment, Attachment.id == MessageAttachment.attachment_id)
        .filter(MessageAttachment.user_message_id.in_(result), Attachment.status != "deleted")
        .order_by(MessageAttachment.user_message_id, MessageAttachment.position)
        .all()
    )
    for association, attachment in rows:
        item = summary(attachment)
        item["revision"] = association.revision
        item["accepted_coverage"] = association.accepted_coverage
        result[association.user_message_id].append(item)
    return result


def validate_for_message(db, *, user_id, session_id, topic_id, mode, ids) -> list[Attachment]:
    if len(ids) > LIMITS["max_attachments"] or len(set(ids)) != len(ids):
        error("ATTACHMENT_TOO_MANY", f"每条消息最多 {LIMITS['max_attachments']} 个附件，且不能重复")
    _validate_scope(db, user_id, session_id, topic_id, mode)
    rows = [get_owned_attachment(db, user_id, identifier, lock=True) for identifier in sorted(ids)]
    ordered = {row.id: row for row in rows}
    rows = [ordered[identifier] for identifier in ids]
    for row in rows:
        if (
            row.session_id is not None
            or row.draft_session_id != session_id
            or row.topic_id != topic_id
            or row.mode != mode
        ):
            error("ATTACHMENT_SCOPE_MISMATCH", "附件已发送或不属于当前会话", 409)
        if row.status != "ready" or (
            row.coverage
            and row.coverage.get("missing_pages")
            and row.accepted_revision != row.revision
        ):
            error("ATTACHMENT_NOT_READY", "请等待全部附件解析完成并确认可用页范围", 409, True)
    if sum(row.size for row in rows) > LIMITS["max_message_bytes"]:
        error("ATTACHMENT_TOO_LARGE", "单条消息附件总大小不能超过 50 MiB", 413)
    return rows


def bind_to_message(db, *, message_id, session_id, attachments):
    for position, attachment in enumerate(attachments):
        attachment.session_id = session_id
        attachment.expires_at = None
        db.add(
            MessageAttachment(
                user_message_id=message_id,
                attachment_id=attachment.id,
                position=position,
                revision=attachment.revision,
                accepted_coverage=attachment.accepted_coverage,
            )
        )


def mark_deleted(db, rows):
    for row in rows:
        if row.status == "deleted":
            continue
        row.status = "deleted"
        row.lease_token = None
        row.lease_until = None
        db.add(AttachmentCleanup(id=str(uuid.uuid4()), storage_prefix=row.id))
        db.query(MessageAttachment).filter(MessageAttachment.attachment_id == row.id).delete(
            synchronize_session=False
        )
        db.query(AttachmentChunk).filter(AttachmentChunk.attachment_id == row.id).delete(
            synchronize_session=False
        )


def delete_for_messages(db, message_ids):
    if not message_ids:
        return
    ids = [
        row[0]
        for row in db.query(MessageAttachment.attachment_id)
        .filter(MessageAttachment.user_message_id.in_(message_ids))
        .all()
    ]
    if ids:
        mark_deleted(
            db, db.query(Attachment).filter(Attachment.id.in_(ids)).with_for_update().all()
        )


def delete_for_scope(db, *, user_id, session_id=None, topic_id=None):
    query = db.query(Attachment).filter(
        Attachment.user_id == user_id, Attachment.status != "deleted"
    )
    if session_id is not None:
        query = query.filter(Attachment.draft_session_id == session_id)
    if topic_id is not None:
        query = query.filter(Attachment.topic_id == topic_id)
    mark_deleted(db, query.with_for_update().all())


def delete_for_user(db, user_id):
    rows = db.query(Attachment).filter(Attachment.user_id == user_id).with_for_update().all()
    mark_deleted(db, rows)
    db.flush()
    # Keep independent cleanup rows, remove user-FK records before account deletion.
    for row in rows:
        db.delete(row)
    db.flush()
