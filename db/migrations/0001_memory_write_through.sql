BEGIN;

SELECT pg_advisory_xact_lock(hashtext('artemis:0001_memory_write_through'));

CREATE SCHEMA IF NOT EXISTS artemis;

CREATE TABLE IF NOT EXISTS artemis.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM artemis.schema_migrations
        WHERE version = '0001_memory_write_through'
    ) THEN
        RAISE EXCEPTION 'migration 0001_memory_write_through is already applied'
            USING ERRCODE = 'P0001';
    END IF;
END;
$$;

INSERT INTO artemis.schema_migrations (version)
VALUES ('0001_memory_write_through');

CREATE TABLE artemis.memory_records (
    record_id UUID PRIMARY KEY,
    memory_id UUID NOT NULL,
    relative_path TEXT NOT NULL,
    revision BIGINT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    provenance_id UUID NULL,
    source_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT memory_records_memory_revision_key UNIQUE (memory_id, revision),
    CONSTRAINT memory_records_record_memory_revision_path_key UNIQUE (record_id, memory_id, revision, relative_path),
    CONSTRAINT memory_records_relative_path_relative CHECK (
        relative_path <> ''
        AND left(relative_path, 1) NOT IN ('/', E'\\')
        AND position(E'\\' IN relative_path) = 0
        AND relative_path NOT LIKE '%//%'
        AND relative_path !~ '(^|/)\.(/|$)'
        AND right(relative_path, 1) <> '/'
        AND relative_path = normalize(relative_path, NFC)
        AND relative_path ~ '(^|/)[^/]+\.[^/]+$'
        AND relative_path !~ '(^|/)\.*[^/.][^/]*\.[^/]+/'
        AND relative_path !~ '^[A-Za-z]:[/\\]'
        AND relative_path !~ '(^|[/\\])\.\.([/\\]|$)'
    )
);

CREATE FUNCTION artemis.prevent_memory_record_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'memory records are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER memory_records_immutable
    BEFORE UPDATE OR DELETE ON artemis.memory_records
    FOR EACH ROW EXECUTE FUNCTION artemis.prevent_memory_record_mutation();

CREATE TABLE artemis.memory_heads (
    relative_path TEXT PRIMARY KEY,
    memory_id UUID NOT NULL UNIQUE,
    current_record_id UUID NOT NULL,
    current_revision BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT memory_heads_current_record_fk FOREIGN KEY (
        current_record_id, memory_id, current_revision, relative_path
    ) REFERENCES artemis.memory_records (record_id, memory_id, revision, relative_path),
    CONSTRAINT memory_heads_relative_path_relative CHECK (
        relative_path <> ''
        AND left(relative_path, 1) NOT IN ('/', E'\\')
        AND position(E'\\' IN relative_path) = 0
        AND relative_path NOT LIKE '%//%'
        AND relative_path !~ '(^|/)\.(/|$)'
        AND right(relative_path, 1) <> '/'
        AND relative_path = normalize(relative_path, NFC)
        AND relative_path ~ '(^|/)[^/]+\.[^/]+$'
        AND relative_path !~ '(^|/)\.*[^/.][^/]*\.[^/]+/'
        AND relative_path !~ '^[A-Za-z]:[/\\]'
        AND relative_path !~ '(^|[/\\])\.\.([/\\]|$)'
    )
);

CREATE UNIQUE INDEX memory_heads_relative_path_casefold_key
    ON artemis.memory_heads (lower(relative_path));

CREATE TABLE artemis.memory_outbox (
    event_id UUID PRIMARY KEY,
    record_id UUID NOT NULL,
    memory_id UUID NOT NULL,
    relative_path TEXT NOT NULL,
    revision BIGINT NOT NULL,
    target TEXT NOT NULL CHECK (target = 'obsidian'),
    operation TEXT NOT NULL CHECK (operation IN ('write', 'delete')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'delivered', 'dead')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ NULL,
    locked_by TEXT NULL,
    last_error_code TEXT NULL,
    delivered_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT memory_outbox_record_target_key UNIQUE (record_id, target),
    CONSTRAINT memory_outbox_record_fk FOREIGN KEY (
        record_id, memory_id, revision, relative_path
    ) REFERENCES artemis.memory_records (record_id, memory_id, revision, relative_path),
    CONSTRAINT memory_outbox_relative_path_relative CHECK (
        relative_path <> ''
        AND left(relative_path, 1) NOT IN ('/', E'\\')
        AND position(E'\\' IN relative_path) = 0
        AND relative_path NOT LIKE '%//%'
        AND relative_path !~ '(^|/)\.(/|$)'
        AND right(relative_path, 1) <> '/'
        AND relative_path = normalize(relative_path, NFC)
        AND relative_path ~ '(^|/)[^/]+\.[^/]+$'
        AND relative_path !~ '(^|/)\.*[^/.][^/]*\.[^/]+/'
        AND relative_path !~ '^[A-Za-z]:[/\\]'
        AND relative_path !~ '(^|[/\\])\.\.([/\\]|$)'
    )
);

CREATE INDEX memory_outbox_pending_idx
    ON artemis.memory_outbox (status, next_attempt_at, revision)
    WHERE status IN ('pending', 'processing');

COMMIT;
