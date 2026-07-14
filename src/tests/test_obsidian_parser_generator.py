"""Contract tests for Obsidian task-note parsing and Markdown generation."""

import re

from src.obsidian_integration.generator import ObsidianGenerator
from src.obsidian_integration.parser import ObsidianParser


def test_parse_task_note_reads_front_matter_body_fields_and_checkboxes():
    parser = ObsidianParser()
    content = """---
task_id: T-42
agent: Research Agent
status: pending
metadata without a delimiter
---

# Investigate Artemis

Context: Compare routing outcomes: before and after.
Keywords: routing, governance
Target: [[Routing Review]]
- [ ] Collect evidence
- [x] Summarize findings
Unstructured prose is ignored.
"""

    task = parser.parse_task_note(content)

    assert task == {
        "task_id": "T-42",
        "agent": "Research Agent",
        "status": "pending",
        "title": "Investigate Artemis",
        "context": "Compare routing outcomes: before and after.",
        "keywords": "routing, governance",
        "target": "[[Routing Review]]",
        "subtasks": [
            {"text": "Collect evidence", "completed": False},
            {"text": "Summarize findings", "completed": True},
        ],
    }


def test_parse_task_note_preserves_front_matter_title_and_repairs_non_list_subtasks():
    parser = ObsidianParser()
    content = """---
title: Front Matter Title
subtasks: stale scalar
---
# Body Title
- [ ] Fresh subtask
"""

    task = parser.parse_task_note(content)

    assert task == {
        "title": "Front Matter Title",
        "subtasks": [{"text": "Fresh subtask", "completed": False}],
    }


def test_parse_task_note_returns_none_when_note_has_no_structured_data(caplog):
    parser = ObsidianParser()

    assert (
        parser.parse_task_note("Plain prose only.\n\nNothing structured here.") is None
    )
    assert "No structured task data found in note." in caplog.text


def test_malformed_front_matter_does_not_crash_or_corrupt_note(caplog):
    parser = ObsidianParser()
    malformed = "---\ntask_id: T-broken\nstatus: pending"

    parsed = parser.parse_task_note(malformed)
    updated = parser.update_status_in_note(malformed, "completed")

    assert parsed == {"task_id": "T-broken", "status": "pending"}
    assert updated == malformed
    assert "without closing delimiter" in caplog.text
    assert "Status not updated" in caplog.text


def test_update_status_replaces_adds_and_creates_front_matter():
    parser = ObsidianParser()

    replaced = parser.update_status_in_note(
        "---\ntask_id: T-1\nstatus: pending\nagent: Artemis\n---\n# Task\nBody",
        "completed",
        task_id="T-1",
    )
    inserted = parser.update_status_in_note(
        "---\ntask_id: T-2\nagent: Research\n---\n# Task",
        "in progress",
    )
    created = parser.update_status_in_note("# Task\nBody", "failed")

    assert replaced == (
        "---\ntask_id: T-1\nstatus: completed\nagent: Artemis\n---\n# Task\nBody"
    )
    assert inserted == (
        "---\ntask_id: T-2\nagent: Research\nstatus: in progress\n---\n# Task"
    )
    assert created == "---\nstatus: failed\n---\n# Task\nBody"


def test_generate_agent_report_renders_every_supported_result_shape():
    generator = ObsidianGenerator()

    report = generator.generate_agent_report(
        "Research Agent",
        "T-99",
        {
            "summary": "Routing remained stable.",
            "findings": ["Trust synchronized", "No fallback used"],
            "metrics": {"trust score": 0.9, "attempts": 2},
            "outcome": "success",
        },
    )

    assert "task_id: T-99" in report
    assert "agent: Research Agent" in report
    assert 'tags: ["agent_report", "research_agent"]' in report
    assert re.search(r"timestamp: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", report)
    assert "# Agent Report: Research Agent - T-99" in report
    assert "## Summary of Findings\n\nRouting remained stable." in report
    assert "### Findings\n- Trust synchronized\n- No fallback used" in report
    assert "### Metrics" in report
    assert "- **Trust Score**: 0.9" in report
    assert "- **Attempts**: 2" in report
    assert "- **Outcome**: success" in report
    assert report.count("Routing remained stable.") == 1
    assert "- [ ]  Review this report" in report


def test_generate_agent_report_supplies_default_summary():
    report = ObsidianGenerator().generate_agent_report("Artemis", "T-0", {})

    assert "## Summary of Findings\n\nNo summary provided." in report


def test_generate_task_note_renders_complete_task_and_round_trips():
    generator = ObsidianGenerator()
    task_data = {
        "task_id": "T-7",
        "title": "Review Governance",
        "agent": "Research Agent",
        "required_capability": "document_analysis",
        "status": "ready",
        "tags": ["review", "governance"],
        "context": "Inspect the current policy.",
        "keywords": "trust, quarantine",
        "target": "[[Governance]]",
        "subtasks": [
            {"text": "Read policy", "completed": True},
            {"text": "Write findings", "completed": False},
        ],
    }

    note = generator.generate_task_note(task_data)

    assert note.startswith(
        "---\n"
        "task_id: T-7\n"
        "agent: Research Agent\n"
        "status: ready\n"
        "required_capability: document_analysis\n"
        "tags: ['review', 'governance']\n"
        "---\n\n"
        "# Review Governance\n\n"
    )
    assert "## Context\nInspect the current policy." in note
    assert "Keywords: trust, quarantine" in note
    assert "Target: [[Governance]]" in note
    assert "## Subtasks\n- [x] Read policy\n- [ ] Write findings" in note

    parsed = ObsidianParser().parse_task_note(note)
    assert parsed is not None
    assert parsed["task_id"] == "T-7"
    assert parsed["required_capability"] == "document_analysis"
    assert parsed["title"] == "Review Governance"
    assert parsed["subtasks"] == task_data["subtasks"]


def test_generate_task_note_uses_defaults_and_omits_empty_optional_sections():
    note = ObsidianGenerator().generate_task_note({"subtasks": []})

    assert "task_id: AUTO_GEN_ID" in note
    assert "agent: general" in note
    assert "status: pending" in note
    assert "tags: ['agent_task', 'general']" in note
    assert "required_capability:" not in note
    assert "# New Agent Task" in note
    assert "## Context" not in note
    assert "Keywords:" not in note
    assert "Target:" not in note
    assert "## Subtasks" not in note
