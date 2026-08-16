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
        return ATPHeaderInput.model_validate(self.model_dump(exclude={"syntax"}))


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
