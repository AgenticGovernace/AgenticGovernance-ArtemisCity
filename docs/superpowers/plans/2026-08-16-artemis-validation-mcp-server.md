# Artemis Validation MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an independently buildable, local-stdio MCP 2.0 adapter that
exposes the canonical Artemis ATP parse, validate, and format operations with
strict flat inputs, typed structured outputs, controlled errors, and no second
validator implementation.

**Architecture:** The package under `services/mcp/artemis-validation` is a thin
transport adapter over `src.validation.ATPValidationService`. The official
`mcp==2.0.0` `MCPServer` owns registration and stdio; a small server subclass
publishes the exact strict Pydantic input schemas, while pre-validation
middleware enforces those same schemas before handlers. There is no HTTP
listener, resource, persistence, provenance wrapper, EXO proxy, reflection
experiment, or dependency on the quarantined `services/mcp/common` package.

**Tech Stack:** Python 3.12, Pydantic 2, official MCP Python SDK 2.0.0,
Hatchling, pytest/pytest-asyncio.

**Spec:**
`docs/superpowers/specs/2026-08-16-artemis-mcp-backend-servers-design.md`

## Global Constraints

- Use Python `>=3.12,<3.13`, `mcp[cli]==2.0.0`, and `pydantic>=2.4`.
- Tool names are exactly `parse-atp`, `validate-atp`, and `format-atp`.
- All three tools are read-only, non-destructive, idempotent, and closed-world.
- Handler parameters remain flat on the wire; do not introduce `params`,
  `request`, or `header` wrapper objects.
- Every advertised input schema has `type="object"` and
  `additionalProperties=false`, and runtime enforcement matches the schema.
- Typed successful results include a human-readable `summary` and produce real
  `outputSchema` and `structuredContent` fields.
- Invalid ATP is a successful validation result with `valid=false`; malformed
  tool arguments are a sanitized `INVALID_PARAMS` MCP protocol error.
- Unexpected service failures are sanitized `INTERNAL_ERROR` MCP protocol
  errors. Never interpolate raw input, rejected values, exception text, or
  formatter fields into errors.
- `src.validation` is the only parser, validator, formatter, enum, and policy
  authority. Do not copy the Prove regexes, enums, wrappers, or JSON stores.
- These read-only validation/bootstrap tools do not require an ATP envelope:
  requiring a prevalidated ATP message to validate ATP would be circular. This
  is an explicit bootstrap boundary, not a bypass for state-changing tools.
- Initial transport is stdio only. Do not add HTTP, SSE, OAuth, static bearer
  auth, resources, prompts, network calls, or startup diagnostics.
- Application code never writes to stdout; stdio belongs exclusively to MCP.
- Preserve the dirty worktree. Stage and commit only paths owned by each task.

## Execution Gate: Local Service Principal

Task 1 is complete at `202a63c`. The unauthenticated Task 2 draft below is
superseded and must not execute. Use
`docs/superpowers/plans/2026-08-16-artemis-validation-mcp-server-task2a.md`
for the safe verifier-injected server factory. Task 3 remains on hold until one
of these reviewed conditions is true:

1. the canonical Authstructure integration can issue and load a verified local
   service receipt for stdio; or
2. the user explicitly approves a validation-only, read-only local-stdio
   identity exemption in the governing design.

The accepted design requires local stdio to use an explicitly configured
service principal. The current `src.auth.config.load_auth_verifier()` correctly
fails closed because the external Authstructure boundary is unpublished, and
`services/mcp/common` explicitly forbids production use as principal authority.
Therefore the old Task 2/3 snippets below are retained only as historical
tool-contract evidence, not authorization to implement or launch an
unauthenticated server. Task 2A supplies the executable replacement. Environment
strings must not mint identity, capabilities, or receipts. Do not substitute
the quarantined common provider.

## File Structure

```text
services/mcp/artemis-validation/
  pyproject.toml                         # independently buildable package metadata
  README.md                              # scope, local stdio use, bootstrap boundary
  src/artemis_validation_mcp/
    __init__.py                          # supported public exports
    __main__.py                          # `python -m` entrypoint only
    models.py                            # strict MCP request/result DTOs
    server.py                            # MCPServer, strict-input middleware, tools
  tests/
    test_models.py                       # DTO/schema/security unit contracts
    test_server.py                       # real MCP client conformance and errors
    test_entrypoint.py                   # stdio entrypoint wiring
```

The package does not add a second domain layer. `models.py` contains only wire
DTOs that wrap or reuse canonical `src.validation` DTOs. `server.py` owns all
MCP SDK knowledge and dependency injection.

---

### Task 1: Strict MCP Boundary Models and Package Skeleton

