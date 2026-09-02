# Artemis Validation MCP Authenticated Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real MCP 2.0 validation server factory that registers the
three canonical ATP tools only after an injected verifier authenticates a
local stdio request, without adding a runnable production entrypoint or any
environment-minted authority.

**Architecture:** `create_server()` requires an `AuthVerifier` and transient
`AuthenticationRequest`; it verifies once, constructs canonical credential-free
authority, authorizes the fixed `validation:read` domain scope, and retains
only a frozen expiry lease. MCP middleware checks that lease before every tool
call, then enforces the exact strict DTO schema. The canonical
`ATPValidationService` remains the sole parser/validator/formatter.

**Tech Stack:** Python 3.12, Pydantic 2, official MCP Python SDK 2.0.0,
canonical `src.auth` contracts, pytest/pytest-asyncio.

**Spec:**
`docs/superpowers/specs/2026-08-16-artemis-mcp-backend-servers-design.md`

**Predecessor:** Task 1 commit `202a63c` from
`docs/superpowers/plans/2026-08-16-artemis-validation-mcp-server.md`.

## Global Constraints

- Own only `server.py`, package `__init__.py`, and `test_server.py` under
  `services/mcp/artemis-validation`.
- `verifier` and `authentication_request` are keyword-only and mandatory.
- Accept only `AuthenticationRequest.transport == "stdio"`.
- Call the injected verifier exactly once before constructing `MCPServer`.
- Obtain authority only through `AuthorityContextFactory.root(receipt)`.
- Require the server-owned domain scope `validation:read`; caller/tool/env
  fields never choose the required capability.
- Retain only credential-free `AuthorityContextV1` and its expiry. Never retain
  the verifier, raw request, headers, body, token, signature, or proof.
- Recheck the authority lease before every `tools/call`; expiry and clock
  failures occur before argument validation and before the validation core.
- Disable every inherited SSE and Streamable HTTP app/runner surface. The
  admitted stdio authority must never be reused as remote-client authority.
- No defaults, module singleton, console script, `__main__.py`, HTTP listener,
  SSE, resources, prompts, environment principal/capability lookup, common MCP
  package, production auth loader, provenance, EXO, reflection, disk, or network.
- Tool names are exactly `parse-atp`, `validate-atp`, and `format-atp`.
- All tool inputs are flat, strict, and `additionalProperties=false` at schema
  and runtime. All success outputs are typed and include `summary`.
- Invalid ATP remains a successful typed diagnostic. Malformed tool input is a
  sanitized `INVALID_PARAMS` MCP error; service failures are sanitized
  `INTERNAL_ERROR` errors.
- Task 3 remains held until Authstructure publishes a conforming receipt broker
  that issues `authstructure.receipt/2` with `validation:read`.
- Preserve every unrelated dirty/staged/untracked path. No reset, stash, clean,
  broad add, or unrelated formatting.

## File Structure

```text
services/mcp/artemis-validation/
  src/artemis_validation_mcp/
    __init__.py       # DTO exports plus create_server; no server object
    models.py         # unchanged Task 1 DTOs
    server.py         # authenticated factory, lease middleware, three tools
  tests/
    test_models.py    # unchanged Task 1 tests
    test_server.py    # auth admission plus real-client MCP conformance
```

---

### Task 2A: Verifier-Injected Validation MCP Server Factory

**Files:**

- Create: `services/mcp/artemis-validation/src/artemis_validation_mcp/server.py`
- Modify: `services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py`
- Create: `services/mcp/artemis-validation/tests/test_server.py`

**Interfaces:**

- Consumes:
  `AuthVerifier.verify(AuthenticationRequest) -> AuthReceiptV1`,
  `AuthorityContextFactory.root(AuthReceiptV1) -> AuthorityContextV1`, Task 1
  DTOs, and the three `ATPValidationService` methods.
- Produces:
  `create_server(*, verifier, authentication_request, service=None,
clock=_utc_now) -> MCPServer` and no module-level runtime object.

- [ ] **Step 1: Write canonical auth fixtures and failing startup-admission tests**

Create the beginning of
`services/mcp/artemis-validation/tests/test_server.py`:

```python
from __future__ import annotations

import gc
import importlib
import inspect
import json
import os
import socket
import subprocess
import sys
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from artemis_validation_mcp.models import (
    FormatATPInput,
    ParseATPInput,
    ValidateATPInput,
)
from artemis_validation_mcp.server import create_server
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST

from mcp import Client
from src.auth.contracts import (
    AuthReceiptSourceV1,
    AuthReceiptV1,
    PrincipalCapabilityV1,
    PrincipalIdentityV1,
    PrincipalV1,
)
from src.auth.verifier import AuthenticationDenied, AuthenticationRequest
from src.routing.authorization import AuthorizationDenied
from src.tests.fakes.auth import FakeAuthVerifier
from src.validation import (
    ATPHeaderInput,
    ATPValidationReport,
    ATPValidationService,
    ParsedATP,
)

NOW = datetime(2026, 8, 16, 16, 0, tzinfo=UTC)
RAW_HEADER_SECRET = "Bearer validation-proof-sentinel"
RAW_BODY_SECRET = b"validation-body-proof-sentinel"
VALID_HASH = """#Mode: Build
#Context: Validation boundary
#Priority: Normal
#ActionType: Execute
#TargetZone: src/validation

Implement the adapter.
"""


def _receipt(
    *,
    scopes: frozenset[str] = frozenset({"validation:read"}),
    expires_at: datetime = NOW + timedelta(minutes=5),
    authenticated: bool = True,
) -> AuthReceiptV1:
    source = AuthReceiptSourceV1(
        format="authstructure.receipt/2",
        receipt_id="receipt:validation-1",
        record_hash="sha256:validation-receipt-1",
        receipt_key_id="key:validation-receipt-1",
        signer_namespace="authstructure",
        canonical_receipt={
            "record_kind": "local-validation-service",
            "verified": True,
        },
    )
    if not authenticated:
        return AuthReceiptV1(
            request_id="request:validation-1",
            authentication="rejected",
            principal=None,
            reason_code="invalid_request_proof",
            verified_at=NOW - timedelta(minutes=1),
            source=source,
        )
    identity = PrincipalIdentityV1(
        actor_issuer="https://auth.example.test",
        actor_subject_ref="subject:validation-service",
        agent_id="service:artemis-validation",
        tenant_id="tenant:artemis-city",
        certificate_issuer="issuer:artemis-ca",
        certificate_serial="serial:validation-1",
        certificate_thumbprint="thumbprint:validation-1",
        request_key_id="key:validation-request-1",
        request_key_jkt="jkt:validation-request-1",
    )
    capability = PrincipalCapabilityV1(
        token_issuer="https://auth.example.test",
        audience="artemis-city",
        token_key_id="key:validation-capability-1",
        token_jti_ref="receipt-ref:validation-jti-1",
        granted_scopes=scopes,
    )
    principal = PrincipalV1(
        identity=identity,
        capability=capability,
        verified_at=NOW - timedelta(minutes=2),
        expires_at=expires_at,
    )
    return AuthReceiptV1(
        request_id="request:validation-1",
        authentication="authenticated",
        principal=principal,
        reason_code=None,
        verified_at=NOW - timedelta(minutes=1),
        source=source,
    )


def _request(
    transport: Literal["http", "stdio", "cli"] = "stdio",
) -> AuthenticationRequest:
    return AuthenticationRequest(
        transport=transport,
        request_id="request:validation-1",
        method="tools/call",
        authority="artemis-validation",
        raw_target=b"mcp://stdio/artemis-validation",
        headers={"authorization": (RAW_HEADER_SECRET,)},
        body=RAW_BODY_SECRET,
    )


@dataclass
class MutableClock:
    value: datetime | Exception = NOW

    def __call__(self) -> datetime:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class ExplodingDateTime(datetime):
    def astimezone(self, tz: object = None) -> datetime:
        del tz
        raise RuntimeError("private datetime normalization failure")


@dataclass
class RecordingFakeVerifier:
    delegate: FakeAuthVerifier
    call_count: int = 0

    def verify(self, request: AuthenticationRequest) -> AuthReceiptV1:
        self.call_count += 1
        return self.delegate.verify(request)


class ExplodingVerifier:
    def verify(self, request: AuthenticationRequest) -> AuthReceiptV1:
        del request
        raise RuntimeError("raw verifier secret")


def _exception_graph(error: BaseException) -> list[BaseException]:
    pending = [error]
    visited: set[int] = set()
    graph: list[BaseException] = []
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        graph.append(current)
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
    return graph


def _server(
    *,
    receipt: AuthReceiptV1 | None = None,
    service: ATPValidationService | None = None,
    clock: MutableClock | None = None,
) -> tuple[MCPServer, RecordingFakeVerifier, MutableClock]:
    selected_clock = clock if clock is not None else MutableClock()
    verifier = RecordingFakeVerifier(
        FakeAuthVerifier(receipt=receipt if receipt is not None else _receipt())
    )
    server = create_server(
        verifier=verifier,
        authentication_request=_request(),
        service=service,
        clock=selected_clock,
    )
    return server, verifier, selected_clock


def test_factory_requires_verifier_and_authentication_request() -> None:
    signature = inspect.signature(create_server)
    assert signature.parameters["verifier"].default is inspect.Parameter.empty
    assert (
        signature.parameters["authentication_request"].default
        is inspect.Parameter.empty
    )
    assert signature.parameters["verifier"].kind is inspect.Parameter.KEYWORD_ONLY
    assert (
        signature.parameters["authentication_request"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )


@pytest.mark.parametrize("transport", ["http", "cli"])
def test_non_stdio_transport_denies_before_verifier(
    transport: Literal["http", "cli"],
) -> None:
    verifier = RecordingFakeVerifier(FakeAuthVerifier(receipt=_receipt()))

    with pytest.raises(AuthenticationDenied) as captured:
        create_server(
            verifier=verifier,
            authentication_request=_request(transport),
            clock=MutableClock(),
        )

    assert captured.value.code == "authentication_rejected"
    assert str(captured.value) == "authentication_rejected"
    assert verifier.call_count == 0


def test_verifier_denial_and_unexpected_failure_are_sanitized() -> None:
    denied = RecordingFakeVerifier(
        FakeAuthVerifier(denial_code="invalid_signature_metadata")
    )
    with pytest.raises(AuthenticationDenied) as captured:
        create_server(
            verifier=denied,
            authentication_request=_request(),
            clock=MutableClock(),
        )
    assert captured.value.code == "invalid_signature_metadata"
    assert denied.call_count == 1

    with pytest.raises(AuthenticationDenied) as unexpected:
        create_server(
            verifier=ExplodingVerifier(),
            authentication_request=_request(),
            clock=MutableClock(),
        )
    assert unexpected.value.code == "auth_verifier_unavailable"
    assert "raw verifier secret" not in str(unexpected.value)
    assert _exception_graph(unexpected.value) == [unexpected.value]


@pytest.mark.parametrize(
    "receipt,clock_value,expected_code",
    [
        (_receipt(authenticated=False), NOW, "authentication_rejected"),
        (
            _receipt(expires_at=NOW - timedelta(seconds=1)),
            NOW,
            "principal_expired",
        ),
        (_receipt(), NOW.replace(tzinfo=None), "receipt_time_invalid"),
        (
            _receipt(),
            ExplodingDateTime(2026, 8, 16, 16, 0, tzinfo=UTC),
            "receipt_time_invalid",
        ),
        (
            _receipt(
                expires_at=ExplodingDateTime(
                    2026,
                    8,
                    16,
                    16,
                    5,
                    tzinfo=UTC,
                )
            ),
            NOW,
            "receipt_time_invalid",
        ),
    ],
)
def test_invalid_authority_never_constructs_server(
    receipt: AuthReceiptV1,
    clock_value: datetime,
    expected_code: str,
) -> None:
    verifier = RecordingFakeVerifier(FakeAuthVerifier(receipt=receipt))

    with pytest.raises(AuthenticationDenied) as captured:
        create_server(
            verifier=verifier,
            authentication_request=_request(),
            clock=MutableClock(clock_value),
        )

    assert captured.value.code == expected_code
    assert verifier.call_count == 1
    assert _exception_graph(captured.value) == [captured.value]
    assert "private datetime normalization failure" not in str(captured.value)


def test_missing_validation_scope_is_a_static_authorization_denial() -> None:
    verifier = RecordingFakeVerifier(
        FakeAuthVerifier(receipt=_receipt(scopes=frozenset({"tasks:read"})))
    )

    with pytest.raises(AuthorizationDenied) as captured:
        create_server(
            verifier=verifier,
            authentication_request=_request(),
            clock=MutableClock(),
        )

    assert captured.value.code == "unauthorized_capability"
    assert captured.value.message == (
        "verified authority does not permit validation reads"
    )
    assert "tasks:read" not in str(captured.value)
    assert verifier.call_count == 1


@pytest.mark.parametrize("transport", ["sse", "streamable-http"])
def test_generic_non_stdio_runner_fails_closed_before_parent_dispatch(
    transport: Literal["sse", "streamable-http"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _ = _server()
    parent_calls: list[str] = []

    def parent_run(*args: object, **kwargs: object) -> None:
        del args, kwargs
        parent_calls.append("run")

    monkeypatch.setattr(MCPServer, "run", parent_run)
    with pytest.raises(
        RuntimeError,
        match="^validation_non_stdio_transport_disabled$",
    ):
        server.run(transport)
    assert parent_calls == []


@pytest.mark.parametrize("method_name", ["sse_app", "streamable_http_app"])
def test_non_stdio_app_builders_fail_closed_before_sdk_app_creation(
    method_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _ = _server()
    parent_calls: list[str] = []

    def parent_app(*args: object, **kwargs: object) -> object:
        del args, kwargs
        parent_calls.append(method_name)
        return object()

    monkeypatch.setattr(MCPServer, method_name, parent_app)
    with pytest.raises(
        RuntimeError,
        match="^validation_non_stdio_transport_disabled$",
    ):
        getattr(server, method_name)()
    assert parent_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    ["run_sse_async", "run_streamable_http_async"],
)
async def test_non_stdio_async_runners_fail_closed_before_sdk_runner(
    method_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _ = _server()
    parent_calls: list[str] = []

    async def parent_runner(*args: object, **kwargs: object) -> None:
        del args, kwargs
        parent_calls.append(method_name)

    monkeypatch.setattr(MCPServer, method_name, parent_runner)
    with pytest.raises(
        RuntimeError,
        match="^validation_non_stdio_transport_disabled$",
    ):
        await getattr(server, method_name)()
    assert parent_calls == []
```

