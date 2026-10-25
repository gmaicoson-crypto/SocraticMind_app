from datetime import datetime, timedelta, timezone
from copy import deepcopy
import hashlib
import json
import logging
import re
import uuid
from time import perf_counter, monotonic
from typing import List, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session, sessionmaker
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai.agent import chat_stream
from ai.prompts import build_normal_suggestions_prompt, build_socratic_suggestions_prompt
from ai.util import extract_json_from_markdown
from core.database import get_db
from core.avatar_uploads import UPLOAD_DIR, read_avatar_upload
from core import rate_limit
from core.deps import get_current_user
from core.ai_client import get_ai_client, resolve_llm_profile, resolve_model_id
from core.user_llm import load_user_profiles
from models import ChatSession
from models.progress import ChatMessage
from models.node import Node
from models.topic import Topic
from models.user import User
from core.errors import ApiError
from core.context_budget import (
    ContextWindowExceeded,
    count_messages,
    count_method,
    get_context_policy,
)
from routers.chat_history import router as history_router
from schemas.chat_history import HistoryResponse
from schemas.chat_request import ChatRequest
from services.chat_history import history_responses, turn_usage, visible_messages
from services.chat_feedback import ChatUsageCollector, classify_chat_error, error_description
from services.chat_context import assemble_chat_context
from services.web_evidence import apply_web_context, cited_source_ids, invalid_source_ids
from services.web_search import iter_web_search, web_search_capabilities
from services.web_search_quota import reserve_web_queries
from services.chat_stream_runner import cancellable_chat_stream
from services.chat_summaries import run_one_summary_job, schedule_chat_summary
from services.chat_titles import schedule_title
from services.chat_lifecycle import (
    begin_chat_turn,
    finish_chat_turn,
    cancel_chat_turn,
    refresh_generation_lease,
    checkpoint_interrupted_content,
    get_chat_turn,
    recover_chat_turn,
)
from services.progress_archive import archive_and_delete_messages, delete_agent_runs
from services.attachments.service import summaries_for_messages

router = APIRouter(prefix="/api/chat", tags=["对话"])
router.include_router(history_router)
log = logging.getLogger(__name__)


def _chat_avatar_prefix(user_id: int, session_id: str) -> str:
    session_hash = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
    return f"ai_{user_id}_{session_hash}_"


def _delete_chat_avatar_files(user_id: int, session_id: str, *, except_name: str = "") -> int:
    deleted = 0
    for image in UPLOAD_DIR.glob(f"{_chat_avatar_prefix(user_id, session_id)}*"):
        if image.name == except_name:
            continue
        try:
            image.unlink()
            deleted += 1
        except OSError:
            log.warning("Failed to remove chat avatar %s", image)
    return deleted


def selected_model(model_id: str | None, user_id: int | None = None) -> str:
    try:
        return resolve_model_id(model_id, user_id=user_id)
    except ValueError as error:
        raise ApiError(
            status_code=422,
            code="LLM_MODEL_UNAVAILABLE",
            message="所选模型不可用，请刷新模型列表后重试。",
            retryable=False,
        ) from error


@router.get("/capabilities")
def chat_capabilities(current_user: User = Depends(get_current_user)):
    return web_search_capabilities()


