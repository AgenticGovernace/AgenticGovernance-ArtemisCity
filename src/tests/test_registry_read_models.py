"""Contract tests for the registry read models."""

from __future__ import annotations

import importlib.util

import pytest
from pydantic import ValidationError

from src.registry.models import RegistryAgentView


def test_registry_agent_view_contract_is_available() -> None:
    """A typed, public-only registry view is available to read callers."""
    assert importlib.util.find_spec("src.registry.models") is not None


def test_registry_agent_view_exposes_only_the_public_fields() -> None:
    """Internal registry state cannot leak through the typed read view."""
    assert set(RegistryAgentView.model_fields) == {
        "name",
        "capabilities",
        "description",
    }


def test_registry_agent_view_is_frozen_and_rejects_extra_fields() -> None:
    """A caller cannot mutate a view or smuggle internal state into it."""
    agent = RegistryAgentView(
        name="research",
        capabilities=("search",),
        description=None,
    )

    with pytest.raises(ValidationError):
        agent.name = "changed"
    with pytest.raises(ValidationError):
        RegistryAgentView(
            name="research",
            capabilities=("search",),
            description=None,
            trust_score=1.0,
        )


@pytest.mark.parametrize(
    ("name", "capabilities", "description"),
    [
        ("", ("search",), None),
        (1, ("search",), None),
        ("research", ["search"], None),
        ("research", ("",), None),
        ("research", (1,), None),
        ("research", ("search",), 1),
    ],
)
def test_registry_agent_view_requires_strict_public_values(
    name: object, capabilities: object, description: object
) -> None:
    """Public records reject coercible or malformed values instead of coercing."""
    with pytest.raises(ValidationError):
        RegistryAgentView(
            name=name,
            capabilities=capabilities,
            description=description,
        )