**Files:**
- Create: `services/mcp/artemis-validation/pyproject.toml`
- Create: `services/mcp/artemis-validation/src/artemis_validation_mcp/models.py`
- Create: `services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py`
- Create: `services/mcp/artemis-validation/tests/test_models.py`

**Interfaces:**
- Consumes: `src.validation.ATPHeaderInput`, `ParsedATP`, and the canonical ATP
  input enum annotations from `src.validation.models`.
- Produces: `ParseATPInput`, `ValidateATPInput`, `FormatATPInput`,
  `ParseATPResult`, and `FormatATPResult` for Task 2.

- [x] **Step 1: Write the failing model tests**

Create `services/mcp/artemis-validation/tests/test_models.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from artemis_validation_mcp.models import (
    FormatATPInput,
    FormatATPResult,
    ParseATPInput,
    ParseATPResult,
    ValidateATPInput,
)
from src.validation import ATPHeaderInput, ATPValidationService


def test_input_models_are_flat_strict_and_forbid_extras() -> None:
    for model in (ParseATPInput, ValidateATPInput, FormatATPInput):
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False

    with pytest.raises(ValidationError):
        ParseATPInput.model_validate({"raw_input": "plain", "actor": "caller"})

    with pytest.raises(ValidationError):
        ValidateATPInput.model_validate({"raw_input": "plain", "strict": 1})


def test_format_input_advertises_only_canonical_public_enums() -> None:
    properties = FormatATPInput.model_json_schema()["properties"]

    assert properties["mode"]["enum"] == [
        "Build",
        "Review",
        "Organize",
        "Capture",
        "Synthesize",
        "Commit",
        "Reflect",
    ]
    assert properties["action_type"]["enum"] == [
        "Summarize",
        "Scaffold",
        "Execute",
        "Reflect",
    ]
    assert properties["priority"]["enum"] == [
        "Critical",
        "High",
        "Normal",
        "Low",
    ]
    assert properties["priority"]["default"] == "Normal"
    assert properties["syntax"]["enum"] == ["hash", "bracket"]
    assert properties["syntax"]["default"] == "bracket"
    assert "Unknown" not in properties["mode"]["enum"]
    assert "Synthesize" not in properties["action_type"]["enum"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("context", "safe\n#ActionType: Execute"),
        ("target_zone", "src\u2028#Mode: Build"),
        ("special_notes", "safe [[Priority]]: Critical"),
    ],
)
def test_format_input_preserves_canonical_injection_rejection(
    field: str,
    value: str,
) -> None:
    payload = {
        "mode": "Build",
        "context": "validation",
        "action_type": "Execute",
        field: value,
    }

    with pytest.raises(ValidationError):
        FormatATPInput.model_validate(payload)


def test_result_models_are_typed_frozen_and_non_echoing_in_summary() -> None:
    service = ATPValidationService()
    parsed = service.parse("plain request body")
    parse_result = ParseATPResult.from_parsed(parsed)

    assert parse_result.parsed is parsed
    assert parse_result.summary == (
        "ATP parse completed: detected_format=none, "
        "has_atp_headers=false, is_complete=false."
    )
    assert "plain request body" not in parse_result.summary

    header = ATPHeaderInput(
        mode="Build",
        context="validation",
        action_type="Execute",
    )
    format_result = FormatATPResult(
        header=header,
        syntax="bracket",
        formatted="[[Mode]]: Build\n\n---\n",
        summary="ATP header formatted using bracket syntax.",
    )
    with pytest.raises(ValidationError):
        FormatATPResult.model_validate(
            {**format_result.model_dump(), "summary": ""}
        )
    with pytest.raises(ValidationError, match="frozen"):
        setattr(format_result, "summary", "changed")
```

- [x] **Step 2: Run the model tests and verify RED**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests/test_models.py -q
```

Expected: collection fails with `ModuleNotFoundError` because the validation
MCP package does not exist.

- [x] **Step 3: Add independently buildable package metadata**

Create `services/mcp/artemis-validation/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "artemis-validation-mcp"
version = "0.1.0"
description = "Read-only MCP adapter for canonical Artemis ATP validation."
requires-python = ">=3.12,<3.13"
dependencies = [
    "artemis-city==1.0.0",
    "mcp[cli]==2.0.0",
    "pydantic>=2.4",
]

[tool.hatch.build.targets.wheel]
packages = ["src/artemis_validation_mcp"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.uv.sources]
artemis-city = { path = "../../..", editable = true }
```

Do not add `artemis-mcp-common`: that package is quarantined and validation is
read-only stdio in this phase.

- [x] **Step 4: Implement the strict wire models**

Create `services/mcp/artemis-validation/src/artemis_validation_mcp/models.py`:

```python
from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from src.validation import ATPHeaderInput, ParsedATP


class ValidationMCPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ParseATPInput(ValidationMCPModel):
    raw_input: str


