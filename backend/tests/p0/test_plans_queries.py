from sqlalchemy import event

from tests.p0.test_plans_api import create_plan


def test_today_plan_uses_bounded_select_count(client, db_session, auth_user):
    create_plan(db_session, auth_user, title="One")
    create_plan(db_session, auth_user, title="Two")
    selects = []

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", count_selects)
    try:
        response = client.get("/api/plans/today", params={"timezone": "UTC"})
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_selects)

    assert response.status_code == 200
    assert len(selects) <= 2
