"""PostHog configuration and process-wide client for the FastAPI dashboard."""

import atexit
from functools import lru_cache

from posthog import Posthog
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from the repository environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    artemis_env: str = "development"
    debug: bool = False
    posthog_project_token: str | None = None
    posthog_host: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings so FastAPI dependencies can reuse configuration."""
    return Settings()


posthog_client: Posthog | None = None
_shutdown_registered = False


def _is_development(settings: Settings) -> bool:
    return settings.debug or settings.artemis_env.lower() in {"dev", "development"}


def initialize_posthog() -> Posthog | None:
    """Initialize the process-wide PostHog client when configuration is available."""
    global posthog_client, _shutdown_registered

    if posthog_client is not None:
        return posthog_client

    settings = get_settings()
    missing_key = next(
        (
            key
            for key, value in (
                ("POSTHOG_PROJECT_TOKEN", settings.posthog_project_token),
                ("POSTHOG_HOST", settings.posthog_host),
            )
            if not value
        ),
        None,
    )
    if missing_key:
        if _is_development(settings):
            raise RuntimeError(
                f"{missing_key} variable required by PostHog is missing or un-configured, "
                f"this causes events to be silently missed. This error stops appearing once {missing_key} is configured"
            )
        return None

    project_token = settings.posthog_project_token
    posthog_host = settings.posthog_host
    assert (
        project_token is not None and posthog_host is not None
    )  # nosec B101 - narrows types after the explicit None check above
    posthog_client = Posthog(
        project_api_key=project_token,
        host=posthog_host,
        enable_exception_autocapture=True,
    )
    if not _shutdown_registered:
        atexit.register(shutdown_posthog)
        _shutdown_registered = True
    return posthog_client


def get_posthog_client() -> Posthog | None:
    """Return the shared PostHog client for call sites after lifespan startup."""
    return posthog_client


def flush_posthog() -> None:
    """Flush queued events during FastAPI lifespan shutdown."""
    if posthog_client is not None:
        posthog_client.flush()


def shutdown_posthog() -> None:
    """Shut down the shared client so queued events are delivered before exit."""
    if posthog_client is not None:
        posthog_client.shutdown()