class ValidateATPInput(ParseATPInput):
    strict: bool = True


class FormatATPInput(ATPHeaderInput):
    syntax: Literal["hash", "bracket"] = "bracket"

    def to_header(self) -> ATPHeaderInput:
        return ATPHeaderInput.model_validate(
            self.model_dump(exclude={"syntax"})
        )


class ParseATPResult(ValidationMCPModel):
    parsed: ParsedATP
    summary: str = Field(min_length=1)

    @classmethod
    def from_parsed(cls, parsed: ParsedATP) -> Self:
        return cls(
            parsed=parsed,
            summary=(
                "ATP parse completed: "
                f"detected_format={parsed.detected_format}, "
                "has_atp_headers="
                f"{str(parsed.has_atp_headers).lower()}, "
                f"is_complete={str(parsed.is_complete).lower()}."
            ),
        )


class FormatATPResult(ValidationMCPModel):
    header: ATPHeaderInput
    syntax: Literal["hash", "bracket"]
    formatted: str = Field(min_length=1)
    summary: str = Field(min_length=1)
```

`FormatATPInput` inherits the canonical core model deliberately. This reuses
the canonical enum schemas, single-line checks, optional-field rules, and
`extra="forbid"` behavior instead of copying them.

- [x] **Step 5: Add the supported model exports**

Create `services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py`:

```python
"""MCP transport adapter for canonical Artemis ATP validation."""

from .models import (
    FormatATPInput,
    FormatATPResult,
    ParseATPInput,
    ParseATPResult,
    ValidateATPInput,
)

__all__ = [
    "FormatATPInput",
    "FormatATPResult",
    "ParseATPInput",
    "ParseATPResult",
    "ValidateATPInput",
]
```

- [x] **Step 6: Run focused and canonical model tests**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests/test_models.py \
  src/tests/test_atp_validation_models.py -q
```

Expected: all tests pass.

- [x] **Step 7: Run Task 1 quality gates**

Run:

```bash
.venv/bin/python -m black --check \
  services/mcp/artemis-validation/src/artemis_validation_mcp/models.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py \
  services/mcp/artemis-validation/tests/test_models.py
.venv/bin/python -m ruff check \
  services/mcp/artemis-validation/src/artemis_validation_mcp/models.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py \
  services/mcp/artemis-validation/tests/test_models.py
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m mypy \
  services/mcp/artemis-validation/src/artemis_validation_mcp/models.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py
.venv/bin/python -m bandit -q \
  services/mcp/artemis-validation/src/artemis_validation_mcp/models.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py
git diff --check -- \
  services/mcp/artemis-validation/pyproject.toml \
  services/mcp/artemis-validation/src/artemis_validation_mcp \
  services/mcp/artemis-validation/tests/test_models.py
```

Expected: all gates pass.

- [x] **Step 8: Commit Task 1 exact paths**

```bash
git add -- \
  services/mcp/artemis-validation/pyproject.toml \
  services/mcp/artemis-validation/src/artemis_validation_mcp/models.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py \
  services/mcp/artemis-validation/tests/test_models.py
git commit -m "feat(validation-mcp): add strict transport models"
```

Before committing, verify `git diff --cached --name-only` lists exactly the
four paths above.

---

### Task 2: SUPERSEDED — Do Not Execute

**Files:**
- Create: `services/mcp/artemis-validation/src/artemis_validation_mcp/server.py`
- Modify: `services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py`
- Create: `services/mcp/artemis-validation/tests/test_server.py`

**Interfaces:**
- Consumes: the Task 1 wire models and
  `ATPValidationService.parse(raw_input)`,
  `validate(raw_input, strict)`, and `format(header, syntax)`.
- Produces: `create_server(service=None) -> MCPServer`, the module-level
  `server`, and exactly three typed tools for Task 3's stdio entrypoint.

- [ ] **Step 1: Write the failing tools/list contract tests**

Create the following first section of
`services/mcp/artemis-validation/tests/test_server.py`:

```python
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Literal

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS

from artemis_validation_mcp.server import create_server
from artemis_validation_mcp.models import (
    FormatATPInput,
    ParseATPInput,
    ValidateATPInput,
)
from src.validation import (
    ATPHeaderInput,
    ATPValidationReport,
    ATPValidationService,
    ParsedATP,
)


VALID_HASH = """#Mode: Build
#Context: Validation boundary
#Priority: Normal
#ActionType: Execute
#TargetZone: src/validation

Implement the adapter.
"""


@pytest.mark.asyncio
async def test_tools_list_exposes_exact_strict_typed_contract() -> None:
    async with Client(create_server()) as client:
        listed = await client.list_tools()
        resources = await client.list_resources()

    tools = {tool.name: tool for tool in listed.tools}
    assert set(tools) == {"parse-atp", "validate-atp", "format-atp"}
    assert resources.resources == []

    for tool in tools.values():
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        assert tool.output_schema["additionalProperties"] is False
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False

    assert tools["parse-atp"].input_schema["required"] == ["raw_input"]
    assert tools["validate-atp"].input_schema["required"] == ["raw_input"]
    assert tools["parse-atp"].input_schema == ParseATPInput.model_json_schema()
    assert (
        tools["validate-atp"].input_schema
        == ValidateATPInput.model_json_schema()
    )
    assert tools["format-atp"].input_schema == FormatATPInput.model_json_schema()
    assert tools["validate-atp"].input_schema["properties"]["strict"] == {
        "default": True,
        "title": "Strict",
        "type": "boolean",
    }
    format_schema = tools["format-atp"].input_schema
    assert format_schema["required"] == ["mode", "context", "action_type"]
    assert "Synthesize" in format_schema["properties"]["mode"]["enum"]
    assert "Synthesize" not in format_schema["properties"]["action_type"]["enum"]

    parse_output = tools["parse-atp"].output_schema
    validate_output = tools["validate-atp"].output_schema
    format_output = tools["format-atp"].output_schema
    assert parse_output is not None
    assert validate_output is not None
    assert format_output is not None
    assert parse_output["required"] == ["parsed", "summary"]
    assert validate_output["required"] == [
        "parsed",
        "valid",
        "strict",
        "issues",
        "summary",
    ]
    assert format_output["required"] == [
        "header",
        "syntax",
        "formatted",
        "summary",
    ]
    parsed_schema = parse_output["$defs"]["ParsedATP"]
    assert parse_output["properties"]["parsed"] == {
        "$ref": "#/$defs/ParsedATP"
    }
    assert parsed_schema["required"] == [
        "mode",
        "priority",
        "action_type",
        "content",
        "detected_format",
        "has_atp_headers",
        "is_complete",
    ]
    issue_schema = validate_output["$defs"]["ValidationIssue"]
    assert issue_schema["required"] == ["code", "severity", "message"]
    assert validate_output["properties"]["issues"] == {
        "items": {"$ref": "#/$defs/ValidationIssue"},
        "title": "Issues",
        "type": "array",
    }
    serialized_parse_schema = json.dumps(parse_output, sort_keys=True)
    assert "raw_input" not in serialized_parse_schema
    assert "timestamp" not in serialized_parse_schema
    assert "metadata" not in serialized_parse_schema


@pytest.mark.asyncio
async def test_tools_return_runtime_structured_content() -> None:
    async with Client(create_server()) as client:
        parsed = await client.call_tool("parse-atp", {"raw_input": VALID_HASH})
        validated = await client.call_tool(
            "validate-atp",
            {"raw_input": VALID_HASH, "strict": True},
        )
        formatted = await client.call_tool(
            "format-atp",
            {
                "mode": "Build",
                "context": "Validation boundary",
                "action_type": "Execute",
                "priority": "Normal",
                "target_zone": "src/validation",
                "special_notes": "Use the canonical service",
                "syntax": "bracket",
            },
        )

    assert parsed.is_error is False
    assert parsed.structured_content is not None
    assert parsed.structured_content["parsed"]["detected_format"] == "hash"
    assert parsed.structured_content["summary"].endswith("is_complete=true.")

    assert validated.is_error is False
    assert validated.structured_content is not None
    assert validated.structured_content["valid"] is True
    assert validated.structured_content["issues"] == [
        {
            "code": "target_zone_relative",
            "severity": "suggestion",
            "message": (
                "Consider using absolute paths or home-relative paths (~/) "
                "in TargetZone"
            ),
        }
    ]
    assert validated.structured_content["summary"] == (
        "ATP validation passed: 0 errors, 0 warnings, 1 suggestion"
    )

    assert formatted.is_error is False
    assert formatted.structured_content == {
        "header": {
            "mode": "Build",
            "context": "Validation boundary",
            "action_type": "Execute",
            "priority": "Normal",
            "target_zone": "src/validation",
            "special_notes": "Use the canonical service",
        },
        "syntax": "bracket",
        "formatted": (
            "[[Mode]]: Build\n"
            "[[Context]]: Validation boundary\n"
            "[[Priority]]: Normal\n"
            "[[ActionType]]: Execute\n"
            "[[TargetZone]]: src/validation\n"
            "[[SpecialNotes]]: Use the canonical service\n\n---\n"
        ),
        "summary": "ATP header formatted using bracket syntax.",
    }
```

- [ ] **Step 2: Write the failing diagnostic and sanitized-error tests**

Append to `test_server.py`:

```python
@pytest.mark.asyncio
async def test_headerless_atp_is_a_typed_diagnostic_not_a_tool_error() -> None:
    async with Client(create_server()) as client:
        parsed = await client.call_tool(
            "parse-atp",
            {"raw_input": "plain content"},
        )
        validated = await client.call_tool(
            "validate-atp",
            {"raw_input": "plain content", "strict": True},
        )

    assert parsed.is_error is False
    assert parsed.structured_content is not None
    assert parsed.structured_content["parsed"]["mode"] == "Unknown"
    assert parsed.structured_content["parsed"]["detected_format"] == "none"
    assert validated.is_error is False
    assert validated.structured_content is not None
    assert validated.structured_content["valid"] is False
    assert validated.structured_content["issues"][0]["code"] == "no_atp_headers"


class RecordingValidationService(ATPValidationService):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def parse(self, raw_input: str) -> ParsedATP:
        self.calls.append("parse")
        return super().parse(raw_input)

    def validate(
        self,
        raw_input: str,
        strict: bool = True,
    ) -> ATPValidationReport:
        self.calls.append("validate")
        return super().validate(raw_input, strict)

    def format(
        self,
        header: ATPHeaderInput,
        syntax: Literal["hash", "bracket"] = "bracket",
    ) -> str:
        self.calls.append("format")
        return super().format(header, syntax)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("parse-atp", {"raw_input": "plain", "actor": "caller"}),
        ("validate-atp", {"raw_input": "plain", "strict": 1}),
        (
            "format-atp",
            {
                "mode": "Build",
                "context": "safe\u2028#ActionType: Execute",
                "action_type": "Execute",
            },
        ),
        (
            "format-atp",
            {
                "mode": "Build",
                "context": "validation",
                "action_type": "Synthesize",
            },
        ),
        (
            "format-atp",
            {
                "mode": "Build",
                "context": "validation",
                "action_type": "Execute",
                "syntax": "xml",
            },
        ),
    ],
)
async def test_invalid_inputs_are_sanitized_protocol_errors_before_core(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    service = RecordingValidationService()
    async with Client(create_server(service)) as client:
        with pytest.raises(MCPError) as captured:
            await client.call_tool(tool_name, arguments)

    assert captured.value.code == INVALID_PARAMS
    assert captured.value.message == "Invalid validation tool input."
    assert captured.value.data == {"code": "invalid_validation_input"}
    assert "caller" not in str(captured.value)
    assert "#ActionType" not in str(captured.value)
    assert "Synthesize" not in str(captured.value)
    assert "xml" not in str(captured.value)
    assert service.calls == []


class FailingValidationService(ATPValidationService):
    def parse(self, raw_input: str) -> ParsedATP:
        raise RuntimeError(f"sensitive failure for {raw_input}")


@pytest.mark.asyncio
async def test_unexpected_service_failure_is_sanitized() -> None:
    raw_input = "private validation body"
    async with Client(create_server(FailingValidationService())) as client:
        with pytest.raises(MCPError) as captured:
            await client.call_tool("parse-atp", {"raw_input": raw_input})

    assert captured.value.code == INTERNAL_ERROR
    assert captured.value.message == "Validation service failed."
    assert captured.value.data == {"code": "validation_service_failed"}
    assert raw_input not in str(captured.value)
    assert "sensitive failure" not in str(captured.value)
```

- [ ] **Step 3: Write the failing no-I/O/no-Prove boundary test**

Append to `test_server.py`:

```python
@pytest.mark.asyncio
async def test_tools_have_no_filesystem_network_or_diagnostic_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = create_server()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("validation tool attempted external I/O")

    monkeypatch.setattr("pathlib.Path.open", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)

    async with Client(server) as client:
        result = await client.call_tool(
            "validate-atp",
            {"raw_input": VALID_HASH, "strict": True},
        )

    assert result.is_error is False
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_adapter_source_does_not_import_prove_or_legacy_wrappers() -> None:
    server_module = importlib.import_module("artemis_validation_mcp.server")
    source = server_module.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    forbidden = (
        "projects.prove",
        "_provenance",
        "log_tool_call",
        "api_bridge",
        "exo",
        "reflection",
    )
    assert all(token not in text.lower() for token in forbidden)
```

- [ ] **Step 4: Run the server tests and verify RED**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests/test_server.py -q
```

Expected: collection fails because `artemis_validation_mcp.server` does not
exist.

- [ ] **Step 5: Implement strict pre-validation and schema publication**

Create the imports and support types at the top of
`services/mcp/artemis-validation/src/artemis_validation_mcp/server.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Never, TypeVar

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, Tool, ToolAnnotations
from pydantic import BaseModel, ValidationError

from src.agents.atp.atp_models import ATPActionType, ATPMode, ATPPriority
from src.validation import ATPHeaderInput, ATPValidationReport, ATPValidationService

