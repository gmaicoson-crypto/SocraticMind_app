import json
from dataclasses import dataclass, field
from typing import Any, Iterator
from itertools import islice

from services.attachments.evidence import hydrate_message_sources

from sqlalchemy import case, or_, exists
from sqlalchemy.orm import Session, aliased

from ai.agent import build_chat_messages
from core.context_budget import count_messages, ensure_fits, get_context_policy
from models import AgentRun, ChatMessage, ChatSession, ChatTurn, Node, StudyPlan, Topic
from services.memories import select_relevant_memories
from services.attachments.context import PreparedAttachments
from models.attachment import Attachment, MessageAttachment
from services.web_evidence import (
    compact_web_references,
    historical_source_note,
    hydrate_summary_web_sources,
    message_web_sources,
)


@dataclass
class HistoryBlock:
    turn_id: int | None
    node_key: str
    message_ids: list[int]
    messages: list[dict[str, str]]
    web_references: list[dict] = field(default_factory=list)
    attachment_derived: bool = False


@dataclass
class PreparedChatContext:
    messages: list[dict[str, str]]
    history: list[dict[str, str]]
    memories: list[dict[str, str]]
    input_tokens: int
    summary_needed: bool
    omitted_history: bool
    attachment_derived: bool = False


def valid_summary(session: ChatSession) -> bool:
    return bool(session.summary_json and session.summary_source_version == session.content_version)


def _validated_sources_in_batches(db, session, rows, message_at):
    iterator = iter(rows)
    while batch := list(islice(iterator, 64)):
        messages = [message_at(row) for row in batch]
        valid = hydrate_message_sources(db, user_id=session.user_id, messages=messages)
        for row, message in zip(batch, messages):
            yield row, message_web_sources(message, sources=valid.get(message.id, []))


def iter_history_blocks(
    db: Session,
    session: ChatSession,
    *,
    before_user_message_id: int | None = None,
    after_turn_id: int | None = None,
    include_interrupted: bool = False,
    newest_first: bool = True,
) -> Iterator[HistoryBlock]:
    """Read complete turns in bounded database batches, preserving question/answer pairs."""
    attachment_notes = {}
    for message_id, attachment in (
        db.query(MessageAttachment.user_message_id, Attachment)
        .join(Attachment, Attachment.id == MessageAttachment.attachment_id)
        .filter(
            Attachment.user_id == session.user_id,
            Attachment.session_id == session.session_id,
            Attachment.topic_id == session.topic_id,
            Attachment.mode == session.mode,
            Attachment.status == "ready",
        )
        .order_by(MessageAttachment.position)
    ):
        attachment_notes.setdefault(message_id, []).append(
            {
                "id": attachment.id,
                "name": attachment.name,
                "kind": attachment.kind,
                "revision": attachment.revision,
            }
        )
    user_message = aliased(ChatMessage)
    ai_message = aliased(ChatMessage)
    statuses = ["complete", "interrupted"] if include_interrupted else ["complete"]
    query = (
        db.query(ChatTurn, user_message, ai_message)
        .join(user_message, ChatTurn.user_message_id == user_message.id)
        .join(ai_message, ChatTurn.ai_message_id == ai_message.id)
        .filter(
            ChatTurn.chat_session_id == session.id,
            ChatTurn.user_id == session.user_id,
            ChatTurn.status.in_(statuses),
            user_message.user_id == session.user_id,
            ai_message.user_id == session.user_id,
            user_message.session_id == session.session_id,
            ai_message.session_id == session.session_id,
            user_message.topic_id == session.topic_id,
            ai_message.topic_id == session.topic_id,
            user_message.mode == session.mode,
            ai_message.mode == session.mode,
            user_message.message_type == "chat",
            ai_message.message_type == "chat",
        )
    )
    if before_user_message_id is not None:
        query = query.filter(user_message.id < before_user_message_id)
    if after_turn_id is not None:
        cursor = (
            db.query(ChatTurn.user_message_id)
            .filter(
                ChatTurn.id == after_turn_id,
                ChatTurn.chat_session_id == session.id,
            )
            .scalar()
        )
        if cursor is not None:
            query = query.filter(user_message.id > cursor)
    order = user_message.id.desc() if newest_first else user_message.id.asc()
    for (turn, user, ai), sources in _validated_sources_in_batches(
        db, session, query.order_by(order).yield_per(64), lambda row: row[2]
    ):
        if not ai.content or (ai.metadata_json or {}).get("status") == "superseded":
            continue
        if turn.status == "interrupted" and turn.regenerate_message_id is not None:
            continue
        content = ai.content + historical_source_note(sources)
        if turn.status == "interrupted":
            content = "[以下为生成中断前已显示的部分回答，尚未完成]\n" + content
        messages = []
        user_content = user.content
        if user.id in attachment_notes:
            default = (
                "结合当前节点，从资料中提出一个引导问题"
                if session.mode == "socratic"
                else "概括资料并提示可以继续提问"
            )
            user_content += "\n附件目录：" + json.dumps(
                attachment_notes[user.id], ensure_ascii=False
            )
            if not user.content:
                user_content += "\n用户仅上传附件，服务端默认处理意图：" + default
        if user_content:
            messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": content})
        yield HistoryBlock(
            turn.id,
            turn.node_key,
            [user.id, ai.id],
            messages,
            compact_web_references(sources),
            user.id in attachment_notes
            or bool((ai.metadata_json or {}).get("attachment_derived"))
            or any(source.get("kind") in {"document", "image"} for source in sources),
        )

    # Development databases may already have raw messages. They remain searchable
    # without accepting a client history field or inventing successful turns.
    managed = exists().where(
        (ChatTurn.user_message_id == ChatMessage.id) | (ChatTurn.ai_message_id == ChatMessage.id)
    )
    legacy = db.query(ChatMessage).filter(
        ChatMessage.user_id == session.user_id,
        ChatMessage.session_id == session.session_id,
        ChatMessage.topic_id == session.topic_id,
        ChatMessage.mode == session.mode,
        ChatMessage.message_type == "chat",
        ~managed,
        or_(
            ChatMessage.metadata_json.is_(None),
            ChatMessage.metadata_json["status"].as_string() == "complete",
        ),
    )
    if before_user_message_id is not None:
        legacy = legacy.filter(ChatMessage.id < before_user_message_id)
    order = ChatMessage.id.desc() if newest_first else ChatMessage.id.asc()
    for message, sources in _validated_sources_in_batches(
        db, session, legacy.order_by(order).yield_per(64), lambda row: row
    ):
        if message.role not in {"user", "ai"} or not message.content:
            continue
        yield HistoryBlock(
            None,
            message.node_key,
            [message.id],
            [
                {
                    "role": "assistant" if message.role == "ai" else "user",
                    "content": message.content + historical_source_note(sources),
                }
            ],
            compact_web_references(sources),
            bool((message.metadata_json or {}).get("attachment_derived"))
            or any(source.get("kind") in {"document", "image"} for source in sources),
        )


