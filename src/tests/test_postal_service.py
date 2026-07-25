"""Behavior tests for the governed Artemis City postal service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.integration import postal_service
from src.integration.context_loader import ContextEntry
from src.integration.memory_client import MCPResponse
from src.integration.postal_service import MailPacket, PostOffice


@pytest.fixture
def office(monkeypatch: pytest.MonkeyPatch) -> PostOffice:
    """Build an isolated post office without network, sleep, or global stores."""
    instance = PostOffice.__new__(PostOffice)
    instance.memory_client = MagicMock()
    instance.trust_office = MagicMock()
    instance.context_loader = MagicMock()
    instance.delivery_log = []
    monkeypatch.setattr(postal_service.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(postal_service.random, "uniform", lambda _a, _b: 0.0)
    return instance


def test_post_office_initializes_dependencies(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Construction should wire one client into the context loader."""
    client = MagicMock(name="memory-client")
    trust = MagicMock(name="trust-office")
    loader = MagicMock(name="context-loader")
    memory_factory = MagicMock(return_value=client)
    loader_factory = MagicMock(return_value=loader)
    monkeypatch.setattr(
        postal_service.src.integration.memory_client, "MemoryClient", memory_factory
    )
    monkeypatch.setattr(
        postal_service.src.integration.trust_interface,
        "get_trust_interface",
        MagicMock(return_value=trust),
    )
    monkeypatch.setattr(postal_service.context_loader, "ContextLoader", loader_factory)

    result = PostOffice()

    assert result.memory_client is client
    assert result.trust_office is trust
    assert result.context_loader is loader
    assert result.delivery_log == []
    loader_factory.assert_called_once_with(client)
    assert "Post Office - OPEN" in capsys.readouterr().out


def test_mail_packet_has_tracking_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mail packets should expose stable sender-prefixed tracking metadata."""
    monkeypatch.setattr(postal_service.time, "time", lambda: 123.456)

    packet = MailPacket("artemis", "planner", "Status", "All systems nominal", "urgent")

    assert packet.tracking_id == "ART-23456"
    assert packet.delivery_status == "created"
    rendered = str(packet)
    assert "From: artemis" in rendered
    assert "To: planner" in rendered
    assert "Priority: urgent" in rendered


def test_send_mail_rejects_sender_without_clearance(office: PostOffice) -> None:
    """Denied writes should be logged without touching memory."""
    office.trust_office.can_perform_operation.return_value = False

    packet = office.send_mail("guest", "planner", "Hello", "Body")

    assert packet.delivery_status == "rejected - insufficient clearance"
    assert office.delivery_log[0]["reason"] == "No clearance"
    assert office.delivery_log[0]["success"] is False
    office.memory_client.append_context.assert_not_called()


def test_send_mail_delivers_tags_and_records_trust(
    office: PostOffice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful delivery should persist, tag, and reward the sender."""
    office.trust_office.can_perform_operation.return_value = True
    office.memory_client.append_context.return_value = MCPResponse(success=True)
    monkeypatch.setattr(postal_service.random, "random", lambda: 0.0)

    packet = office.send_mail("artemis", "planner", "Plan", "Proceed", "urgent")

    assert packet.delivery_status == "delivered"
    path, note = office.memory_client.append_context.call_args.args
    assert path == f"Postal/Agents/planner/{packet.tracking_id}.md"
    assert "# Mail: Plan" in note
    assert "from: artemis" in note
    office.memory_client.manage_tags.assert_called_once_with(
        path, "add", ["artemis", "planner", "postal-mail", "urgent"]
    )
    office.trust_office.record_success.assert_called_once_with("artemis")
    assert office.delivery_log[-1]["success"] is True


