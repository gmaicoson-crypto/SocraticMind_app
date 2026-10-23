from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import String, func
from datetime import date, timedelta
from core.database import get_db
from core.deps import get_current_user
from models.user import User
from models.node import Node
from models.topic import Topic
from models.progress import LearningRecord, ChatMessage
from models.progress_archive import ArchivedChatActivity, ArchivedMastery

router = APIRouter(prefix="/api/progress", tags=["进度"])


def today_str() -> str:
    return date.today().isoformat()


def _compute_streak(learned_dates: set[str]) -> int:
    """计算连续学习天数：从今天往前数，今天没记录则从昨天开始数。"""
    streak = 0
    check = date.today()
    while check.isoformat() in learned_dates:
        streak += 1
        check -= timedelta(days=1)
    if streak == 0:
        check = date.today() - timedelta(days=1)
        while check.isoformat() in learned_dates:
            streak += 1
            check -= timedelta(days=1)
    return streak


@router.post("/record")
def record_today(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """记录今日打卡，幂等操作：同一天重复调用不会重复写入。"""
    today = today_str()
    exists = (
        db.query(LearningRecord)
        .filter(
            LearningRecord.user_id == current_user.id,
            LearningRecord.date == today,
        )
        .first()
    )
    if not exists:
        db.add(LearningRecord(user_id=current_user.id, date=today))
        db.commit()
    return {"date": today, "recorded": True}


@router.get("/streak")
def get_streak(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取连续学习天数和最近 14 天的打卡情况。

    streak 计算只取近 60 天记录（连续学习上限远小于此值），total_days 用 count() 统计总天数。
    """
    cutoff = (date.today() - timedelta(days=60)).isoformat()
    recent_records = (
        db.query(LearningRecord.date)
        .filter(
            LearningRecord.user_id == current_user.id,
            LearningRecord.date >= cutoff,
        )
        .all()
    )
    learned_dates = {r.date for r in recent_records}

    total_days = (
        db.query(LearningRecord)
        .filter(
            LearningRecord.user_id == current_user.id,
        )
        .count()
    )

    streak = _compute_streak(learned_dates)

    recent = [
        {
            "date": (date.today() - timedelta(days=i)).isoformat(),
            "learned": (date.today() - timedelta(days=i)).isoformat() in learned_dates,
        }
        for i in range(13, -1, -1)
    ]

    return {
        "streak": streak,
        "total_days": total_days,
        "recent": recent,
    }


@router.get("/stats")
def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取完整的学习统计数据：热力图、streak、本周概览、成就徽章、最近掌握时间线。"""
    today = date.today()
    one_year_ago = today - timedelta(days=364)

    # 苏格拉底模式下用户发出的消息总数（不含 AI 回复）
    live_chat_count = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.role == "user",
            ChatMessage.mode == "socratic",
        )
        .count()
    )
    archived_chat_count = (
        db.query(func.coalesce(func.sum(ArchivedChatActivity.count), 0))
        .filter(ArchivedChatActivity.user_id == current_user.id)
        .scalar()
    )
    chat_count = live_chat_count + archived_chat_count

    # 热力图：单次 GROUP BY 查询替代原先的 365 次独立 COUNT，性能差异显著
    date_expr = func.substr(func.cast(ChatMessage.created_at, String(10)), 1, 10)
    heatmap_rows = (
        db.query(
            date_expr.label("d"),
            func.count().label("c"),
        )
        .filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.role == "user",
            ChatMessage.mode == "socratic",
            ChatMessage.created_at >= one_year_ago,
        )
        .group_by("d")
        .all()
    )
    by_date = {row.d: row.c for row in heatmap_rows}
    archived_heatmap_rows = (
        db.query(ArchivedChatActivity.day, func.sum(ArchivedChatActivity.count))
        .filter(
            ArchivedChatActivity.user_id == current_user.id,
            ArchivedChatActivity.day >= one_year_ago.isoformat(),
        )
        .group_by(ArchivedChatActivity.day)
        .all()
    )
    for day, count in archived_heatmap_rows:
        by_date[day] = by_date.get(day, 0) + count
    heatmap = [
        {
            "date": (today - timedelta(days=i)).isoformat(),
            "count": by_date.get((today - timedelta(days=i)).isoformat(), 0),
        }
        for i in range(364, -1, -1)
    ]

    # streak 和总学习天数
    streak_cutoff = (today - timedelta(days=60)).isoformat()
    recent_records = (
        db.query(LearningRecord.date)
        .filter(
            LearningRecord.user_id == current_user.id,
            LearningRecord.date >= streak_cutoff,
        )
        .all()
    )
    learned_dates = {r.date for r in recent_records}
    streak = _compute_streak(learned_dates)
    total_days_learned = (
        db.query(LearningRecord)
        .filter(
            LearningRecord.user_id == current_user.id,
        )
        .count()
    )

    # 本周统计（从本周一到今天）
    weekday = today.weekday()
    week_start = today - timedelta(days=weekday)
    week_start_str = week_start.isoformat()

    live_week_chats = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.role == "user",
            ChatMessage.mode == "socratic",
            date_expr >= week_start_str,
        )
        .count()
    )
    archived_week_chats = (
        db.query(func.coalesce(func.sum(ArchivedChatActivity.count), 0))
        .filter(
            ArchivedChatActivity.user_id == current_user.id,
            ArchivedChatActivity.day >= week_start_str,
        )
        .scalar()
    )
    week_chats = live_week_chats + archived_week_chats

    live_week_mastered = (
        db.query(Node)
        .join(Topic)
        .filter(
            Topic.user_id == current_user.id,
            Node.state == "mastered",
            Node.mastered_at.isnot(None),
            func.substr(func.cast(Node.mastered_at, String(10)), 1, 10) >= week_start_str,
        )
        .count()
    )
    archived_week_mastered = (
        db.query(ArchivedMastery)
        .filter(
            ArchivedMastery.user_id == current_user.id,
            ArchivedMastery.mastered_at.isnot(None),
            func.substr(func.cast(ArchivedMastery.mastered_at, String(10)), 1, 10)
            >= week_start_str,
        )
        .count()
    )
    week_mastered = live_week_mastered + archived_week_mastered

    # 最活跃时段：按小时 GROUP BY，避免全表加载到 Python 再循环统计
    hour_expr = func.substr(func.cast(ChatMessage.created_at, String(26)), 12, 2)
    hour_rows = (
        db.query(
            hour_expr.label("h"),
            func.count().label("c"),
        )
        .filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.role == "user",
            ChatMessage.mode == "socratic",
        )
        .group_by("h")
        .all()
    )
    hour_counts = {int(row.h): row.c for row in hour_rows}
    archived_hour_rows = (
        db.query(ArchivedChatActivity.hour, func.sum(ArchivedChatActivity.count))
        .filter(ArchivedChatActivity.user_id == current_user.id)
        .group_by(ArchivedChatActivity.hour)
        .all()
    )
    for hour, count in archived_hour_rows:
        hour_counts[hour] = hour_counts.get(hour, 0) + count
    if hour_counts:
        peak_hour = max(hour_counts, key=hour_counts.get)
        peak_label = f"{peak_hour:02d}:00 - {(peak_hour + 2) % 24:02d}:00"
    else:
        peak_label = "暂无数据"

    # 平均每天对话数：以曾学习过的天数为分母，避免用总日历天数导致数值虚低
    avg_daily = round(chat_count / (total_days_learned or 1), 1)
    week_days_learned = sum(1 for d in learned_dates if d >= week_start_str)

    # 最近掌握时间线：joinedload 避免循环中对 node.topic 的 N+1 查询
    recent_mastered = (
        db.query(Node)
        .options(joinedload(Node.topic))
        .join(Topic)
        .filter(
            Topic.user_id == current_user.id,
            Node.state == "mastered",
            Node.mastered_at.isnot(None),
        )
        .order_by(Node.mastered_at.desc())
        .limit(5)
        .all()
    )
    archived_recent_mastered = (
        db.query(ArchivedMastery)
        .filter(
            ArchivedMastery.user_id == current_user.id,
            ArchivedMastery.mastered_at.isnot(None),
        )
        .order_by(ArchivedMastery.mastered_at.desc())
        .limit(5)
        .all()
    )
    mastery_timeline = [
        (node.mastered_at, node.label, node.topic.title if node.topic else "")
        for node in recent_mastered
    ] + [(item.mastered_at, item.label, item.topic_title) for item in archived_recent_mastered]
    mastery_timeline.sort(key=lambda item: item[0].strftime("%Y-%m-%d %H:%M:%S"), reverse=True)
    timeline = [
        {
            "type": "mastered",
            "title": f"掌握「{label}」节点",
            "sub": topic_title,
            "time": mastered_at.strftime("%m/%d %H:%M"),
        }
        for mastered_at, label, topic_title in mastery_timeline[:5]
    ]

    # 成就徽章：按解锁条件计算，顺序即展示顺序
    live_mastered_count = (
        db.query(Node)
        .join(Topic)
        .filter(
            Topic.user_id == current_user.id,
            Node.state == "mastered",
        )
        .count()
    )
    archived_mastered_count = (
        db.query(ArchivedMastery).filter(ArchivedMastery.user_id == current_user.id).count()
    )
    mastered_count = live_mastered_count + archived_mastered_count

    badges = [
        {"icon": "🚀", "name": "第一步", "unlocked": chat_count >= 1},
        {"icon": "🔥", "name": "连续7天", "unlocked": streak >= 7},
        {"icon": "⭐", "name": "掌握10节点", "unlocked": mastered_count >= 10},
        {"icon": "💬", "name": "对话达人", "unlocked": chat_count >= 50},
        {"icon": "🏆", "name": "掌握50节点", "unlocked": mastered_count >= 50},
        {"icon": "🌙", "name": "连续30天", "unlocked": streak >= 30},
        {"icon": "💎", "name": "全图通关", "unlocked": False},
        {"icon": "👑", "name": "学习大师", "unlocked": mastered_count >= 100},
    ]

    return {
        "chat_count": chat_count,
        "mastered_count": mastered_count,
        "streak": streak,
        "total_days": total_days_learned,
        "heatmap": heatmap,
        "timeline": timeline,
        "badges": badges,
        "weekly": {
            "chat_count": week_chats,
            "mastered_count": week_mastered,
            "peak_hour": peak_label,
            "avg_daily": avg_daily,
            "days_learned": week_days_learned,
        },
    }
