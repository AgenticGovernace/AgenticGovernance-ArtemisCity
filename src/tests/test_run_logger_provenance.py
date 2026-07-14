"""Run logger parent/child provenance tests."""

import sqlite3

from src.utils.run_logger import RunLogger, get_run_events


def test_run_logger_persists_parent_child_provenance(tmp_path):
    db_path = tmp_path / "run_logs.db"
    logger = RunLogger(
        log_dir=str(tmp_path / "logs"),
        db_path=str(db_path),
        run_id="provenance-test",
    )

    parent = logger.log_event(
        "prompt_received",
        "orchestrator",
        prov_id="parent-1",
    )
    child = logger.log_event(
        "routing_decision",
        "router",
        parent_prov_id=parent,
    )

    assert parent == "parent-1"
    assert child != parent
    events = get_run_events(str(db_path), "provenance-test")
    routing = next(event for event in events if event["event_type"] == "routing_decision")
    assert routing["parent_prov_id"] == parent
    assert routing["prov_id"] == child

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM event_log WHERE parent_prov_id = ?", (parent,)
        ).fetchone()[0] == 1