from .models import (
    FormatATPInput,
    FormatATPResult,
    ParseATPInput,
    ParseATPResult,
    ValidateATPInput,
)

_ResultT = TypeVar("_ResultT")
_ERROR_DATA_INVALID = {"code": "invalid_validation_input"}
_ERROR_DATA_SERVICE = {"code": "validation_service_failed"}


def _invalid_input(exc: Exception) -> Never:
    raise MCPError(
        INVALID_PARAMS,
        "Invalid validation tool input.",
        _ERROR_DATA_INVALID,
    ) from exc


def _call_service(operation: Callable[[], _ResultT]) -> _ResultT:
    try:
        return operation()
    except MCPError:
        raise
    except Exception as exc:
        raise MCPError(
            INTERNAL_ERROR,
            "Validation service failed.",
            _ERROR_DATA_SERVICE,
        ) from exc


class _StrictInputMiddleware:
    def __init__(
        self,
        input_models: Mapping[str, type[BaseModel]],
    ) -> None:
        self._input_models = dict(input_models)

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if ctx.method == "tools/call":
            try:
                if not isinstance(ctx.params, Mapping):
                    raise TypeError
                tool_name = ctx.params.get("name")
                arguments = ctx.params.get("arguments", {})
                input_model = (
                    self._input_models.get(tool_name)
                    if isinstance(tool_name, str)
                    else None
                )
                if input_model is not None:
                    if not isinstance(arguments, Mapping):
                        raise TypeError
                    input_model.model_validate(arguments)
            except MCPError:
                raise
            except Exception as exc:  # noqa: BLE001
                _invalid_input(exc)
        return await call_next(ctx)


class _ValidationMCPServer(MCPServer):
    def __init__(
        self,
        input_models: Mapping[str, type[BaseModel]],
    ) -> None:
        self._input_models = dict(input_models)
        super().__init__(
            name="artemis-validation",
            title="Artemis ATP Validation",
            description="Read-only canonical ATP parse, validate, and format tools.",
            version="0.1.0",
            middleware=[_StrictInputMiddleware(self._input_models)],
        )

    async def list_tools(self) -> list[Tool]:
        published: list[Tool] = []
        for tool in await super().list_tools():
            input_model = self._input_models.get(tool.name)
            if input_model is None:
                published.append(tool)
                continue
            published.append(
                tool.model_copy(
                    update={
                        "input_schema": input_model.model_json_schema(by_alias=True)
                    }
                )
            )
        return published