def topic_context_notes(db: Session, session: ChatSession, *, node_key: str) -> list[str]:
    if session.mode != "socratic" or session.topic_id is None:
        return []
    topic = (
        db.query(Topic)
        .filter(Topic.id == session.topic_id, Topic.user_id == session.user_id)
        .first()
    )
    node = (
        db.query(Node).filter(Node.topic_id == session.topic_id, Node.node_key == node_key).first()
    )
    plan = (
        db.query(StudyPlan)
        .filter(
            StudyPlan.topic_id == session.topic_id,
            StudyPlan.user_id == session.user_id,
            StudyPlan.status == "active",
        )
        .first()
    )
    state = {"topic": topic.title if topic else ""}
    if node:
        state["current_node"] = {
            "name": node.label,
            "state": node.state,
            "mastery_source": node.mastery_source,
        }
    if plan:
        state["plan"] = {
            "goal": plan.goal,
            "daily_minutes": plan.daily_minutes,
            "version": plan.version,
        }
    notes = ["服务端当前学习状态（优先于旧摘要中的进度）：" + json.dumps(state, ensure_ascii=False)]
    related_keys = {node_key}
    if node:
        related_keys.update(
            key.strip() for key in (node.parent_keys or "").split(",") if key.strip()
        )
    relevant_turn = exists().where(
        ChatTurn.chat_session_id == ChatSession.id,
        ChatTurn.node_key.in_(related_keys),
        ChatTurn.status == "complete",
    )
    exact_turn = exists().where(
        ChatTurn.chat_session_id == ChatSession.id,
        ChatTurn.node_key == node_key,
        ChatTurn.status == "complete",
    )
    candidates = (
        db.query(ChatSession)
        .filter(
            ChatSession.user_id == session.user_id,
            ChatSession.topic_id == session.topic_id,
            ChatSession.mode == "socratic",
            ChatSession.id != session.id,
            ChatSession.summary_json.is_not(None),
            ChatSession.summary_source_version == ChatSession.content_version,
            relevant_turn,
        )
        .order_by(
            case((exact_turn, 0), else_=1), ChatSession.updated_at.desc(), ChatSession.id.desc()
        )
        .limit(12)
        .all()
    )
    for candidate in candidates:
        raw_summary = candidate.summary_json or {}
        # This provenance flag is computed by the server and propagated even
        # when the model omits source markers in a later derived conclusion.
        if raw_summary.get("attachment_derived"):
            continue
        summary = hydrate_summary_web_sources(db, candidate, candidate.summary_json or {})
        if any(
            source.get("kind") in {"document", "image"} for source in summary.get("web_sources", [])
        ):
            continue
        if not related_keys.intersection(summary.get("node_keys", [])):
            continue
        notes.append(
            "同主题其他会话的相关讨论摘要（不是当前会话，也不作为掌握证据）："
            + json.dumps(summary, ensure_ascii=False)
        )
        if len(notes) >= 4:
            break
    return notes