def test_send_mail_records_failed_persistence(
    office: PostOffice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A memory-layer failure should lower trust and remain auditable."""
    office.trust_office.can_perform_operation.return_value = True
    office.memory_client.append_context.return_value = MCPResponse(
        success=False, error="vault offline"
    )
    monkeypatch.setattr(postal_service.random, "random", lambda: 1.0)

    packet = office.send_mail("artemis", "planner", "Plan", "Proceed")

    assert packet.delivery_status == "failed"
    office.trust_office.record_failure.assert_called_once_with("artemis")
    office.memory_client.manage_tags.assert_not_called()
    assert office.delivery_log[-1]["success"] is False


def test_check_mailbox_enforces_read_clearance(office: PostOffice) -> None:
    """Mailbox contents must not be returned to an untrusted reader."""
    office.trust_office.can_perform_operation.return_value = False

    assert office.check_mailbox("guest") == []
    office.context_loader.load_folder_context.assert_not_called()


@pytest.mark.parametrize("entries", [[], [ContextEntry("mail.md", "body", [], {})]])
def test_check_mailbox_loads_recipient_folder(
    office: PostOffice, entries: list[ContextEntry]
) -> None:
    """Cleared recipients should receive their bounded postal-folder entries."""
    office.trust_office.can_perform_operation.return_value = True
    office.context_loader.load_folder_context.return_value = entries * 3

    result = office.check_mailbox("planner", limit=2)

    assert result == (entries * 3)[:2]
    office.context_loader.load_folder_context.assert_called_once_with(
        "Postal/Agents/planner"
    )
    office.trust_office.record_success.assert_called_once_with("planner")


def test_send_to_archives_denies_missing_clearance(office: PostOffice) -> None:
    """Archive writes should fail closed before persistence."""
    office.trust_office.can_perform_operation.return_value = False

    response = office.send_to_archives("guest", "Reports", "Q3", "body")

    assert response.success is False
    assert response.error == "Insufficient clearance for archival operations"
    office.memory_client.store_agent_context.assert_not_called()


@pytest.mark.parametrize("success", [True, False])
def test_send_to_archives_records_outcome(office: PostOffice, success: bool) -> None:
    """Archive persistence should update trust according to its actual outcome."""
    office.trust_office.can_perform_operation.return_value = True
    office.memory_client.store_agent_context.return_value = MCPResponse(
        success=success, error=None if success else "offline"
    )

    response = office.send_to_archives("artemis", "Reports", "Q3", "body")

    assert response.success is success
    office.memory_client.store_agent_context.assert_called_once_with(
        "artemis", "body", folder="Archives/Reports"
    )
    recorder = (
        office.trust_office.record_success
        if success
        else office.trust_office.record_failure
    )
    recorder.assert_called_once_with("artemis")


def test_request_from_archives_enforces_read_clearance(office: PostOffice) -> None:
    """Archive search should not run for an unauthorized requester."""
    office.trust_office.can_perform_operation.return_value = False

    assert office.request_from_archives("guest", "roadmap") == []
    office.context_loader.search_context.assert_not_called()


@pytest.mark.parametrize(
    ("section", "expected_query", "results"),
    [
        (None, "roadmap", []),
        (
            "Plans",
            "#Archives #Plans roadmap",
            [ContextEntry("Archives/Plans/roadmap.md", "body", [], {})],
        ),
    ],
)
def test_request_from_archives_searches_scoped_query(
    office: PostOffice,
    section: str | None,
    expected_query: str,
    results: list[ContextEntry],
) -> None:
    """An optional section should be represented in the archive search query."""
    office.trust_office.can_perform_operation.return_value = True
    office.context_loader.search_context.return_value = results

    assert office.request_from_archives("artemis", "roadmap", section) == results
    office.context_loader.search_context.assert_called_once_with(
        expected_query, limit=10
    )
    office.trust_office.record_success.assert_called_once_with("artemis")


@pytest.mark.parametrize("delivery_log", [[], [{"success": True}, {"success": False}]])
def test_get_postal_report_summarizes_delivery_and_trust(
    office: PostOffice, delivery_log: list[dict]
) -> None:
    """Postal reports should calculate totals and include governance state."""
    office.delivery_log = delivery_log
    trust_report = {"by_level": {"high": ["artemis"], "low": []}}
    office.trust_office.get_trust_report.return_value = trust_report

    report = office.get_postal_report()

    assert report == {
        "total_deliveries": len(delivery_log),
        "successful": sum(item["success"] for item in delivery_log),
        "failed": sum(not item["success"] for item in delivery_log),
        "trust_report": trust_report,
    }


def test_get_post_office_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """The module-level accessor should construct the post office once."""
    sentinel = SimpleNamespace(name="post-office")
    factory = MagicMock(return_value=sentinel)
    monkeypatch.setattr(postal_service, "_city_post_office", None)
    monkeypatch.setattr(postal_service, "PostOffice", factory)

    assert postal_service.get_post_office() is sentinel
    assert postal_service.get_post_office() is sentinel
    factory.assert_called_once_with()
