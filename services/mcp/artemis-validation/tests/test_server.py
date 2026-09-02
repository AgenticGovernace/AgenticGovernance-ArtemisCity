from __future__ import annotations

import gc
import importlib
import inspect
import json
import os
import socket
import subprocess
import sys
import warnings
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from artemis_validation_mcp.models import (
    FormatATPInput,
    ParseATPInput,
    ValidateATPInput,
)
from artemis_validation_mcp.server import create_server
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST

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


OUTPUT_CONVERSION_SECRET = "OUTPUT-CONVERSION-SECRET"


class SecretMalformedResult:
    def __str__(self) -> str:
        return OUTPUT_CONVERSION_SECRET

    def __repr__(self) -> str:
        return OUTPUT_CONVERSION_SECRET


class MalformedResultValidationService(ATPValidationService):
    def parse(self, raw_input: str) -> ParsedATP:
        del raw_input
        return cast(ParsedATP, SecretMalformedResult())

    def validate(
        self,
        raw_input: str,
        strict: bool = True,
    ) -> ATPValidationReport:
        del raw_input, strict
        return cast(ATPValidationReport, SecretMalformedResult())

    def format(
        self,
        header: ATPHeaderInput,
        syntax: Literal["hash", "bracket"] = "bracket",
    ) -> str:
        del header, syntax
        return cast(str, SecretMalformedResult())


SAME_CLASS_OUTPUT_SECRET = "SAME-CLASS-OUTPUT-SECRET"


class SecretDynamicValue:
    def __str__(self) -> str:
        return SAME_CLASS_OUTPUT_SECRET

    def __repr__(self) -> str:
        return SAME_CLASS_OUTPUT_SECRET


class SameClassMalformedValidationService(ATPValidationService):
    def parse(self, raw_input: str) -> ParsedATP:
        values = super().parse(raw_input).model_dump(mode="python")
        values["mode"] = SecretDynamicValue()
        return ParsedATP.model_construct(**values)

    def validate(
        self,
        raw_input: str,
        strict: bool = True,
    ) -> ATPValidationReport:
        report = super().validate(raw_input, strict)
        malformed_parsed = report.parsed.model_copy(
            update={"mode": SecretDynamicValue()}
        )
        return report.model_copy(
            update={
                "parsed": malformed_parsed,
                "valid": SecretDynamicValue(),
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("parse-atp", {"raw_input": "private parse input"}),
        (
            "validate-atp",
            {"raw_input": "private validation input", "strict": True},
        ),
        (
            "format-atp",
            {
                "mode": "Build",
                "context": "Private formatting input",
                "action_type": "Execute",
            },
        ),
    ],
)
async def test_malformed_service_results_are_sanitized_before_sdk_conversion(
    tool_name: str,
    arguments: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    server, _, _ = _server(service=MalformedResultValidationService())
    caplog.clear()
    captured_error: MCPError | None = None

    async with Client(server) as client:
        try:
            result = await client.call_tool(tool_name, arguments)
        except MCPError as error:
            captured_error = error
        else:
            wire_output = f"{result!s} {result!r} {result.model_dump_json()}"
            assert OUTPUT_CONVERSION_SECRET not in wire_output
            assert "error executing tool" not in wire_output.lower()
            assert "validation error" not in wire_output.lower()
            pytest.fail("malformed service result was not rejected")

    assert captured_error is not None
    assert captured_error.code == INTERNAL_ERROR
    assert captured_error.message == "Validation service failed."
    assert captured_error.data == {"code": "validation_service_failed"}
    graph = _exception_graph(captured_error)
    assert graph == [captured_error]
    observed = " ".join(
        [
            *(f"{linked!s} {linked!r}" for linked in graph),
            caplog.text,
        ]
    )
    assert OUTPUT_CONVERSION_SECRET not in observed
    assert "error executing tool" not in observed.lower()
    assert "validation error" not in observed.lower()
    assert "input_value" not in observed.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("parse-atp", {"raw_input": "private same-class parse input"}),
        (
            "validate-atp",
            {
                "raw_input": "private same-class validation input",
                "strict": True,
            },
        ),
    ],
)
async def test_same_class_malformed_results_are_sanitized_without_warnings(
    tool_name: str,
    arguments: dict[str, object],
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    server, _, _ = _server(service=SameClassMalformedValidationService())
    caplog.clear()
    captured_error: MCPError | None = None
    wire_output = ""

    with warnings.catch_warnings(record=True) as captured_warnings:
        warnings.simplefilter("always")
        async with Client(server) as client:
            try:
                result = await client.call_tool(tool_name, arguments)
            except MCPError as error:
                captured_error = error
            else:
                wire_output = f"{result!s} {result!r} {result.model_dump_json()}"

    stderr = capfd.readouterr().err
    warning_output = " ".join(str(item.message) for item in captured_warnings)
    graph = _exception_graph(captured_error) if captured_error is not None else []
    observed = " ".join(
        [
            wire_output,
            stderr,
            warning_output,
            caplog.text,
            *(f"{linked!s} {linked!r}" for linked in graph),
        ]
    )
    assert captured_warnings == []
    assert stderr == ""
    assert SAME_CLASS_OUTPUT_SECRET not in observed
    assert "pydantic" not in observed.lower()
    assert "error executing tool" not in observed.lower()
    assert "serialization" not in observed.lower()
    assert "input_value" not in observed.lower()
    assert captured_error is not None
    assert captured_error.code == INTERNAL_ERROR
    assert captured_error.message == "Validation service failed."
    assert captured_error.data == {"code": "validation_service_failed"}
    assert graph == [captured_error]


@pytest.mark.asyncio
async def test_direct_call_tool_expiry_precedes_strict_input_and_core() -> None:
    service = RecordingValidationService()
    clock = MutableClock()
    server, _, _ = _server(service=service, clock=clock)
    clock.value = NOW + timedelta(minutes=6)

    with pytest.raises(MCPError) as captured:
        await server.call_tool(
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
    [RuntimeError("private direct clock failure"), NOW.replace(tzinfo=None)],
)
async def test_direct_call_tool_clock_failure_precedes_input_and_core(
    clock_value: datetime | Exception,
) -> None:
    service = RecordingValidationService()
    clock = MutableClock()
    server, _, _ = _server(service=service, clock=clock)
    clock.value = clock_value

    with pytest.raises(MCPError) as captured:
        await server.call_tool(
            "parse-atp",
            {"raw_input": "private", "extra": "must-not-validate-first"},
        )

    assert captured.value.code == INTERNAL_ERROR
    assert captured.value.message == "Validation service authority is unavailable."
    assert captured.value.data == {"code": "validation_authority_unavailable"}
    assert "private direct clock failure" not in str(captured.value)
    assert service.calls == []


@pytest.mark.asyncio
async def test_direct_call_tool_strict_input_precedes_core() -> None:
    service = RecordingValidationService()
    server, _, _ = _server(service=service)

    with pytest.raises(MCPError) as captured:
        await server.call_tool(
            "parse-atp",
            {"raw_input": "private", "extra": "forbidden"},
        )

    assert captured.value.code == INVALID_PARAMS
    assert captured.value.message == "Invalid validation tool input."
    assert captured.value.data == {"code": "invalid_validation_input"}
    assert "private" not in str(captured.value)
    assert service.calls == []


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