def assemble_chat_context(
    db: Session,
    *,
    session: ChatSession,
    user_message_id: int,
    model_id: str,
    node_key: str,
    node_label: str,
    node_sub: str,
    user_input: str,
    mode: str,
    ai_style: str,
    kind: str,
    regenerate: bool = False,
    quote_source: ChatMessage | None = None,
    attachments: PreparedAttachments | None = None,
) -> PreparedChatContext:
    policy = get_context_policy(model_id)
    attachments = attachments or PreparedAttachments()
    if not user_input.strip() and attachments.attachment_derived and kind == "qa":
        user_input = (
            "结合当前节点，从资料中提出一个引导问题"
            if mode == "socratic"
            else "概括资料并提示可以继续提问"
        )
    prompt_args = dict(
        node_label=node_label,
        node_sub=node_sub,
        user_input=user_input,
        mode=mode,
        ai_style=ai_style,
        kind=kind,
        image_parts=attachments.image_parts,
    )
    required_notes = list(attachments.context_notes)
    quote_derived = False
    if quote_source:
        quote_sources = (
            message_web_sources(
                quote_source,
                sources=hydrate_message_sources(
                    db, user_id=session.user_id, messages=[quote_source]
                ).get(quote_source.id, []),
            )
            if (
                quote_source.user_id == session.user_id
                and quote_source.session_id == session.session_id
                and quote_source.topic_id == session.topic_id
                and quote_source.mode == session.mode
            )
            else []
        )
        quote_derived = bool((quote_source.metadata_json or {}).get("attachment_derived")) or any(
            source.get("kind") in {"document", "image"} for source in quote_sources
        )
        required_notes.append(
            f"用户明确引用的消息原文（消息 {quote_source.id}）：\n{quote_source.content}"
            + historical_source_note(quote_sources)
        )
    topic_notes = topic_context_notes(db, session, node_key=node_key) if kind == "qa" else []
    if topic_notes:
        required_notes.append(topic_notes[0])
    base = build_chat_messages(messages=[], context_notes=required_notes, **prompt_args)
    ensure_fits(base, model_id)
    if kind != "qa":
        return PreparedChatContext(base, [], [], count_messages(base, model_id), False, False)

    summary = session.summary_json if valid_summary(session) else None
    if summary and regenerate:
        summarized_user_id = (
            db.query(ChatTurn.user_message_id)
            .filter(
                ChatTurn.id == session.summary_through_turn_id,
                ChatTurn.chat_session_id == session.id,
            )
            .scalar()
        )
        # Regenerating the last answer can still reuse a summary covering only
        # earlier questions. Never expose a summary that includes that answer.
        if summarized_user_id is None or summarized_user_id >= user_message_id:
            summary = None
    if summary:
        summary = hydrate_summary_web_sources(db, session, summary)
    summary_notes = (
        ["当前会话较早讨论摘要：" + json.dumps(summary, ensure_ascii=False)] if summary else []
    )
    required = build_chat_messages(
        messages=[], context_notes=required_notes + summary_notes, **prompt_args
    )
    if count_messages(required, model_id) > policy.hard_input_limit:
        # A smaller model must not force us to discard original messages permanently.
        summary = None
        summary_notes = []
        required = base
    remaining = policy.hard_input_limit - count_messages(required, model_id)
    selected = []
    history_cost = 0
    omitted = False
    for block in iter_history_blocks(
        db,
        session,
        before_user_message_id=user_message_id,
        after_turn_id=session.summary_through_turn_id if summary else None,
        include_interrupted=True,
    ):
        if quote_source is not None and quote_source.id in block.message_ids:
            # The required reference already carries the exact original text.
            # Keep its place in the dialogue without spending the budget twice.
            block = HistoryBlock(
                block.turn_id,
                block.node_key,
                block.message_ids,
                [
                    {
                        **message,
                        "content": f"[本条回答原文见用户引用的消息 {quote_source.id}]",
                    }
                    if message["role"] == "assistant"
                    else message
                    for message in block.messages
                ],
                block.web_references,
                block.attachment_derived,
            )
        cost = count_messages(block.messages, model_id) - count_messages([], model_id)
        if cost > remaining:
            if not selected:
                # Never silently remove the immediate answer a follow-up refers to.
                ensure_fits(required[:-1] + block.messages + required[-1:], model_id)
            omitted = True
            break
        selected.append(block)
        remaining -= cost
        history_cost += cost
    selected.reverse()
    history = [message for block in selected for message in block.messages]
    notes = required_notes + summary_notes
    memories = []
    if mode == "socratic":
        # Preserve current dialogue first, then spend the normal budget on background.
        candidates = select_relevant_memories(
            db, user_id=session.user_id, topic_id=session.topic_id
        )
        for memory in candidates:
            entry = {"kind": memory.kind, "content": memory.content}
            proposed = build_chat_messages(
                messages=history, memories=memories + [entry], context_notes=notes, **prompt_args
            )
            if count_messages(proposed, model_id) <= policy.target_input_tokens:
                memories.append(entry)
        for note in topic_notes[1:]:
            proposed = build_chat_messages(
                messages=history, memories=memories, context_notes=notes + [note], **prompt_args
            )
            if count_messages(proposed, model_id) <= policy.target_input_tokens:
                notes.append(note)
    prepared = build_chat_messages(
        messages=history, memories=memories, context_notes=notes, **prompt_args
    )
    tokens = ensure_fits(prepared, model_id)
    return PreparedChatContext(
        prepared,
        history,
        memories,
        tokens,
        omitted
        or history_cost >= policy.summary_trigger_tokens
        or tokens >= policy.summary_trigger_tokens,
        omitted,
        attachments.attachment_derived
        or quote_derived
        or any(block.attachment_derived for block in selected)
        or bool((summary or {}).get("attachment_derived")),
    )


