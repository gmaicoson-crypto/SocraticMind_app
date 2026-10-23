from dataclasses import dataclass
from datetime import date, datetime, timedelta
from collections.abc import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .graph_validation import stable_topological_sort


@dataclass(frozen=True)
class PlanItemDraft:
    node_key: str
    scheduled_date: date
    day_order: int
    estimated_minutes: int
    status: str = "pending"
    source_id: int | None = None


@dataclass(frozen=True)
class PlanningResult:
    items: list[PlanItemDraft]
    effective_timezone: str
    estimated_end_date: date
    will_miss_target: bool
    delay_days: int
    total_minutes: int


def resolve_timezone(timezone_name: str | None) -> tuple[str, ZoneInfo]:
    requested = (timezone_name or "UTC").strip() or "UTC"
    try:
        return requested, ZoneInfo(requested)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC", ZoneInfo("UTC")


def today_in_timezone(timezone_name: str | None) -> tuple[date, str]:
    effective_name, timezone_info = resolve_timezone(timezone_name)
    return datetime.now(timezone_info).date(), effective_name


def _schedule(
    nodes: Sequence[dict],
    *,
    daily_minutes: int,
    start_date: date,
    timezone: str | None,
    target_date: date | None,
    completed_items: Sequence[PlanItemDraft],
    skip_node_keys: set[str],
) -> PlanningResult:
    if not 5 <= daily_minutes <= 240:
        raise ValueError("daily_minutes must be between 5 and 240")
    effective_timezone, _ = resolve_timezone(timezone)
    ordered_nodes = stable_topological_sort(nodes)

    completed_by_node: dict[str, int] = {}
    used_by_date: dict[date, int] = {}
    next_order_by_date: dict[date, int] = {}
    preserved = [item for item in completed_items if item.status == "completed"]
    for item in preserved:
        completed_by_node[item.node_key] = (
            completed_by_node.get(item.node_key, 0) + item.estimated_minutes
        )
        used_by_date[item.scheduled_date] = (
            used_by_date.get(item.scheduled_date, 0) + item.estimated_minutes
        )
        next_order_by_date[item.scheduled_date] = max(
            next_order_by_date.get(item.scheduled_date, 0), item.day_order
        )

    scheduled: list[PlanItemDraft] = []
    current_date = start_date
    total_minutes = 0
    for node in ordered_nodes:
        node_key = node["key"]
        duration = int(node.get("estimated_minutes", 30))
        if node_key in skip_node_keys:
            continue
        total_minutes += duration
        remaining = max(0, duration - completed_by_node.get(node_key, 0))
        while remaining:
            used = used_by_date.get(current_date, 0)
            available = daily_minutes - used
            if available <= 0:
                current_date += timedelta(days=1)
                continue
            allocation = min(remaining, available)
            order = next_order_by_date.get(current_date, 0) + 1
            item = PlanItemDraft(
                node_key=node_key,
                scheduled_date=current_date,
                day_order=order,
                estimated_minutes=allocation,
            )
            scheduled.append(item)
            used_by_date[current_date] = used + allocation
            next_order_by_date[current_date] = order
            remaining -= allocation
            if remaining:
                current_date += timedelta(days=1)

    items = sorted(
        [*preserved, *scheduled],
        key=lambda item: (item.scheduled_date, item.day_order, item.source_id or 0),
    )
    estimated_end_date = max(
        (item.scheduled_date for item in items),
        default=start_date,
    )
    delay_days = max(0, (estimated_end_date - target_date).days) if target_date is not None else 0
    return PlanningResult(
        items=items,
        effective_timezone=effective_timezone,
        estimated_end_date=estimated_end_date,
        will_miss_target=delay_days > 0,
        delay_days=delay_days,
        total_minutes=total_minutes,
    )


def build_schedule(
    nodes: Sequence[dict],
    *,
    daily_minutes: int,
    start_date: date,
    timezone: str | None,
    target_date: date | None = None,
    skip_node_keys: set[str] | None = None,
) -> PlanningResult:
    return _schedule(
        nodes,
        daily_minutes=daily_minutes,
        start_date=start_date,
        timezone=timezone,
        target_date=target_date,
        completed_items=[],
        skip_node_keys=skip_node_keys or set(),
    )


def replan_schedule(
    nodes: Sequence[dict],
    *,
    daily_minutes: int,
    timezone: str | None,
    existing_items: Sequence[PlanItemDraft],
    today: date | None = None,
    target_date: date | None = None,
    skip_node_keys: set[str] | None = None,
) -> PlanningResult:
    effective_today, _ = today_in_timezone(timezone)
    return _schedule(
        nodes,
        daily_minutes=daily_minutes,
        start_date=today or effective_today,
        timezone=timezone,
        target_date=target_date,
        completed_items=existing_items,
        skip_node_keys=skip_node_keys or set(),
    )
