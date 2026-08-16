from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Never

from mcp.server.context import CallNext, Context, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    CallToolResult,
    InputRequiredResult,
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
            _require_current_authority(self._expires_at, self._clock)
        return await call_next(ctx)


def _require_current_authority(
    expires_at: datetime,
    clock: Callable[[], datetime],
) -> None:
    current: datetime | None = None
    try:
        now = clock()
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
        expired = current >= expires_at
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


def _require_strict_tool_input(
    input_models: Mapping[str, type[BaseModel]],
    tool_name: object,
    arguments: object,
) -> None:
    invalid = False
    try:
        input_model = (
            input_models.get(tool_name) if isinstance(tool_name, str) else None
        )
        if input_model is not None:
            if not isinstance(arguments, Mapping):
                raise TypeError
            input_model.model_validate(arguments)
    except Exception:  # noqa: BLE001
        invalid = True
    if invalid:
        raise _invalid_input_error()


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
            tool_name: object = None
            arguments: object = {}
            try:
                if not isinstance(ctx.params, Mapping):
                    raise TypeError
                tool_name = ctx.params.get("name")
                arguments = ctx.params.get("arguments", {})
            except Exception:  # noqa: BLE001
                invalid = True
            if invalid:
                raise _invalid_input_error()
            _require_strict_tool_input(self._input_models, tool_name, arguments)
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
        self._clock = clock
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

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        _require_current_authority(self._authority_lease.expires_at, self._clock)
        _require_strict_tool_input(self._input_models, name, arguments)
        return await super().call_tool(name, arguments, context)

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
        return _call_service(
            lambda: ParseATPResult.from_parsed(validation.parse(request.raw_input))
        )

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

        def validated_result() -> ATPValidationReport:
            report = validation.validate(request.raw_input, request.strict)
            return ATPValidationReport.model_validate(report.model_dump(mode="python"))

        return _call_service(validated_result)

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
        return _call_service(
            lambda: FormatATPResult(
                header=header,
                syntax=request.syntax,
                formatted=validation.format(header, request.syntax),
                summary=f"ATP header formatted using {request.syntax} syntax.",
            )
        )

    return mcp_server
