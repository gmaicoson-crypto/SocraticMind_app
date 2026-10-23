from datetime import date

from services.planning import PlanItemDraft, build_schedule, replan_schedule


def graph_nodes():
    return [
        {"key": "root", "parent_keys": [], "estimated_minutes": 45},
        {"key": "child", "parent_keys": ["root"], "estimated_minutes": 20},
        {"key": "leaf", "parent_keys": ["child"], "estimated_minutes": 10},
        {"key": "extra-1", "parent_keys": ["root"], "estimated_minutes": 10},
        {"key": "extra-2", "parent_keys": ["extra-1"], "estimated_minutes": 10},
        {"key": "extra-3", "parent_keys": ["extra-2"], "estimated_minutes": 10},
    ]


def test_schedule_splits_nodes_and_keeps_daily_limit_and_dependencies():
    result = build_schedule(
        graph_nodes(),
        daily_minutes=30,
        start_date=date(2026, 9, 7),
        timezone="America/Los_Angeles",
    )

    root_items = [item for item in result.items if item.node_key == "root"]
    child_items = [item for item in result.items if item.node_key == "child"]
    assert [item.estimated_minutes for item in root_items] == [30, 15]
    assert (child_items[0].scheduled_date, child_items[0].day_order) > (
        root_items[-1].scheduled_date,
        root_items[-1].day_order,
    )
    daily_totals: dict[date, int] = {}
    for item in result.items:
        daily_totals[item.scheduled_date] = (
            daily_totals.get(item.scheduled_date, 0) + item.estimated_minutes
        )
    assert max(daily_totals.values()) <= 30
    assert result.effective_timezone == "America/Los_Angeles"


def test_tight_target_reports_delay_without_exceeding_daily_limit():
    result = build_schedule(
        graph_nodes(),
        daily_minutes=30,
        start_date=date(2026, 9, 7),
        target_date=date(2026, 9, 8),
        timezone="Invalid/Timezone",
    )

    assert result.effective_timezone == "UTC"
    assert result.will_miss_target is True
    assert result.delay_days == (result.estimated_end_date - date(2026, 9, 8)).days
    assert all(item.estimated_minutes <= 30 for item in result.items)


def test_five_minute_daily_limit_splits_minimum_duration_node():
    result = build_schedule(
        graph_nodes(),
        daily_minutes=5,
        start_date=date(2026, 9, 7),
        timezone="../not-an-iana-zone",
    )

    root_items = [item for item in result.items if item.node_key == "root"]
    assert len(root_items) == 9
    assert {item.estimated_minutes for item in root_items} == {5}
    assert result.effective_timezone == "UTC"


def test_replan_preserves_completed_items_and_uses_today_capacity():
    completed = PlanItemDraft(
        node_key="root",
        scheduled_date=date(2026, 9, 10),
        day_order=1,
        estimated_minutes=20,
        status="completed",
        source_id=99,
    )

    result = replan_schedule(
        graph_nodes(),
        daily_minutes=30,
        timezone="UTC",
        existing_items=[completed],
        today=date(2026, 9, 10),
    )

    assert result.items[0] == completed
    new_today = [
        item
        for item in result.items
        if item.scheduled_date == date(2026, 9, 10) and item.status == "pending"
    ]
    assert sum(item.estimated_minutes for item in new_today) == 10
    assert all(
        item.scheduled_date >= date(2026, 9, 10)
        for item in result.items
        if item.status == "pending"
    )
