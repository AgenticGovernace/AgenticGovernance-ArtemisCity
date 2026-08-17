"""Durable delegation-grant and budget-reservation persistence.

``ArtemisAuthorizer`` requires two ports that had no storage anywhere in the
repository: ``DelegationGrantLookup`` (load an immutable persisted grant by id)
and ``DelegationBudgetPolicy`` (is this reservation still allowed to dispatch).
Without them, any delegated child task fails closed at authorization, which is
why the delegated branches of the authorizer were unreachable in production.

Grants are non-bearer ledger records: possessing one grants nothing on its own,
because ``ArtemisAuthorizer`` independently re-verifies that the grant hash
matches the verified authority's delegation reference, that the grant bounds
the current request, and that the reservation is still active. Storage is
therefore integrity-checked but not secret.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Optional

from src.auth.delegation import DelegationGrantV1
from src.runtime_paths import data_path
from src.utils.helpers import logger

RESERVATION_ACTIVE = "active"
RESERVATION_RELEASED = "released"
RESERVATION_EXHAUSTED = "exhausted"


class DelegationStoreError(RuntimeError):
    """The delegation ledger is unavailable or refused an invalid write."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqliteDelegationStore:
    """SQLite-backed delegation grant ledger and budget reservation policy.

    Implements both ``DelegationGrantLookup`` and ``DelegationBudgetPolicy`` so a
    single object can be handed to :class:`~src.routing.authorization.ArtemisAuthorizer`
    for both concerns.
    """

    _GRANTS_DDL = """
        CREATE TABLE IF NOT EXISTS delegation_grants (
            grant_id TEXT PRIMARY KEY,
            grant_hash TEXT NOT NULL,
            root_task_id TEXT NOT NULL,
            parent_task_id TEXT NOT NULL,
            budget_reservation_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """
    _RESERVATIONS_DDL = """
        CREATE TABLE IF NOT EXISTS budget_reservations (
            reservation_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            remaining_units INTEGER,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = data_path(
            "delegation_grants.db", db_path, env_var="ARTEMIS_DELEGATION_DB"
        )
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _initialize_database(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(self._GRANTS_DDL)
                conn.execute(self._RESERVATIONS_DDL)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_grants_parent "
                    "ON delegation_grants(parent_task_id)"
                )
                conn.commit()
        except sqlite3.Error as error:
            raise DelegationStoreError(
                "delegation ledger could not be initialized"
            ) from error

    # -- DelegationGrantLookup ---------------------------------------------

    def get(self, grant_id: str) -> DelegationGrantV1 | None:
        """Return a grant by id, or ``None`` when it is not present."""
        if not isinstance(grant_id, str) or not grant_id.strip():
            return None
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM delegation_grants WHERE grant_id = ?",
                    (grant_id.strip(),),
                ).fetchone()
        except sqlite3.Error as error:
            raise DelegationStoreError("delegation ledger read failed") from error
        if row is None:
            return None
        try:
            # Re-validation on read re-checks the canonical grant hash, so a
            # tampered ledger row cannot be loaded as a usable grant.
            return DelegationGrantV1.model_validate_json(row[0])
        except Exception as error:  # noqa: BLE001 - a corrupt row is not a grant
            logger.error("Persisted delegation grant failed re-validation on read.")
            raise DelegationStoreError(
                "persisted delegation grant failed integrity re-validation"
            ) from error

    # -- Grant issuance -----------------------------------------------------

    def issue(self, grant: DelegationGrantV1) -> DelegationGrantV1:
        """Persist one immutable grant, rejecting a conflicting re-issue.

        Re-issuing the identical grant is idempotent so a retried fan-out does
        not fail; re-issuing a *different* grant under the same id is refused.
        """
        if not isinstance(grant, DelegationGrantV1):
            raise DelegationStoreError("only DelegationGrantV1 records are storable")
        if grant.grant_hash != grant.canonical_hash():
            raise DelegationStoreError("grant hash does not match canonical bytes")

        payload = grant.model_dump_json()
        try:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT grant_hash FROM delegation_grants WHERE grant_id = ?",
                    (grant.grant_id,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != grant.grant_hash:
                        raise DelegationStoreError(
                            "a different grant is already persisted under this id"
                        )
                    return grant
                conn.execute(
                    "INSERT INTO delegation_grants ("
                    "grant_id, grant_hash, root_task_id, parent_task_id, "
                    "budget_reservation_id, expires_at, payload, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        grant.grant_id,
                        grant.grant_hash,
                        grant.root_task_id,
                        grant.parent_task_id,
                        grant.budget_reservation_id,
                        grant.expires_at.astimezone(UTC).isoformat(),
                        payload,
                        _utc_now().isoformat(),
                    ),
                )
                conn.commit()
        except sqlite3.Error as error:
            raise DelegationStoreError("delegation ledger write failed") from error
        return grant

    # -- DelegationBudgetPolicy --------------------------------------------

    def reservation_is_active(self, reservation_id: str) -> bool:
        """Return true only while the referenced reservation may dispatch."""
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            return False
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state, remaining_units, expires_at "
                    "FROM budget_reservations WHERE reservation_id = ?",
                    (reservation_id.strip(),),
                ).fetchone()
        except sqlite3.Error as error:
            raise DelegationStoreError("budget reservation read failed") from error
        if row is None:
            # An unknown reservation is not an active one. Fail closed.
            return False

        state, remaining_units, expires_at = row
        if state != RESERVATION_ACTIVE:
            return False
        if remaining_units is not None and int(remaining_units) <= 0:
            return False
        if expires_at:
            try:
                deadline = datetime.fromisoformat(expires_at)
            except ValueError:
                return False
            if deadline.tzinfo is None:
                return False
            if _utc_now() >= deadline.astimezone(UTC):
                return False
        return True

    def open_reservation(
        self,
        reservation_id: str,
        *,
        remaining_units: Optional[int] = None,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """Create or reopen one active budget reservation."""
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            raise DelegationStoreError("reservation_id must be a non-empty string")
        if remaining_units is not None and remaining_units < 0:
            raise DelegationStoreError("remaining_units cannot be negative")
        if expires_at is not None and (
            expires_at.tzinfo is None or expires_at.utcoffset() is None
        ):
            raise DelegationStoreError("expires_at must be timezone-aware")

        now = _utc_now().isoformat()
        deadline = expires_at.astimezone(UTC).isoformat() if expires_at else None
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO budget_reservations ("
                    "reservation_id, state, remaining_units, expires_at, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(reservation_id) DO UPDATE SET "
                    "state = excluded.state, "
                    "remaining_units = excluded.remaining_units, "
                    "expires_at = excluded.expires_at, "
                    "updated_at = excluded.updated_at",
                    (
                        reservation_id.strip(),
                        RESERVATION_ACTIVE,
                        remaining_units,
                        deadline,
                        now,
                        now,
                    ),
                )
                conn.commit()
        except sqlite3.Error as error:
            raise DelegationStoreError("budget reservation write failed") from error

    def consume_reservation(self, reservation_id: str, units: int = 1) -> bool:
        """Decrement a metered reservation, returning whether it stays active."""
        if units < 0:
            raise DelegationStoreError("consumed units cannot be negative")
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state, remaining_units FROM budget_reservations "
                    "WHERE reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if row is None or row[0] != RESERVATION_ACTIVE:
                    return False
                if row[1] is None:
                    return True  # Unmetered reservations never exhaust.
                remaining = max(0, int(row[1]) - units)
                state = RESERVATION_ACTIVE if remaining > 0 else RESERVATION_EXHAUSTED
                conn.execute(
                    "UPDATE budget_reservations SET remaining_units = ?, "
                    "state = ?, updated_at = ? WHERE reservation_id = ?",
                    (remaining, state, _utc_now().isoformat(), reservation_id),
                )
                conn.commit()
                return state == RESERVATION_ACTIVE
        except sqlite3.Error as error:
            raise DelegationStoreError("budget reservation update failed") from error

    def close_reservation(self, reservation_id: str) -> None:
        """Release one reservation so no further dispatch may use it."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE budget_reservations SET state = ?, updated_at = ? "
                    "WHERE reservation_id = ?",
                    (RESERVATION_RELEASED, _utc_now().isoformat(), reservation_id),
                )
                conn.commit()
        except sqlite3.Error as error:
            raise DelegationStoreError("budget reservation update failed") from error


__all__ = [
    "DelegationStoreError",
    "RESERVATION_ACTIVE",
    "RESERVATION_EXHAUSTED",
    "RESERVATION_RELEASED",
    "SqliteDelegationStore",
]
