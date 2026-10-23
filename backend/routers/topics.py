import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel
from typing import List
from core.database import get_db
from core.deps import get_current_user
from core.ai_client import get_ai_client, resolve_llm_profile, resolve_model_id
from core.errors import ApiError
from core.user_llm import load_user_profiles
from models.user import User
from models.topic import Topic
from models.node import Node
from services.progress_archive import (
    archive_and_delete_messages,
    archive_topic_mastery,
    delete_agent_runs,
)
from ai.prompts import RECOMMEND_TOPICS_PROMPT, build_recommend_prompt
from ai.util import extract_json_from_markdown

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/topics", tags=["主题"])


class TopicResponse(BaseModel):
    id: int
    title: str
    emoji: str
    total_nodes: int
    mastered_nodes: int

    class Config:
        from_attributes = True


class CreateTopicRequest(BaseModel):
    title: str
    emoji: str = "📚"


class GenerateTopicRequest(BaseModel):
    title: str
    emoji: str = "📚"


def _topic_to_response(t: Topic, nodes: list[Node]) -> TopicResponse:
    """将 Topic ORM 对象转换为 API 响应格式，同时计算节点总数和已掌握节点数。"""
    return TopicResponse(
        id=t.id,
        title=t.title,
        emoji=t.emoji,
        total_nodes=len(nodes),
        mastered_nodes=sum(1 for n in nodes if n.state == "mastered"),
    )


@router.get("", response_model=List[TopicResponse])
def get_topics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # selectinload 一次性预取所有 topic 的 nodes，避免循环中的 N+1 查询
    topics = (
        db.query(Topic)
        .options(selectinload(Topic.nodes))
        .filter(Topic.user_id == current_user.id)
        .all()
    )
    return [_topic_to_response(t, t.nodes) for t in topics]


@router.post("/generate", response_model=TopicResponse, deprecated=True)
def generate_topic(
    req: GenerateTopicRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """旧客户端兼容入口；新主题必须通过 Learning Agent onboarding 创建。"""
    raise ApiError(
        status_code=409,
        code="ONBOARDING_REQUIRED",
        message="请通过新主题引导流程创建学习主题",
        retryable=False,
    )


@router.delete("/{topic_id}")
def delete_topic(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    topic = (
        db.query(Topic)
        .filter(
            Topic.id == topic_id,
            Topic.user_id == current_user.id,
        )
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="主题不存在")

    deleted_messages = archive_and_delete_messages(db, user_id=current_user.id, topic_id=topic.id)
    archive_topic_mastery(db, user_id=current_user.id, topic_id=topic.id, title=topic.title)
    delete_agent_runs(db, user_id=current_user.id, topic_id=topic.id)
    db.delete(topic)
    db.commit()
    return {"message": "删除成功", "deleted_messages": deleted_messages}


class UpdateTopicRequest(BaseModel):
    title: str


@router.patch("/{topic_id}")
def update_topic_title(
    topic_id: int,
    req: UpdateTopicRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    topic = (
        db.query(Topic)
        .filter(
            Topic.id == topic_id,
            Topic.user_id == current_user.id,
        )
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="主题不存在")
    topic.title = req.title
    db.commit()
    db.refresh(topic)
    return _topic_to_response(topic, list(topic.nodes))


@router.get("/recommend")
def recommend_topics(
    model: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """根据用户已有主题推荐下一步学习方向；无主题时推荐热门入门主题。

    AI 调用失败时不阻塞首页加载，返回空列表即可，前端做降级处理。
    """
    topics = db.query(Topic).filter(Topic.user_id == current_user.id).all()
    load_user_profiles(db, current_user.id)

    if topics:
        prompt = build_recommend_prompt([t.title for t in topics])
    else:
        prompt = "该用户还没有学习任何主题，请推荐 3 个适合初学者的热门技术学习主题。"

    try:
        profile = resolve_llm_profile(resolve_model_id(model, user_id=current_user.id))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        response = get_ai_client(profile.id).chat.completions.create(
            model=profile.model,
            messages=[
                {"role": "system", "content": RECOMMEND_TOPICS_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )
        return json.loads(extract_json_from_markdown(response.choices[0].message.content))
    except Exception as e:
        log.warning("recommend_topics 调用失败: %s", e)
        return {"recommendations": []}