```

The server override uses only the public `list_tools()` result and Pydantic
`model_copy`; it does not mutate MCP SDK internals. Runtime enforcement and
advertised schemas are driven by the same immutable mapping.

- [ ] **Step 6: Register the three typed tools**

Append to `server.py`:

```python
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_server(
    service: ATPValidationService | None = None,
) -> MCPServer:
    validation = service if service is not None else ATPValidationService()
    input_models: dict[str, type[BaseModel]] = {
        "parse-atp": ParseATPInput,
        "validate-atp": ValidateATPInput,
        "format-atp": FormatATPInput,
    }
    mcp_server = _ValidationMCPServer(input_models)

    @mcp_server.tool(
        name="parse-atp",
        title="Parse ATP",
        description="Parse canonical ATP headers and content without policy mutation.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def parse_atp(raw_input: str) -> ParseATPResult:
        try:
            request = ParseATPInput(raw_input=raw_input)
        except ValidationError as exc:
            _invalid_input(exc)
        parsed = _call_service(lambda: validation.parse(request.raw_input))
        return ParseATPResult.from_parsed(parsed)

    @mcp_server.tool(
        name="validate-atp",
        title="Validate ATP",
        description="Validate ATP through the canonical Artemis validator.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def validate_atp(
        raw_input: str,
        strict: bool = True,
    ) -> ATPValidationReport:
        try:
            request = ValidateATPInput(raw_input=raw_input, strict=strict)
        except ValidationError as exc:
            _invalid_input(exc)
        return _call_service(
            lambda: validation.validate(request.raw_input, request.strict)
        )

    @mcp_server.tool(
        name="format-atp",
        title="Format ATP",
        description="Format canonical ATP header fields using hash or bracket syntax.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def format_atp(
        mode: ATPMode,
        context: str,
        action_type: ATPActionType,
        priority: ATPPriority = ATPPriority.NORMAL,
        target_zone: str | None = None,
        special_notes: str | None = None,
        syntax: str = "bracket",
    ) -> FormatATPResult:
        try:
            request = FormatATPInput(
                mode=mode,
                context=context,
                action_type=action_type,
                priority=priority,
                target_zone=target_zone,
                special_notes=special_notes,
                syntax=syntax,
            )
        except ValidationError as exc:
            _invalid_input(exc)
        header = request.to_header()
        formatted = _call_service(
            lambda: validation.format(header, request.syntax)
        )
        return FormatATPResult(
            header=header,
            syntax=request.syntax,
            formatted=formatted,
            summary=f"ATP header formatted using {request.syntax} syntax.",
        )

    return mcp_server


server = create_server()
```

Do not replace the flat handler signatures with a single model parameter. The
middleware validates the complete raw argument object before the SDK invokes
the handler, and the handler constructs the same strict model again as a
direct-call defense.

- [ ] **Step 7: Export the server factory and module server**

Replace `services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py`
with:

```python
"""MCP transport adapter for canonical Artemis ATP validation."""

from .models import (
    FormatATPInput,
    FormatATPResult,
    ParseATPInput,
    ParseATPResult,
    ValidateATPInput,
)
from .server import create_server, server

__all__ = [
    "FormatATPInput",
    "FormatATPResult",
    "ParseATPInput",
    "ParseATPResult",
    "ValidateATPInput",
    "create_server",
    "server",
]
```

- [ ] **Step 8: Run real-client and canonical regression tests**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests/test_models.py \
  services/mcp/artemis-validation/tests/test_server.py \
  src/tests/test_atp_validation_models.py \
  src/tests/test_atp_validation_service.py \
  src/tests/test_atp.py \
  src/tests/test_atp_validator.py -q
```

Expected: all tests pass. The real client must show all three `output_schema`
objects and all successful calls must contain `structured_content`.

- [ ] **Step 9: Run Task 2 quality and security gates**

Run:

```bash
.venv/bin/python -m black --check \
  services/mcp/artemis-validation/src/artemis_validation_mcp \
  services/mcp/artemis-validation/tests
.venv/bin/python -m ruff check \
  services/mcp/artemis-validation/src/artemis_validation_mcp \
  services/mcp/artemis-validation/tests
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m mypy \
  services/mcp/artemis-validation/src/artemis_validation_mcp
.venv/bin/python -m bandit -q -r \
  services/mcp/artemis-validation/src/artemis_validation_mcp
git diff --check -- \
  services/mcp/artemis-validation/src/artemis_validation_mcp \
  services/mcp/artemis-validation/tests
```

Expected: all gates pass. If normal mypy follows imports into unrelated dirty
modules, also run an isolated mypy cache and report both the baseline and the
owned-file result; do not weaken type checking or edit unrelated files.

- [ ] **Step 10: Commit Task 2 exact paths**

```bash
git add -- \
  services/mcp/artemis-validation/src/artemis_validation_mcp/server.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py \
  services/mcp/artemis-validation/tests/test_server.py
git commit -m "feat(validation-mcp): add typed MCP server"
```

Before committing, verify `git diff --cached --name-only` lists exactly the
three paths above.

---

### Task 3: Stdio Entrypoint, Operator Documentation, and Wheel Proof

**Files:**
- Create: `services/mcp/artemis-validation/src/artemis_validation_mcp/__main__.py`
- Modify: `services/mcp/artemis-validation/src/artemis_validation_mcp/server.py`
- Modify: `services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py`
- Modify: `services/mcp/artemis-validation/pyproject.toml`
- Create: `services/mcp/artemis-validation/README.md`
- Create: `services/mcp/artemis-validation/tests/test_entrypoint.py`

**Interfaces:**
- Consumes: Task 2's module-level `server`.
- Produces: `main() -> None`, `python -m artemis_validation_mcp`, and the
  `artemis-validation-mcp` console script, both running stdio only.

- [ ] **Step 1: Write the failing entrypoint test**

Create `services/mcp/artemis-validation/tests/test_entrypoint.py`:

```python
from __future__ import annotations

import importlib
import runpy

from artemis_validation_mcp import server as registered_server
from artemis_validation_mcp.server import main


def test_main_runs_registered_server_over_stdio(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        registered_server,
        "run",
        lambda transport: calls.append(transport),
    )

    main()

    assert calls == ["stdio"]


def test_python_module_entrypoint_calls_main(monkeypatch) -> None:
    calls: list[str] = []
    server_module = importlib.import_module("artemis_validation_mcp.server")
    monkeypatch.setattr(server_module, "main", lambda: calls.append("main"))

    runpy.run_module("artemis_validation_mcp.__main__", run_name="__main__")

    assert calls == ["main"]
```

- [ ] **Step 2: Run the entrypoint test and verify RED**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests/test_entrypoint.py -q
```

Expected: import failure because `main` and `__main__.py` do not exist.

- [ ] **Step 3: Add the stdio-only entrypoint**

Append to `server.py`:

```python
def main() -> None:
    server.run("stdio")
```

Create `services/mcp/artemis-validation/src/artemis_validation_mcp/__main__.py`:

```python
from .server import main

main()
```

Update `__init__.py` to import `main` from `.server` and add `"main"` to
`__all__`.

- [ ] **Step 4: Register the console script**

Add this table to `services/mcp/artemis-validation/pyproject.toml` after the
dependency list:

```toml
[project.scripts]
artemis-validation-mcp = "artemis_validation_mcp.server:main"
```

- [ ] **Step 5: Document scope and safe operation**

Create `services/mcp/artemis-validation/README.md` with this complete content:

```markdown
# Artemis Validation MCP

Read-only MCP 2.0 access to the canonical Artemis ATP parser, validator, and
formatter.

## Surface

- `parse-atp` parses ATP headers and content.
- `validate-atp` validates with the canonical strict or compatibility policy.
- `format-atp` formats canonical fields using bracket or hash syntax.

The server imports `src.validation.ATPValidationService`; it does not contain a
second parser, validator, enum set, or provenance wrapper. It has no resources,
persistence, EXO proxy, reflection path, or network access.

## Transport and trust boundary

The initial transport is local stdio only:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  python -m artemis_validation_mcp
```

Stdout is reserved for MCP protocol frames. The server emits no application
diagnostics.

These three operations are ATP bootstrap tools: validating an incomplete or
invalid ATP message cannot require that same message to be prevalidated. They
are read-only and perform no durable action. This exemption does not apply to
state-changing Artemis servers.

Streamable HTTP is intentionally absent until the reviewed Artemis principal
verifier and MCP `AuthSettings` are wired together. Do not expose this package
as an unauthenticated HTTP service.
```

- [ ] **Step 6: Run all validation MCP and canonical ATP tests**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests \
  src/tests/test_atp_validation_models.py \
  src/tests/test_atp_validation_service.py \
  src/tests/test_atp_import_boundaries.py \
  src/tests/test_atp.py \
  src/tests/test_atp_validator.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Build and inspect the independent wheel**

Run in one foreground shell:

```bash
artifact_dir="$(mktemp -d /tmp/artemis-validation-mcp.XXXXXX)" || exit 1
test -n "${artifact_dir}" || exit 1
case "${artifact_dir}" in
  /tmp/artemis-validation-mcp.*) ;;
  *) exit 1 ;;
esac
.venv/bin/python -m build --wheel \
  services/mcp/artemis-validation \
  --outdir "${artifact_dir}"
.venv/bin/python -m zipfile -l \
  "${artifact_dir}"/artemis_validation_mcp-0.1.0-py3-none-any.whl
```

Expected: the wheel builds and contains only the
`artemis_validation_mcp` package plus distribution metadata. It must not embed
Prove, `src.validation`, `.env` files, databases, logs, or vault content.

- [ ] **Step 8: Run final formatting, lint, type, security, and diff gates**

Run:

```bash
.venv/bin/python -m black --check \
  services/mcp/artemis-validation/src \
  services/mcp/artemis-validation/tests
.venv/bin/python -m ruff check \
  services/mcp/artemis-validation/src \
  services/mcp/artemis-validation/tests
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m mypy \
  services/mcp/artemis-validation/src/artemis_validation_mcp
.venv/bin/python -m bandit -q -r \
  services/mcp/artemis-validation/src/artemis_validation_mcp
git diff --check -- services/mcp/artemis-validation
```

Expected: all gates pass.

- [ ] **Step 9: Verify exact scope and commit Task 3**

```bash
git add -- \
  services/mcp/artemis-validation/pyproject.toml \
  services/mcp/artemis-validation/README.md \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__main__.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/server.py \
  services/mcp/artemis-validation/tests/test_entrypoint.py
git diff --cached --name-only
git commit -m "feat(validation-mcp): ship stdio package"
```

Expected staged paths are exactly the six paths listed above. Preserve every
unrelated worktree and index change.

---

## Final Review and Release Evidence

After all three task commits:

1. Run the full Task 3 test command from a clean archive of the three commits,
   not only from the concurrent dirty worktree.
2. Run a real `Client(create_server())` probe and record the exact three tool
   names, all input/output schemas, annotation flags, representative success
   `structuredContent`, the invalid-input `MCPError`, and an empty resource
   list.
3. Confirm no `FastMCP`, low-level `Server`, manual `Tool(inputSchema=...)`,
   Prove import, provenance wrapper, common gate, HTTP transport, SSE, resource,
   prompt, file write, network call, or stdout diagnostic exists in the package.
4. Inspect the wheel manifest and dependency metadata.
5. Request an independent spec-compliance and code-quality review. Fix every
   blocking or important finding with a witnessed RED test before the
   production change, then rerun the exact-archive gates.

The validation server is complete only when the clean-archive evidence and
independent review agree. Its completion does not imply that memory,
provenance, task, registry, governance, or routing MCP servers are complete.