@router.post("/stream")
def chat_stream_endpoint(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    load_user_profiles(db, current_user.id)
    # topic_overview 模式下 node_key 承载的是主题名，不需要查节点表
    if req.kind == "topic_overview":
        topic = (
            db.query(Topic)
            .filter(
                Topic.id == req.topic_id,
                Topic.user_id == current_user.id,
            )
            .first()
        )
        if not topic:
            raise HTTPException(status_code=404, detail="主题不存在")
        node_label = topic.title
        node_sub = ""
    elif req.mode == "normal":
        node_label = "通用助手"
        node_sub = "General Assistant"
    else:
        # 通过 join Topic 校验节点归属，防止越权访问其他用户的节点
        node = (
            db.query(Node)
            .join(Topic)
            .filter(
                Node.node_key == req.node_key,
                Topic.id == req.topic_id,
                Topic.user_id == current_user.id,
            )
            .first()
        )
        if not node:
            raise HTTPException(status_code=404, detail="节点不存在")
        node_label = node.label
        node_sub = node.sub

    model_id = selected_model(req.model, current_user.id)

    quote_source = None
    if req.quote_source_id is not None:
        quote_source = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.id == req.quote_source_id,
                ChatMessage.user_id == current_user.id,
                ChatMessage.session_id == req.session_id,
                ChatMessage.mode == req.mode,
                ChatMessage.role == "ai",
            )
            .one_or_none()
        )
        if quote_source is None or not req.quote_text:
            raise ApiError(status_code=400, code="CHAT_QUOTE_INVALID", message="引用消息无效")

    started = begin_chat_turn(
        db,
        user_id=current_user.id,
        topic_id=req.topic_id if req.mode == "socratic" else None,
        session_id=req.session_id,
        node_key=node_label if req.kind == "topic_overview" else req.node_key,
        user_input=req.user_input,
        mode=req.mode,
        request_id=req.request_id,
        model_id=model_id,
        kind=req.kind,
        ai_style=req.ai_style,
        quote_text=req.quote_text,
        quote_source_id=req.quote_source_id,
        regenerate_message_id=req.regenerate_message_id,
        web_mode=req.web_mode,
        attachment_ids=req.attachment_ids,
    )
    user_id = current_user.id
    if req.kind == "qa" and req.regenerate_message_id is None:
        try:
            source = req.user_input
            if req.attachment_ids:
                attached = summaries_for_messages(db, [started.user_message.id]).get(
                    started.user_message.id, []
                )
                source += "\n附件：" + "、".join(item["name"] for item in attached)
            if source.strip():
                schedule_title(
                    db,
                    user_id=current_user.id,
                    session_id=req.session_id,
                    mode=req.mode,
                    source_text=source,
                    model_id=model_id,
                )
                db.commit()
        except Exception as error:
            db.rollback()
            log.warning("chat_title_schedule_failed error_type=%s", type(error).__name__)
    session_pk = started.session.id
    generation_token = started.turn.generation_token
    user_msg, ai_msg = started.user_message, started.ai_message
    model_user_input = user_msg.content
    ids = {"user": user_msg.id, "ai": ai_msg.id}
    initial_web = deepcopy((ai_msg.metadata_json or {}).get("web"))

    def web_event(payload):
        return event({**payload, "request_id": req.request_id, "ai_message_id": ids["ai"]})

    def event(payload):
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    if started.replayed:
        from services.attachments.evidence import hydrate_message_sources

        if initial_web is not None:
            initial_web["sources"] = hydrate_message_sources(
                db, user_id=user_id, messages=[ai_msg]
            ).get(ai_msg.id, initial_web.get("sources", []))
        if started.turn.status == "generating":
            raise ApiError(
                status_code=409,
                code="CHAT_REQUEST_RUNNING",
                message="该请求仍在生成，请稍后恢复会话",
                retryable=True,
            )
        replay_status = started.turn.status
        replay_content = ai_msg.content
        replay_error = started.turn.error_code

        def replay():
            yield event({"msg_ids": ids})
            if initial_web is not None:
                yield web_event(
                    {"type": "web_status", "status": initial_web["status"], "web": initial_web}
                )
                for warning in initial_web.get("warnings", []):
                    yield web_event({"type": "web_warning", "warning": warning, "web": initial_web})
            if replay_content:
                yield event({"text": replay_content})
            if initial_web is not None:
                yield web_event({"type": "web_sources", "web": initial_web, "final": True})
            yield event({"request_state": {"status": replay_status}})
            if replay_status != "complete":
                yield event({"error": error_description(replay_error or "CHAT_REQUEST_INCOMPLETE")})
            yield "data: [DONE]\n\n"

        return StreamingResponse(replay(), media_type="text/event-stream")

    context_args = dict(
        user_message_id=user_msg.id,
        model_id=model_id,
        node_key=req.node_key,
        node_label=node_label,
        node_sub=node_sub,
        user_input=model_user_input,
        mode=req.mode,
        ai_style=req.ai_style,
        kind=req.kind,
        regenerate=req.regenerate_message_id is not None,
        quote_source=quote_source,
    )
    from models.attachment import Attachment

    has_attachment_context = (
        req.kind == "qa"
        and db.query(Attachment.id)
        .filter_by(
            user_id=user_id,
            session_id=req.session_id,
        )
        .first()
        is not None
    )
    try:
        # Resource preparation emits progress after SSE opens. Text-only requests
        # retain their immediate HTTP context validation contract.
        prepared = (
            None
            if has_attachment_context
            else assemble_chat_context(db, session=started.session, **context_args)
        )
    except Exception as error:
        finish_chat_turn(
            db,
            user_id=user_id,
            request_id=req.request_id,
            generation_token=generation_token,
            content="",
            status="failed",
            error_code=(
                "CHAT_CONTEXT_TOO_LARGE"
                if isinstance(error, ContextWindowExceeded)
                else "CONTEXT_PREPARATION_FAILED"
            ),
        )
        if isinstance(error, ContextWindowExceeded):
            return JSONResponse(
                status_code=413,
                content={
                    "code": "CHAT_CONTEXT_TOO_LARGE",
                    "message": "当前问题或引用内容超过模型可用窗口，请缩小引用范围或拆分输入",
                    "retryable": False,
                    "msg_ids": ids,
                },
            )
        raise

    input_tokens = prepared.input_tokens if prepared else 0
    log.info(
        "chat_context_prepared request=%s model=%s input_tokens=%d count_method=%s omitted_history=%s",
        req.request_id,
        model_id,
        input_tokens,
        count_method(model_id),
        prepared.omitted_history if prepared else False,
    )
    context_session_factory = sessionmaker(bind=db.get_bind())
    # No request-scoped read transaction is held while waiting for the provider.
    db.commit()

    def generate():
        full_text = []
        usage = ChatUsageCollector(req.request_id)
        stream = None
        began = perf_counter()
        checkpoint = began
        first_chunk = True
        terminal = False
        active_context = prepared
        attachment_evidence = None
        deadline = monotonic() + 240
        web = deepcopy(initial_web)

        def check_active():
            if has_attachment_context and monotonic() >= deadline:
                raise ApiError(
                    status_code=504,
                    code="ATTACHMENT_CONTEXT_TIMEOUT",
                    message="资料处理或回答超时，请缩小范围后重试",
                    retryable=True,
                )
            if not refresh_generation_lease(
                db, user_id=user_id, request_id=req.request_id, generation_token=generation_token
            ):
                db.rollback()
                raise ApiError(
                    status_code=409,
                    code="CHAT_REQUEST_CANCELLED",
                    message="本次生成已停止或会话内容已改变",
                    retryable=True,
                )

        def reserve_search(queries):
            allowed = reserve_web_queries(
                db,
                user_id=user_id,
                request_id=req.request_id,
                generation_token=generation_token,
                queries=queries,
            )
            # Cancellation must not become a quota warning and then a normal answer.
            check_active()
            return allowed

        def persist_web():
            if not refresh_generation_lease(
                db,
                user_id=user_id,
                request_id=req.request_id,
                generation_token=generation_token,
                web=web,
            ):
                db.rollback()
                raise ApiError(
                    status_code=409,
                    code="CHAT_REQUEST_CANCELLED",
                    message="本次生成已停止或会话内容已改变",
                    retryable=True,
                )

        try:
            yield event({"msg_ids": ids})
            if not refresh_generation_lease(
                db,
                user_id=user_id,
                request_id=req.request_id,
                generation_token=generation_token,
                preparation={
                    "status": "preparing",
                    "deadline_at": (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=max(0, deadline - monotonic()))
                    ).isoformat(),
                }
                if has_attachment_context
                else None,
            ):
                raise ApiError(
                    status_code=409,
                    code="CHAT_REQUEST_CANCELLED",
                    message="本次生成已停止",
                    retryable=True,
                )
            if has_attachment_context:
                from services.attachments.context import (
                    iter_prepare_attachments,
                    PreparedAttachments,
                )

                yield event(
                    {
                        "type": "attachment_context_preparing",
                        "status": "preparing",
                        "request_id": req.request_id,
                        "ai_message_id": ids["ai"],
                    }
                )
                for update in iter_prepare_attachments(
                    db,
                    session=started.session,
                    user_message_id=ids["user"],
                    model_id=model_id,
                    user_input=model_user_input,
                    mode=req.mode,
                    check_active=check_active,
                    deadline=min(deadline, monotonic() + 90),
                    quote_source=quote_source,
                ):
                    check_active()
                    if isinstance(update, PreparedAttachments):
                        attachment_evidence = update
                    else:
                        if not refresh_generation_lease(
                            db,
                            user_id=user_id,
                            request_id=req.request_id,
                            generation_token=generation_token,
                            preparation=update,
                        ):
                            check_active()
                        yield event(
                            {
                                **update,
                                "type": "attachment_context_progress",
                                "request_id": req.request_id,
                                "ai_message_id": ids["ai"],
                            }
                        )
                if attachment_evidence is None:
                    raise ApiError(
                        status_code=502,
                        code="ATTACHMENT_CONTEXT_FAILED",
                        message="资料未能整理完成，请重试",
                        retryable=True,
                    )
                context_args["attachments"] = attachment_evidence
                context_session = db.get(ChatSession, session_pk)
                if context_session is None:
                    check_active()
                active_context = assemble_chat_context(db, session=context_session, **context_args)
                db.commit()
                if not refresh_generation_lease(
                    db,
                    user_id=user_id,
                    request_id=req.request_id,
                    generation_token=generation_token,
                    preparation={"status": "ready"},
                    attachment_derived=attachment_evidence.attachment_derived,
                ):
                    check_active()
                yield event(
                    {
                        "type": "attachment_context_ready",
                        "status": "ready",
                        "request_id": req.request_id,
                        "ai_message_id": ids["ai"],
                    }
                )
            if active_context.omitted_history:
                yield event({"type": "context_compacting"})
                schedule_chat_summary(db, session_id=session_pk, model_id=model_id)
                if has_attachment_context:
                    # The independent summary worker owns historical compaction.
                    # Do not let a synchronous summary outlive this turn's deadline.
                    raise ApiError(
                        status_code=503,
                        code="CHAT_CONTEXT_NOT_READY",
                        message="较早的对话正在后台整理，请稍后重试；问题与附件已保留",
                        retryable=True,
                    )
                # Reuse the durable worker's lease and version checks. One bounded
                # attempt avoids silently dropping unprocessed older turns.
                run_one_summary_job(
                    context_session_factory, target_session_id=session_pk, force=True
                )
                db.expire_all()
                context_session = db.get(ChatSession, session_pk)
                if context_session is None:
                    raise ApiError(
                        status_code=409,
                        code="CHAT_REQUEST_CANCELLED",
                        message="本次生成已停止或会话已删除",
                        retryable=True,
                    )
                active_context = assemble_chat_context(db, session=context_session, **context_args)
                db.commit()
                if active_context.omitted_history:
                    raise ApiError(
                        status_code=503,
                        code="CHAT_CONTEXT_NOT_READY",
                        message="较早的对话尚未整理完成，请稍后重试；聊天记录已保留",
                        retryable=True,
                    )
                if not refresh_generation_lease(
                    db,
                    user_id=user_id,
                    request_id=req.request_id,
                    generation_token=generation_token,
                ):
                    raise ApiError(
                        status_code=409,
                        code="CHAT_REQUEST_CANCELLED",
                        message="本次生成已停止",
                        retryable=True,
                    )
                yield event({"type": "context_ready"})
            private_context = has_attachment_context or bool(
                getattr(active_context, "attachment_derived", False)
            )
            explicit_search = bool(
                re.search(
                    r"联网|上网|搜索|查找公开|查阅公开|\b(?:search|browse|look up)\b",
                    model_user_input,
                    re.I,
                )
            )
            for payload in iter_web_search(
                web_mode="off" if private_context and not explicit_search else req.web_mode,
                model_id=model_id,
                user_input=model_user_input,
                context_messages=[] if private_context else active_context.messages,
                request_id=req.request_id,
                user_id=user_id,
                check_active=check_active,
                reserve_search=reserve_search,
            ):
                check_active()
                if "web" in payload:
                    web = deepcopy(payload["web"])
                    persist_web()
                # Evidence fitting may shorten sources. Publish their candidate
                # snapshot only once it matches the payload sent to the model.
                if payload["type"] != "web_sources":
                    yield web_event(payload)
            if req.kind == "qa":
                previous_warnings = len(web.get("warnings", []))
                active_context, web = apply_web_context(active_context, web, model_id)
                if attachment_evidence:
                    web["sources"] = [*web.get("sources", []), *attachment_evidence.sources]
                persist_web()
                for warning in web.get("warnings", [])[previous_warnings:]:
                    yield web_event({"type": "web_warning", "warning": warning, "web": web})
            check_active()
            if getattr(active_context, "attachment_derived", False):
                if not refresh_generation_lease(
                    db,
                    user_id=user_id,
                    request_id=req.request_id,
                    generation_token=generation_token,
                    attachment_derived=True,
                ):
                    check_active()
            yield web_event({"type": "web_status", "status": web["status"], "web": web})
            yield web_event({"type": "web_sources", "web": web, "final": False})
            input_tokens = active_context.input_tokens

            def start_answer(control):
                return chat_stream(
                    messages=active_context.history,
                    node_label=node_label,
                    node_sub=node_sub,
                    user_input=model_user_input,
                    mode=req.mode,
                    ai_style=req.ai_style,
                    kind=req.kind,
                    memories=active_context.memories,
                    model_id=model_id,
                    prepared_messages=active_context.messages,
                    on_stream=control.attach,
                    **(
                        {"timeout": max(0.1, deadline - monotonic())}
                        if has_attachment_context
                        else {}
                    ),
                    on_usage=lambda value: usage.record(value, estimated_input=input_tokens),
                )

            last_guard = perf_counter()

            def check_answer_active():
                nonlocal last_guard
                now = perf_counter()
                if now - last_guard >= 0.2:
                    check_active()
                    last_guard = now

            stream = cancellable_chat_stream(
                start_answer,
                check_answer_active,
                **(
                    {"timeout_seconds": max(0.1, deadline - monotonic())}
                    if has_attachment_context
                    else {}
                ),
            )
            for chunk in stream:
                full_text.append(chunk)
                now = perf_counter()
                if first_chunk or now - checkpoint >= 0.5:
                    if not refresh_generation_lease(
                        db,
                        user_id=user_id,
                        request_id=req.request_id,
                        generation_token=generation_token,
                        content="".join(full_text),
                        web=web,
                    ):
                        raise ApiError(
                            status_code=409,
                            code="CHAT_REQUEST_CANCELLED",
                            message="本次生成已停止或会话内容已改变",
                            retryable=True,
                        )
                    checkpoint = now
                if first_chunk:
                    log.info(
                        "chat_first_token request=%s latency_ms=%d",
                        req.request_id,
                        round((now - began) * 1000),
                    )
                    first_chunk = False
                yield event({"text": chunk})
            content = "".join(full_text)
            if not content.strip():
                raise ApiError(
                    status_code=502,
                    code="AI_EMPTY_RESPONSE",
                    message="模型未返回可用回答，请重新生成",
                    retryable=True,
                )
            invalid_citations = invalid_source_ids(content, web.get("sources", []))
            if invalid_citations:
                warning = {
                    "code": "WEB_CITATION_INVALID",
                    "message": "部分引用没有对应的检索来源，已禁用这些引用链接。",
                    "retryable": False,
                }
                web.setdefault("warnings", []).append(warning)
                web.setdefault("metrics", {})["invalid_citations"] = len(invalid_citations)
                yield web_event({"type": "web_warning", "warning": warning, "web": web})
            saved = finish_chat_turn(
                db,
                user_id=user_id,
                request_id=req.request_id,
                generation_token=generation_token,
                content=content,
                status="complete",
                web=web,
                usage=usage.finish(),
            )
            if not saved:
                raise ApiError(
                    status_code=409,
                    code="CHAT_REQUEST_CANCELLED",
                    message="本次生成已停止或会话内容已改变",
                    retryable=True,
                )
            terminal = True
            web["cited_source_ids"] = cited_source_ids(content, web.get("sources", []))
            policy = get_context_policy(model_id)
            if (
                active_context.summary_needed
                or input_tokens
                + count_messages([{"role": "assistant", "content": content}], model_id)
                >= policy.summary_trigger_tokens
            ):
                try:
                    schedule_chat_summary(db, session_id=session_pk, model_id=model_id)
                except Exception as error:
                    db.rollback()
                    log.warning(
                        "chat_summary_schedule_failed session=%s error_type=%s",
                        session_pk,
                        type(error).__name__,
                    )
            yield web_event({"type": "web_sources", "web": web, "final": True})
            yield event({"request_state": {"status": "complete"}})
            yield "data: [DONE]\n\n"
        except GeneratorExit:
            finish_chat_turn(
                db,
                user_id=user_id,
                request_id=req.request_id,
                generation_token=generation_token,
                content="".join(full_text),
                status="interrupted",
                error_code="CLIENT_DISCONNECTED",
                web=web,
                usage=usage.finish(),
            )
            checkpoint_interrupted_content(
                db,
                user_id=user_id,
                request_id=req.request_id,
                generation_token=generation_token,
                content="".join(full_text),
                usage=usage.finish(),
            )
            raise
        except Exception as error:
            failure = classify_chat_error(error)
            code, message, retryable = failure.code, failure.message, failure.retryable
            incomplete = code in {"AI_OUTPUT_LIMIT", "AI_STREAM_INCOMPLETE", "AI_TIMEOUT"}
            log.warning(
                "chat_stream_failed request=%s code=%s error_type=%s",
                req.request_id,
                code,
                type(error).__name__,
            )
            finish_chat_turn(
                db,
                user_id=user_id,
                request_id=req.request_id,
                generation_token=generation_token,
                content="".join(full_text),
                status="interrupted" if incomplete else "failed",
                error_code=code,
                web=web,
                usage=usage.finish(),
            )
            checkpoint_interrupted_content(
                db,
                user_id=user_id,
                request_id=req.request_id,
                generation_token=generation_token,
                content="".join(full_text),
                usage=usage.finish(),
            )
            current_turn = get_chat_turn(db, user_id=user_id, request_id=req.request_id)
            status = (
                "interrupted"
                if current_turn is None or current_turn.status in {"interrupted", "deleted"}
                else "failed"
            )
            saved_message = (
                db.query(ChatMessage)
                .filter_by(id=ids["ai"], user_id=user_id)
                .populate_existing()
                .one_or_none()
            )
            saved_web = (
                deepcopy((saved_message.metadata_json or {}).get("web")) if saved_message else None
            )
            db.commit()
            if saved_web is not None:
                yield web_event({"type": "web_sources", "web": saved_web, "final": True})
            yield event({"request_state": {"status": status}})
            yield event({"error": {"code": code, "message": message, "retryable": retryable}})
            yield "data: [DONE]\n\n"
        finally:
            usage.finish()
            close = getattr(stream, "close", None)
            if close:
                close()
            if not terminal:
                db.rollback()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class CancelChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)