- [ ] **Step 2: Run startup-admission tests and verify RED**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests/test_server.py -q
```

Expected: collection fails because `artemis_validation_mcp.server` does not
exist.

- [ ] **Step 3: Add failing proof-retention and import-safety tests**

Append to `test_server.py`:

```python
def test_factory_retains_no_authentication_proof_or_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTEMIS_MCP_PRINCIPAL_ID", "forged-env-principal")
    monkeypatch.setenv("ARTEMIS_MCP_CAPABILITIES", "validation:read")
    request = _request()
    request_ref = weakref.ref(request)
    verifier = RecordingFakeVerifier(FakeAuthVerifier(receipt=_receipt()))
    verifier_ref = weakref.ref(verifier)

    server = create_server(
        verifier=verifier,
        authentication_request=request,
        clock=MutableClock(),
    )
    assert verifier.call_count == 1
    del request, verifier
    gc.collect()

    assert request_ref() is None
    assert verifier_ref() is None
    server_state = repr(vars(server))
    assert RAW_HEADER_SECRET not in server_state
    assert RAW_BODY_SECRET.decode() not in server_state
    assert "forged-env-principal" not in server_state
    assert "RecordingFakeVerifier" not in server_state


def test_fresh_import_has_no_server_singleton_authority_or_output(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[4]
    package_root = Path(__file__).resolve().parents[1]
    forbidden_log = tmp_path / "must-not-create.log"
    child_environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(
            (str(repository_root), str(package_root / "src"))
        ),
        "ARTEMIS_LOG_FILE": str(forbidden_log),
        "ARTEMIS_MCP_PRINCIPAL_ID": "forged-import-principal",
        "ARTEMIS_MCP_CAPABILITIES": "validation:read",
    }
    script = (
        "import importlib\n"
        "module = importlib.import_module('artemis_validation_mcp.server')\n"
        "assert not hasattr(module, 'server')\n"
        "assert not hasattr(module, 'main')\n"
        "print('import-ok')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=child_environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "import-ok\n"
    assert completed.stderr == ""
    assert not forbidden_log.exists()


def test_factory_performs_no_disk_network_or_console_io(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_io(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("factory attempted external I/O")

    monkeypatch.setattr("builtins.open", forbidden_io)
    monkeypatch.setattr(socket, "create_connection", forbidden_io)
    server, verifier, _ = _server()

    assert isinstance(server, MCPServer)
    assert verifier.call_count == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_server_source_has_no_authority_loader_or_singleton() -> None:
    module = importlib.import_module("artemis_validation_mcp.server")

    assert not hasattr(module, "server")
    assert not hasattr(module, "main")

    source_path = module.__file__
    assert source_path is not None
    source = Path(source_path).read_text(encoding="utf-8").lower()
    forbidden = (
        "artemis_mcp_common",
        "localprincipalprovider",
        "artemis_mcp_principal_id",
        "artemis_mcp_capabilities",
        "src.tests",
        "fakeauthverifier",
        "load_auth_verifier",
        "os.getenv",
        "os.environ",
    )
    assert all(token not in source for token in forbidden)
```

- [ ] **Step 4: Add failing real-client schema, success, and diagnostic tests**

Append to `test_server.py`:

```python
@pytest.mark.asyncio
async def test_tools_list_exposes_exact_strict_typed_contract() -> None:
    server, verifier, _ = _server()
    async with Client(server) as client:
        listed = await client.list_tools()
        resources = await client.list_resources()

    assert verifier.call_count == 1
    tools = {tool.name: tool for tool in listed.tools}
    assert set(tools) == {"parse-atp", "validate-atp", "format-atp"}
    assert resources.resources == []
    expected_inputs = {
        "parse-atp": ParseATPInput.model_json_schema(),
        "validate-atp": ValidateATPInput.model_json_schema(),
        "format-atp": FormatATPInput.model_json_schema(),
    }
    for name, tool in tools.items():
        assert tool.input_schema == expected_inputs[name]
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        assert tool.output_schema["additionalProperties"] is False
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False

    assert tools["parse-atp"].output_schema["required"] == [
        "parsed",
        "summary",
    ]
    assert tools["validate-atp"].output_schema["required"] == [
        "parsed",
        "valid",
        "strict",
        "issues",
        "summary",
    ]
    assert tools["format-atp"].output_schema["required"] == [
        "header",
        "syntax",
        "formatted",
        "summary",
    ]
    assert "raw_input" not in json.dumps(
        tools["parse-atp"].output_schema,
        sort_keys=True,
    )


@pytest.mark.asyncio
async def test_all_tools_return_typed_structured_content() -> None:
    server, _, _ = _server()
    async with Client(server) as client:
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
    assert validated.structured_content["issues"][0]["code"] == "target_zone_relative"
    assert formatted.is_error is False
    assert formatted.structured_content is not None
    assert formatted.structured_content["formatted"].endswith("\n\n---\n")
    assert formatted.structured_content["summary"] == (
        "ATP header formatted using bracket syntax."
    )


@pytest.mark.asyncio
async def test_headerless_input_is_a_successful_typed_diagnostic() -> None:
    server, _, _ = _server()
    async with Client(server) as client:
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
```

- [ ] **Step 5: Add failing lease-order and sanitized-error tests**

Append to `test_server.py`:

```python
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


class FailingValidationService(ATPValidationService):
    def parse(self, raw_input: str) -> ParsedATP:
        raise RuntimeError(f"sensitive service failure for {raw_input}")


class MCPFailingValidationService(ATPValidationService):
    def parse(self, raw_input: str) -> ParsedATP:
        raise MCPError(
            INVALID_PARAMS,
            "LEAKED-SERVICE-SENTINEL",
            {"raw": raw_input},
        )


@pytest.mark.asyncio
async def test_expired_lease_denies_before_input_and_core() -> None:
    service = RecordingValidationService()
    clock = MutableClock()
    server, _, _ = _server(service=service, clock=clock)
    clock.value = NOW + timedelta(minutes=6)

    async with Client(server) as client:
        with pytest.raises(MCPError) as captured:
            await client.call_tool(
                "parse-atp",
                {"raw_input": "private", "extra": "must-not-validate-first"},
            )

    assert captured.value.code == INVALID_REQUEST
    assert captured.value.message == "Validation service authority has expired."
    assert captured.value.data == {"code": "validation_authority_expired"}
    assert "private" not in str(captured.value)
    assert service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clock_value",
    [RuntimeError("private clock failure"), NOW.replace(tzinfo=None)],
)
async def test_runtime_clock_failure_denies_before_core(
    clock_value: datetime | Exception,
) -> None:
    service = RecordingValidationService()
    clock = MutableClock()
    server, _, _ = _server(service=service, clock=clock)
    clock.value = clock_value

    async with Client(server) as client:
        with pytest.raises(MCPError) as captured:
            await client.call_tool("parse-atp", {"raw_input": "private"})

    assert captured.value.code == INTERNAL_ERROR
    assert captured.value.message == "Validation service authority is unavailable."
    assert captured.value.data == {"code": "validation_authority_unavailable"}
    assert "private clock failure" not in str(captured.value)
    assert service.calls == []


@pytest.mark.asyncio
async def test_invalid_tool_input_is_sanitized_before_core() -> None:
    service = RecordingValidationService()
    server, _, _ = _server(service=service)

    async with Client(server) as client:
        with pytest.raises(MCPError) as captured:
            await client.call_tool(
                "format-atp",
                {
                    "mode": "Build",
                    "context": "safe\u2028#ActionType: Execute",
                    "action_type": "Execute",
                },
            )

    assert captured.value.code == INVALID_PARAMS
    assert captured.value.message == "Invalid validation tool input."
    assert captured.value.data == {"code": "invalid_validation_input"}
    assert "#ActionType" not in str(captured.value)
    assert service.calls == []


@pytest.mark.asyncio
async def test_unexpected_service_failure_is_sanitized() -> None:
    raw_input = "private validation body"
    server, _, _ = _server(service=FailingValidationService())

    async with Client(server) as client:
        with pytest.raises(MCPError) as captured:
            await client.call_tool("parse-atp", {"raw_input": raw_input})

    assert captured.value.code == INTERNAL_ERROR
    assert captured.value.message == "Validation service failed."
    assert captured.value.data == {"code": "validation_service_failed"}
    assert raw_input not in str(captured.value)
    assert "sensitive service failure" not in str(captured.value)
    for linked in _exception_graph(captured.value):
        assert raw_input not in str(linked)
        assert raw_input not in repr(linked)


@pytest.mark.asyncio
async def test_service_mcp_error_is_not_treated_as_trusted_transport_error() -> None:
    raw_input = "private MCP error body"
    server, _, _ = _server(service=MCPFailingValidationService())

    async with Client(server) as client:
        with pytest.raises(MCPError) as captured:
            await client.call_tool("parse-atp", {"raw_input": raw_input})

    assert captured.value.code == INTERNAL_ERROR
    assert captured.value.message == "Validation service failed."
    assert captured.value.data == {"code": "validation_service_failed"}
    for linked in _exception_graph(captured.value):
        serialized = f"{linked!s} {linked!r}"
        assert "LEAKED-SERVICE-SENTINEL" not in serialized
        assert raw_input not in serialized
```

- [ ] **Step 6: Run the complete test file and verify RED**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests/test_server.py -q
```

Expected: collection still fails because `server.py` does not exist. Record the
single initial RED; do not claim each append step had a distinct failure.

- [ ] **Step 7: Implement authenticated admission and lease middleware**

Create the first portion of
`services/mcp/artemis-validation/src/artemis_validation_mcp/server.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Never

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    Tool,
    ToolAnnotations,
)
from pydantic import BaseModel, ValidationError

from src.agents.atp.atp_models import ATPActionType, ATPMode, ATPPriority
from src.auth.contracts import AuthorityContextV1
from src.auth.verifier import (
    AuthenticationDenied,
    AuthenticationRequest,
    AuthorityContextFactory,
    AuthVerifier,
)
from src.routing.authorization import AuthorizationDenied
from src.validation import ATPValidationReport, ATPValidationService

from .models import (
    FormatATPInput,
    FormatATPResult,
    ParseATPInput,
    ParseATPResult,
    ValidateATPInput,
)

_REQUIRED_SCOPE = "validation:read"
_NON_STDIO_DISABLED = "validation_non_stdio_transport_disabled"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _startup_now(clock: Callable[[], datetime]) -> datetime:
    normalized: datetime | None = None
    try:
        value = clock()
        if not isinstance(value, datetime):
            raise TypeError
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError
        candidate = value.astimezone(UTC)
        if not isinstance(candidate, datetime):
            raise TypeError
        if candidate.tzinfo is None or candidate.utcoffset() is None:
            raise ValueError
        normalized = candidate
    except Exception:  # noqa: BLE001
        normalized = None
    if normalized is None:
        raise AuthenticationDenied("receipt_time_invalid")
    return normalized


@dataclass(frozen=True, slots=True, repr=False)
class _AuthorityLease:
    authority: AuthorityContextV1
    expires_at: datetime


def _admit_stdio_authority(
    *,
    verifier: AuthVerifier,
    authentication_request: AuthenticationRequest,
    clock: Callable[[], datetime],
) -> _AuthorityLease:
    if authentication_request.transport != "stdio":
        raise AuthenticationDenied("authentication_rejected")
    verification_denial: AuthenticationDenied | None = None
    try:
        receipt = verifier.verify(authentication_request)
    except AuthenticationDenied as denied:
        verification_denial = AuthenticationDenied(denied.code)
    except Exception:  # noqa: BLE001
        verification_denial = AuthenticationDenied("auth_verifier_unavailable")
    if verification_denial is not None:
        raise verification_denial

    authority_denial: AuthenticationDenied | None = None
    try:
        authority = AuthorityContextFactory().root(receipt)
    except AuthenticationDenied as denied:
        authority_denial = AuthenticationDenied(denied.code)
    except Exception:  # noqa: BLE001
        authority_denial = AuthenticationDenied("authentication_rejected")
    if authority_denial is not None:
        raise authority_denial

    now = _startup_now(clock)
    expires_at: datetime | None = None
    try:
        candidate = min(
            authority.requester.principal.expires_at,
            authority.actor.principal.expires_at,
        )
        if candidate.tzinfo is None or candidate.utcoffset() is None:
            raise ValueError
        normalized_expiry = candidate.astimezone(UTC)
        if not isinstance(normalized_expiry, datetime):
            raise TypeError
        if normalized_expiry.tzinfo is None or normalized_expiry.utcoffset() is None:
            raise ValueError
        expires_at = normalized_expiry
    except Exception:  # noqa: BLE001
        expires_at = None
    if expires_at is None:
        raise AuthenticationDenied("receipt_time_invalid")

    expired: bool | None = None
    try:
        expired = now >= expires_at
    except Exception:  # noqa: BLE001
        expired = None
    if expired is None:
        raise AuthenticationDenied("receipt_time_invalid")
    if expired:
        raise AuthenticationDenied("principal_expired")

    scopes = authority.requester.principal.capability.granted_scopes.intersection(
        authority.actor.principal.capability.granted_scopes
    )
    if _REQUIRED_SCOPE not in scopes:
        raise AuthorizationDenied(
            "unauthorized_capability",
            "verified authority does not permit validation reads",
        )
    return _AuthorityLease(authority=authority, expires_at=expires_at)


class _AuthorityExpiryMiddleware:
    def __init__(
        self,
        lease: _AuthorityLease,
        clock: Callable[[], datetime],
    ) -> None:
        self._expires_at = lease.expires_at
        self._clock = clock

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if ctx.method == "tools/call":
            current: datetime | None = None
            try:
                now = self._clock()
                if not isinstance(now, datetime):
                    raise TypeError
                if now.tzinfo is None or now.utcoffset() is None:
                    raise ValueError
                current = now.astimezone(UTC)
            except Exception:  # noqa: BLE001
                current = None
            if current is None:
                raise MCPError(
                    INTERNAL_ERROR,
                    "Validation service authority is unavailable.",
                    {"code": "validation_authority_unavailable"},
                )
            expired: bool | None = None
            try:
                expired = current >= self._expires_at
            except Exception:  # noqa: BLE001
                expired = None
            if expired is None:
                raise MCPError(
                    INTERNAL_ERROR,
                    "Validation service authority is unavailable.",
                    {"code": "validation_authority_unavailable"},
                )
            if expired:
                raise MCPError(
                    INVALID_REQUEST,
                    "Validation service authority has expired.",
                    {"code": "validation_authority_expired"},
                )
        return await call_next(ctx)
```

- [ ] **Step 8: Implement strict input enforcement and schema publication**

Append to `server.py`:

```python
def _invalid_input_error() -> MCPError:
    return MCPError(
        INVALID_PARAMS,
        "Invalid validation tool input.",
        {"code": "invalid_validation_input"},
    )


def _call_service[ResultT](operation: Callable[[], ResultT]) -> ResultT:
    failed = False
    try:
        return operation()
    except Exception:  # noqa: BLE001
        failed = True
    if failed:
        raise MCPError(
            INTERNAL_ERROR,
            "Validation service failed.",
            {"code": "validation_service_failed"},
        )
    raise AssertionError("unreachable service result state")


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
            invalid = False
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
            except Exception:  # noqa: BLE001
                invalid = True
            if invalid:
                raise _invalid_input_error()
        return await call_next(ctx)


class _ValidationMCPServer(MCPServer):
    def __init__(
        self,
        *,
        authority_lease: _AuthorityLease,
        clock: Callable[[], datetime],
        input_models: Mapping[str, type[BaseModel]],
    ) -> None:
        self._authority_lease = authority_lease
        self._input_models = dict(input_models)
        super().__init__(
            name="artemis-validation",
            title="Artemis ATP Validation",
            description="Read-only canonical ATP parse, validate, and format tools.",
            version="0.1.0",
            middleware=[
                _AuthorityExpiryMiddleware(authority_lease, clock),
                _StrictInputMiddleware(self._input_models),
            ],
        )

    def run(
        self,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        **kwargs: Any,
    ) -> None:
        if transport != "stdio":
            raise RuntimeError(_NON_STDIO_DISABLED)
        super().run(transport=transport, **kwargs)

    def sse_app(self, **kwargs: Any) -> Never:
        del kwargs
        raise RuntimeError(_NON_STDIO_DISABLED)

    def streamable_http_app(self, **kwargs: Any) -> Never:
        del kwargs
        raise RuntimeError(_NON_STDIO_DISABLED)

    async def run_sse_async(self, **kwargs: Any) -> Never:
        del kwargs
        raise RuntimeError(_NON_STDIO_DISABLED)

    async def run_streamable_http_async(self, **kwargs: Any) -> Never:
        del kwargs
        raise RuntimeError(_NON_STDIO_DISABLED)

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

- [ ] **Step 9: Implement the mandatory factory and three tools**

Append to `server.py`:

```python
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_server(
    *,
    verifier: AuthVerifier,
    authentication_request: AuthenticationRequest,
    service: ATPValidationService | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> MCPServer:
    authority_lease = _admit_stdio_authority(
        verifier=verifier,
        authentication_request=authentication_request,
        clock=clock,
    )
    validation = service if service is not None else ATPValidationService()
    input_models: dict[str, type[BaseModel]] = {
        "parse-atp": ParseATPInput,
        "validate-atp": ValidateATPInput,
        "format-atp": FormatATPInput,
    }
    mcp_server = _ValidationMCPServer(
        authority_lease=authority_lease,
        clock=clock,
        input_models=input_models,
    )

    @mcp_server.tool(
        name="parse-atp",
        title="Parse ATP",
        description="Parse canonical ATP headers and content without policy mutation.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def parse_atp(raw_input: str) -> ParseATPResult:
        request: ParseATPInput | None = None
        try:
            request = ParseATPInput(raw_input=raw_input)
        except ValidationError:
            request = None
        if request is None:
            raise _invalid_input_error()
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
        request: ValidateATPInput | None = None
        try:
            request = ValidateATPInput(raw_input=raw_input, strict=strict)
        except ValidationError:
            request = None
        if request is None:
            raise _invalid_input_error()
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
        request: FormatATPInput | None = None
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
        except ValidationError:
            request = None
        if request is None:
            raise _invalid_input_error()
        header = request.to_header()
        formatted = _call_service(lambda: validation.format(header, request.syntax))
        return FormatATPResult(
            header=header,
            syntax=request.syntax,
            formatted=formatted,
            summary=f"ATP header formatted using {request.syntax} syntax.",
        )

    return mcp_server
```

Do not append `server = create_server()`, `main()`, or any environment loader.

- [ ] **Step 10: Export only DTOs and the factory**

Replace package `__init__.py` with:

```python
"""MCP transport adapter for canonical Artemis ATP validation."""

from .models import (
    FormatATPInput,
    FormatATPResult,
    ParseATPInput,
    ParseATPResult,
    ValidateATPInput,
)
from .server import create_server

__all__ = [
    "FormatATPInput",
    "FormatATPResult",
    "ParseATPInput",
    "ParseATPResult",
    "ValidateATPInput",
    "create_server",
]
```

- [ ] **Step 11: Run complete focused and canonical regressions**

Run:

```bash
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m pytest \
  services/mcp/artemis-validation/tests \
  src/tests/test_atp_validation_models.py \
  src/tests/test_atp_validation_service.py \
  src/tests/test_atp_import_boundaries.py \
  src/tests/test_atp.py \
  src/tests/test_atp_validator.py \
  src/tests/test_auth_contracts.py \
  src/tests/test_auth_verifier.py -q
```

Expected: all tests pass. Record package-only and combined counts separately.

- [ ] **Step 12: Run formatting, lint, type, security, build, and diff gates**

Run:

```bash
.venv/bin/python -m black --check \
  services/mcp/artemis-validation/src \
  services/mcp/artemis-validation/tests
.venv/bin/python -m ruff check --no-cache \
  services/mcp/artemis-validation/src \
  services/mcp/artemis-validation/tests
PYTHONPATH=.:services/mcp/artemis-validation/src \
  .venv/bin/python -m mypy --follow-imports=skip \
  services/mcp/artemis-validation/src/artemis_validation_mcp
.venv/bin/python -m bandit -q -r \
  services/mcp/artemis-validation/src/artemis_validation_mcp
git diff --check -- services/mcp/artemis-validation
```

Build to a validated disposable directory without deleting it:

```bash
artifact_dir="$(mktemp -d /tmp/artemis-validation-task2a.XXXXXX)" || exit 1
test -n "${artifact_dir}" || exit 1
case "${artifact_dir}" in
  /tmp/artemis-validation-task2a.*) ;;
  *) exit 1 ;;
esac
.venv/bin/python -m build --wheel \
  services/mcp/artemis-validation \
  --outdir "${artifact_dir}"
.venv/bin/python -m zipfile -l \
  "${artifact_dir}"/artemis_validation_mcp-0.1.0-py3-none-any.whl
```

Expected: all gates pass; the wheel contains models, server, and package
metadata, but no tests, auth proof, common package, environment file, database,
log, vault, `__main__.py`, or console entrypoint.

- [ ] **Step 13: Commit exact Task 2A paths**

```bash
git add -- \
  services/mcp/artemis-validation/src/artemis_validation_mcp/server.py \
  services/mcp/artemis-validation/src/artemis_validation_mcp/__init__.py \
  services/mcp/artemis-validation/tests/test_server.py
git diff --cached --name-only
git commit -m "feat(validation-mcp): add authenticated server factory"
```

Expected staged/committed paths are exactly the three listed paths. The plan,
spec, reports, unrelated worktree, package cache, and Task 1 files other than
the explicit `__init__.py` modification remain unstaged.

---

## Final Review Evidence

After the commit:

1. Extract the exact commit with `git archive` and rerun package tests, canonical
   validation/auth regressions, Black, Ruff, owned mypy, Bandit, build, and
   wheel inspection against the archive.
2. Use a real `Client` to capture the three live input/output schemas,
   annotation flags, successful `structuredContent`, empty resources, invalid
   input error, expired lease error, and clock-unavailable error.
3. Inspect server state and source to prove no transient authentication proof,
   verifier, environment authority, common package, singleton, entrypoint,
   resource, or provenance wrapper remains, and prove every inherited
   non-stdio HTTP/SSE surface fails closed before SDK dispatch.
4. Request independent spec-compliance and code-quality review. Every Important
   finding requires a focused witnessed RED before production correction and a
   new exact-commit review.

Task 2A completion proves the authenticated factory contract only. It does not
claim that production stdio can launch. Task 3 remains held until the external
Authstructure verifier/proof broker can issue the exact receipt and
`validation:read` authority.
