import pytest
from pydantic import ValidationError

from artemis_mcp_common.models import AtpEnvelope, ServicePrincipal


def test_atp_envelope_rejects_authority_alias():
    with pytest.raises(ValidationError, match="parent_id"):
        AtpEnvelope(
            mode="Commit",
            context="Store the reviewed note",
            action_type="Execute",
            target_zone="memory/reviewed",
            parent_provenance_id="prov-root",
            parent_id="shadow-root",
        )


def test_service_principal_normalizes_capabilities():
    principal = ServicePrincipal(
        principal_id="operator",
        capabilities={" memory:write ", "memory:read"},
    )

    assert principal.capabilities == {"memory:read", "memory:write"}