def sync_agent_run_message(
    db: Session,
    *,
    run: AgentRun,
    payload: dict[str, Any],
    answer: dict[str, Any] | None = None,
) -> None:
    if not run.session_id:
        return

    messages: list[ChatMessage] = []
    node_key = (run.state_json or {}).get("params", {}).get("node_key", "")
    if answer is not None:
        messages.append(
            ChatMessage(
                user_id=run.user_id,
                topic_id=run.topic_id,
                session_id=run.session_id,
                node_key=node_key,
                role="user",
                content=answer["answer"],
                mode="socratic",
                message_type="agent_answer",
                metadata_json={
                    "run_id": run.id,
                    "step_id": answer["step_id"],
                    "submitted_version": answer["version"],
                },
            )
        )

    step = payload.get("step")
    preview = payload.get("preview")
    result = payload.get("result")
    error = payload.get("error")
    if step:
        message_type = "agent_step"
        content = step["prompt"]
        detail = {"step": step}
    elif preview and payload["status"] == "awaiting_confirmation":
        message_type = "plan_preview"
        content = "学习计划预览已生成"
        detail = {"preview": preview}
    elif result and payload["type"] == "assessment":
        message_type = "assessment_result"
        content = "节点评估已完成"
        detail = {"result": result}
    elif result:
        message_type = "agent_result"
        content = "学习计划已创建"
        detail = {"result": result}
    elif payload["status"] in {"failed", "cancelled"}:
        message_type = "agent_status"
        content = "流程执行失败" if payload["status"] == "failed" else "流程已取消"
        detail = {"error": error}
    else:
        message_type = ""
        content = ""
        detail = {}

    if message_type:
        duplicate = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.user_id == run.user_id,
                ChatMessage.session_id == run.session_id,
                ChatMessage.message_type == message_type,
                ChatMessage.metadata_json["run_id"].as_string() == run.id,
                ChatMessage.metadata_json["version"].as_integer() == run.version,
            )
            .first()
            is not None
        )
        if not duplicate:
            messages.append(
                ChatMessage(
                    user_id=run.user_id,
                    topic_id=run.topic_id,
                    session_id=run.session_id,
                    node_key=node_key,
                    role="ai",
                    content=content,
                    mode="socratic",
                    message_type=message_type,
                    metadata_json={
                        "run_id": run.id,
                        "run_type": run.run_type,
                        "status": run.status,
                        "version": run.version,
                        **detail,
                    },
                )
            )

    if messages:
        db.add_all(messages)
        if answer is not None:
            from services.chat_titles import schedule_title

            schedule_title(
                db,
                user_id=run.user_id,
                session_id=run.session_id,
                mode="socratic",
                source_text=answer["answer"],
                model_id=run.model,
            )
        db.commit()
