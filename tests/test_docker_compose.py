"""
Unit tests for validating the docker-compose.yaml configuration.

Tests the structure, services, and security constraints defined in the file.
"""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def docker_compose_path():
    """Fixture to get the path to docker-compose.yaml."""
    return Path(__file__).parent.parent / "docker-compose.yaml"


@pytest.fixture
def docker_compose_config(docker_compose_path):
    """Fixture to load and parse the docker-compose.yaml file."""
    assert docker_compose_path.exists(), f"File not found: {docker_compose_path}"
    with open(docker_compose_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestDockerCompose:
    """Tests for validating docker-compose structure and configurations."""

    def test_version_and_basic_structure(self, docker_compose_config):
        """Test that the docker-compose version and basic structure are correct."""
        # Modern Compose files do not require a top-level version. If the
        # legacy field is present, keep it pinned to the expected schema.
        assert docker_compose_config.get("version") in (None, "3.8")
        assert "services" in docker_compose_config
        assert "volumes" in docker_compose_config
        assert "networks" in docker_compose_config

    def test_required_services_present(self, docker_compose_config):
        """Test that all essential services are defined."""
        services = docker_compose_config["services"]
        expected_services = [
            "kernel",
            "express-api",
            "redis",
            "vector-store",
            "prometheus",
            "grafana",
        ]
        for service in expected_services:
            assert service in services, f"Missing required service: {service}"

    def test_kernel_service_configuration(self, docker_compose_config):
        """Test the configuration of the kernel service."""
        kernel = docker_compose_config["services"]["kernel"]

        # Check dependencies (memory-bus / registry are in-process for now)
        depends_on = kernel.get("depends_on", [])
        assert "redis" in depends_on
        assert "vector-store" in depends_on

        # Check environment configurations
        env = kernel.get("environment", [])
        assert "ARTEMIS_ENV=${ARTEMIS_ENV:-dev}" in env
        assert "ARTEMIS_REDIS_URL=redis://redis:6379" in env
        assert "ARTEMIS_VECTOR_STORE_URL=http://vector-store:6333" in env

        # Check networking
        networks = kernel.get("networks", [])
        assert "artemis" in networks

    def test_security_requirements(self, docker_compose_config):
        """Test that sensitive services enforce security configurations."""
        services = docker_compose_config["services"]

        # Redis password requirement
        redis_command = services["redis"].get("command", "")
        assert "--requirepass" in redis_command
        assert "${REDIS_PASSWORD:?REDIS_PASSWORD must be set}" in redis_command

        # Grafana password requirement
        grafana_env = services["grafana"].get("environment", [])
        assert (
            "GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:?GRAFANA_PASSWORD must be set}"
            in grafana_env
        )

    def test_service_healthchecks(self, docker_compose_config):
        """Test that key services define healthchecks."""
        services = docker_compose_config["services"]

        assert "healthcheck" in services["kernel"], "Kernel missing healthcheck"
        assert "healthcheck" in services["express-api"], (
            "Express API missing healthcheck"
        )

        # Validate healthcheck structure
        kernel_hc = services["kernel"]["healthcheck"]
        assert "curl" in kernel_hc["test"]
        assert kernel_hc.get("interval") == "30s"

    def test_persistent_volumes(self, docker_compose_config):
        """Test that required persistent volumes are properly mapped."""
        volumes = docker_compose_config["volumes"]

        expected_named_volumes = [
            "redis-data",
            "vector-data",
            "prometheus-data",
            "grafana-data",
        ]
        for volume in expected_named_volumes:
            assert volume in volumes, f"Missing named volume: {volume}"

        # Check vector-store volume mount
        vector_store = docker_compose_config["services"]["vector-store"]
        assert "vector-data:/qdrant/storage" in vector_store.get("volumes", [])