@router.post("/cancel")
def cancel_chat_endpoint(
    req: CancelChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    turn = cancel_chat_turn(
        db, user_id=current_user.id, session_id=req.session_id, request_id=req.request_id
    )
    reported = turn_usage(db, turn) if turn else None
    return {
        "status": turn.status if turn else "interrupted",
        **({"usage": reported} if reported is not None else {}),
        **(
            {"msg_ids": {"user": turn.user_message_id, "ai": turn.ai_message_id}}
            if turn and turn.user_message_id and turn.ai_message_id
            else {}
        ),
    }


@router.get("/requests/{request_id}")
def chat_request_state(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    turn = recover_chat_turn(db, user_id=current_user.id, request_id=request_id)
    session = db.get(ChatSession, turn.chat_session_id)
    return {
        "request_id": turn.request_id,
        "session_id": session.session_id,
        "status": turn.status,
        "preparation": turn.preparation_json,
        "error_code": turn.error_code,
        "error": error_description(turn.error_code) if turn.error_code else None,
        "usage": turn_usage(db, turn),
        "msg_ids": {"user": turn.user_message_id, "ai": turn.ai_message_id},
    }


@router.get("/history/{node_key}", response_model=List[HistoryResponse])
def get_history(
    node_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取指定节点的对话历史，按消息 ID 升序排列，最多返回 50 条。"""
    messages = (
        visible_messages(db.query(ChatMessage))
        .filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.node_key == node_key,
        )
        .order_by(ChatMessage.id)
        .limit(50)
        .all()
    )
    return history_responses(db, messages)


@router.get("/messages", response_model=List[HistoryResponse])
def get_all_messages(
    limit: int = 200,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页获取当前用户的全部消息，按 ID 倒序。"""
    messages = (
        visible_messages(db.query(ChatMessage))
        .filter(
            ChatMessage.user_id == current_user.id,
        )
        .order_by(ChatMessage.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return history_responses(db, messages)


class DeleteMessagesRequest(BaseModel):
    ids: List[int]


@router.delete("/messages")
def delete_messages_endpoint(
    req: DeleteMessagesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量删除指定 ID 的消息，过滤 user_id 确保只能删除自己的消息。"""
    if not req.ids:
        return {"deleted": 0}
    deleted = archive_and_delete_messages(db, user_id=current_user.id, ids=req.ids)
    db.commit()
    return {"deleted": deleted}


class DeleteSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)

    @field_validator("session_id")
    @classmethod
    def strip_session_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("session_id must not be blank")
        return value


@router.post("/avatar")
async def upload_chat_avatar(
    session_id: str = Form(min_length=1, max_length=100),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(status_code=422, detail="会话 ID 不能为空")
    if not rate_limit.hit(f"chat-avatar:{current_user.id}", max_calls=30, window_seconds=3600):
        raise HTTPException(status_code=429, detail="头像上传过于频繁，请稍后再试")
    suffix, data = await read_avatar_upload(file)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{_chat_avatar_prefix(current_user.id, session_id)}{uuid.uuid4().hex}{suffix}"
    (UPLOAD_DIR / filename).write_bytes(data)
    _delete_chat_avatar_files(current_user.id, session_id, except_name=filename)
    return {"avatar_url": f"/static/avatars/{filename}"}


@router.delete("/avatar")
def delete_chat_avatar(
    req: DeleteSessionRequest,
    current_user: User = Depends(get_current_user),
):
    return {"deleted": _delete_chat_avatar_files(current_user.id, req.session_id)}


@router.delete("/session")
def delete_session_endpoint(
    req: DeleteSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按稳定的 session_id 删除当前用户的完整会话。"""
    deleted = archive_and_delete_messages(db, user_id=current_user.id, session_id=req.session_id)
    delete_agent_runs(db, user_id=current_user.id, session_id=req.session_id)
    db.commit()
    _delete_chat_avatar_files(current_user.id, req.session_id)
    return {"deleted": deleted}


def _suggestion_history(
    db: Session,
    *,
    user_id: int,
    session_id: str | None,
    mode: str,
    topic_id: int | None = None,
) -> list[dict[str, str]]:
    """复用会话索引，限制推荐上下文的消息数量和单条长度。"""
    if not session_id:
        return []
    query = db.query(ChatMessage).filter(
        ChatMessage.user_id == user_id,
        ChatMessage.session_id == session_id,
        ChatMessage.mode == mode,
        ChatMessage.message_type == "chat",
    )
    if mode == "socratic":
        query = query.filter(ChatMessage.topic_id == topic_id)
    recent_messages = query.order_by(ChatMessage.id.desc()).limit(6).all()
    return [
        {"角色": message.role, "内容": message.content[-800:]}
        for message in reversed(recent_messages)
        if message.content.strip()
        and (message.metadata_json or {}).get("status", "complete") == "complete"
    ]


@router.get("/suggestions")
def get_suggestions(
    mode: Literal["socratic", "normal"] = "socratic",
    model: str | None = None,
    exclude: list[str] = Query(default=[]),
    topic_id: int | None = Query(default=None, gt=0),
    session_id: str | None = Query(default=None, min_length=1, max_length=100),
    node_key: str | None = Query(default=None, min_length=1, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新对话推荐开场主题，已有内容的对话根据当前会话生成后续建议。"""
    load_user_profiles(db, current_user.id)
    subject = ""
    normal_history = []
    if mode == "socratic":
        if topic_id is None:
            topics = (
                db.query(Topic.title)
                .filter(Topic.user_id == current_user.id)
                .order_by(Topic.id.desc())
                .limit(12)
                .all()
            )
            context = {"已有学习主题": [title for (title,) in topics]}
        else:
            topic = (
                db.query(Topic)
                .filter(Topic.id == topic_id, Topic.user_id == current_user.id)
                .first()
            )
            if not topic:
                raise HTTPException(status_code=404, detail="主题不存在")
            subject = topic.title
            context = {"当前主题": topic.title}
            if node_key:
                node = (
                    db.query(Node)
                    .filter(Node.topic_id == topic_id, Node.node_key == node_key)
                    .first()
                )
                if not node:
                    raise HTTPException(status_code=404, detail="当前主题中不存在该节点")
                subject = node.label
                context["当前节点"] = {"名称": node.label, "说明": node.sub}
            if session_id:
                context["最近对话"] = _suggestion_history(
                    db,
                    user_id=current_user.id,
                    session_id=session_id,
                    mode=mode,
                    topic_id=topic_id,
                )
        prompt = build_socratic_suggestions_prompt(
            json.dumps(context, ensure_ascii=False), has_topic=topic_id is not None
        )
    else:
        normal_history = _suggestion_history(
            db, user_id=current_user.id, session_id=session_id, mode=mode
        )
        prompt = build_normal_suggestions_prompt(
            json.dumps({"最近对话": normal_history}, ensure_ascii=False) if normal_history else None
        )

    excluded = list(dict.fromkeys(value.strip()[:80] for value in exclude if value.strip()))[:24]
    if excluded:
        prompt += f"\n以下建议已经展示过，请不要重复：{json.dumps(excluded, ensure_ascii=False)}"

    profile = resolve_llm_profile(selected_model(model, current_user.id))
    try:
        response = get_ai_client(profile.id).chat.completions.create(
            model=profile.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.8,
        )
        payload = json.loads(extract_json_from_markdown(response.choices[0].message.content))
        suggestions = payload.get("suggestions") if isinstance(payload, dict) else None
        if not isinstance(suggestions, list) or not all(
            isinstance(value, str) for value in suggestions
        ):
            raise ValueError("invalid suggestions response")
        fresh = list(dict.fromkeys(value.strip() for value in suggestions if value.strip()))
        if not fresh:
            raise ValueError("empty suggestions response")
        return {
            "suggestions": [value for value in fresh if value not in excluded][:12],
            "source": "ai",
        }
    except Exception:
        if mode == "socratic":
            if topic_id is not None:
                return {
                    "suggestions": [
                        value
                        for value in [
                            f"{subject}的核心原理是什么？",
                            f"{subject}有什么实际用途？",
                            f"{subject}能举个例子吗？",
                            f"{subject}有哪些常见误区？",
                            f"{subject}与相关概念有何区别？",
                            f"{subject}如何一步步实现？",
                            "刚才的例子为什么成立？",
                            "这个结论需要哪些前提？",
                            "换个场景还适用吗？",
                            "这一步可以再解释一下吗？",
                            "有没有反例能帮助理解？",
                            "如何检验我是否理解了？",
                        ]
                        if value not in excluded
                    ],
                    "source": "fallback",
                }
            return {
                "suggestions": [
                    "我想学 Python",
                    "教我机器学习",
                    "讲讲数据结构",
                    "学习 Web 开发",
                    "学习算法基础",
                    "学习编程基础",
                    "学习逻辑思维",
                    "了解神经网络",
                    "学习数据库",
                    "学习前端基础",
                    "学习操作系统",
                    "学习计算机网络",
                ],
                "source": "fallback",
            }
        else:
            if normal_history:
                return {
                    "suggestions": [
                        value
                        for value in [
                            "能展开说说刚才的内容吗？",
                            "能结合我的情况举个例子吗？",
                            "我接下来可以先做什么？",
                            "有没有更简单的选择？",
                            "刚才提到的方法怎么操作？",
                            "这有哪些需要注意的地方？",
                            "还有哪些相关细节值得了解？",
                            "如果换个情况该怎么办？",
                            "这几种选择有什么区别？",
                            "能帮我梳理一下刚才的重点吗？",
                            "这个建议为什么适合我？",
                            "有没有其他可行的思路？",
                        ]
                        if value not in excluded
                    ],
                    "source": "fallback",
                }
            return {
                "suggestions": [
                    "今天天气怎么样",
                    "推荐一部电影",
                    "给我讲个笑话",
                    "聊聊最近的新闻",
                    "推荐一本书",
                    "分享一个冷知识",
                    "有什么旅行建议",
                    "聊聊音乐",
                    "推荐一道菜",
                    "讲个有趣的故事",
                    "如何安排周末",
                    "聊聊科技趋势",
                ],
                "source": "fallback",
            }
