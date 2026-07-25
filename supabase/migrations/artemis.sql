-- =====================================================================
-- Artemis City — event-sourced spine
-- Target: Supabase project "Hebbian" (jdbpmqssmfjzqmeuukkg), Postgres 17
--
-- Apply via:  Supabase Dashboard -> SQL Editor -> paste -> Run
--        or:  supabase db push  (if using the CLI with this in supabase/migrations/)
--
-- Fully idempotent: IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS
-- throughout. Safe to re-run.
--
-- ISOLATION NOTE: everything lives in a dedicated `artemis` schema.
-- The `public` schema of this project hosts UNRELATED grant-management
-- (gm_*) and trading (portfolios/trades/market_events) tables. The project
-- is *named* "Hebbian" but contained nothing Hebbian before this migration.
-- Namespacing makes a wrong-store write structurally impossible rather
-- than merely unlikely.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS artemis;
COMMENT ON SCHEMA artemis IS
  'Artemis City agent infrastructure. Deliberately isolated from public, which hosts unrelated grant-management and trading tables. Truth model: event-sourced - artemis.outcome_events is canonical and append-only; agents/violations/memory are rebuildable projections; hebbian_weights is a VIEW (never a table).';


-- ---------------------------------------------------------------------
-- 1. CANONICAL LOG — append-only, enforced by the engine
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS artemis.outcome_events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ts          timestamptz NOT NULL DEFAULT now(),
  event_type  text NOT NULL,
  ledger      text NOT NULL CHECK (ledger IN ('agent','provider','system')),
  agent_id    text,
  provider    text,
  prov_id     uuid,                          -- ATP parent provenance id
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,

  -- THE 22:18 FIX, AS A CONSTRAINT.
  -- A provider-ledger event cannot be written without naming the provider;
  -- an agent-ledger event cannot be written without naming the agent.
  -- The unattributable failure that vanished on 2026-07-15 at 22:18 is now
  -- not merely discouraged — it is unrepresentable.
  CONSTRAINT ledger_attribution CHECK (
    (ledger = 'agent'    AND agent_id IS NOT NULL) OR
    (ledger = 'provider' AND provider IS NOT NULL) OR
    (ledger = 'system')
  )
);
COMMENT ON TABLE artemis.outcome_events IS
  'Append-only source of truth. UPDATE and DELETE are blocked by trigger. To correct a record, emit a compensating event - history is never rewritten.';
COMMENT ON COLUMN artemis.outcome_events.ledger IS
  'Separate ledgers: agent-caused vs provider/infrastructure-caused outcomes never share a bucket, so reliability and quality signals cannot contaminate each other.';

CREATE INDEX IF NOT EXISTS idx_oe_agent    ON artemis.outcome_events (agent_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_oe_provider ON artemis.outcome_events (provider, ts DESC);
CREATE INDEX IF NOT EXISTS idx_oe_ledger   ON artemis.outcome_events (ledger, ts DESC);
CREATE INDEX IF NOT EXISTS idx_oe_type     ON artemis.outcome_events (event_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_oe_prov     ON artemis.outcome_events (prov_id);
CREATE INDEX IF NOT EXISTS idx_oe_payload  ON artemis.outcome_events USING gin (payload);

-- Append-only enforcement. This is the database-layer equivalent of the
-- frozen MappingProxyType in endpoint_registry.py: mutation fails LOUDLY
-- instead of succeeding silently. Same principle, different layer.
CREATE OR REPLACE FUNCTION artemis.block_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION
    'artemis.% is append-only: % is not permitted. Emit a compensating event instead of rewriting history.',
    TG_TABLE_NAME, TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS oe_no_update ON artemis.outcome_events;
CREATE TRIGGER oe_no_update BEFORE UPDATE ON artemis.outcome_events
  FOR EACH STATEMENT EXECUTE FUNCTION artemis.block_mutation();
DROP TRIGGER IF EXISTS oe_no_delete ON artemis.outcome_events;
CREATE TRIGGER oe_no_delete BEFORE DELETE ON artemis.outcome_events
  FOR EACH STATEMENT EXECUTE FUNCTION artemis.block_mutation();


-- ---------------------------------------------------------------------
-- 2. ATP PROVENANCE CHAIN — what the atp-provenance-logging skill expects
--    (this table did NOT exist anywhere before now — confirm where the
--     skill has actually been writing)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS artemis.agent_logs (
  prov_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_prov_id  uuid REFERENCES artemis.agent_logs(prov_id),
  ts              timestamptz NOT NULL DEFAULT now(),
  entry_kind      text NOT NULL DEFAULT 'agent_action'
                  CHECK (entry_kind IN ('atp_prompt','agent_action')),
  agent_id        text NOT NULL,
  atp_context     text,                      -- the ATP Context field, verbatim
  action_type     text,                      -- tool_call | read | write | execute | delegate | reject
  target          text,
  result          text DEFAULT 'accepted'
                  CHECK (result IN ('accepted','rejected','error')),
  payload_summary text,
  body_sha256     text
);
COMMENT ON TABLE artemis.agent_logs IS
  'ATP provenance chain. Root rows are entry_kind=atp_prompt (parent_prov_id IS NULL); child rows are agent_action entries linking back via parent_prov_id. Append-only.';

CREATE INDEX IF NOT EXISTS idx_al_parent ON artemis.agent_logs (parent_prov_id, ts);
CREATE INDEX IF NOT EXISTS idx_al_agent  ON artemis.agent_logs (agent_id, ts DESC);

DROP TRIGGER IF EXISTS al_no_update ON artemis.agent_logs;
CREATE TRIGGER al_no_update BEFORE UPDATE ON artemis.agent_logs
  FOR EACH STATEMENT EXECUTE FUNCTION artemis.block_mutation();
DROP TRIGGER IF EXISTS al_no_delete ON artemis.agent_logs;
CREATE TRIGGER al_no_delete BEFORE DELETE ON artemis.agent_logs
  FOR EACH STATEMENT EXECUTE FUNCTION artemis.block_mutation();


-- ---------------------------------------------------------------------
-- 3. PROJECTIONS — fast-path current state, always rebuildable from the log
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS artemis.agents (
  id           text PRIMARY KEY,
  name         text NOT NULL,
  role         text,
  status       text NOT NULL DEFAULT 'active',
  capabilities jsonb NOT NULL DEFAULT '[]'::jsonb,
  ts_created   timestamptz NOT NULL DEFAULT now(),
  ts_updated   timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE artemis.agents IS
  'PROJECTION. Derived from outcome_events (registry_add / registry_change). Safe to drop and rebuild.';

CREATE TABLE IF NOT EXISTS artemis.violations (
  id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id text REFERENCES artemis.agents(id),
  provider text,
  kind     text NOT NULL,
  detail   text,
  ts       timestamptz NOT NULL DEFAULT now(),
  cleared  boolean NOT NULL DEFAULT false,
  ledger   text NOT NULL DEFAULT 'agent' CHECK (ledger IN ('agent','provider','system'))
);
COMMENT ON TABLE artemis.violations IS
  'PROJECTION. ledger separates agent-caused from provider/infrastructure-caused violations.';
CREATE INDEX IF NOT EXISTS idx_v_agent ON artemis.violations (agent_id) WHERE NOT cleared;

CREATE TABLE IF NOT EXISTS artemis.memory (
  id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content text NOT NULL,
  tags    jsonb NOT NULL DEFAULT '[]'::jsonb,
  source  text,
  ts      timestamptz NOT NULL DEFAULT now(),
  fts     tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
COMMENT ON TABLE artemis.memory IS
  'PROJECTION. Memory Bus store. fts is a generated tsvector - the Postgres equivalent of the local SQLite FTS5 virtual table.';
CREATE INDEX IF NOT EXISTS idx_mem_fts  ON artemis.memory USING gin (fts);
CREATE INDEX IF NOT EXISTS idx_mem_tags ON artemis.memory USING gin (tags);


-- ---------------------------------------------------------------------
-- 4. HEBBIAN — a FUNCTION + VIEW, never a table.
--
--    There is no row to UPDATE, so a weight CANNOT be asserted. It can
--    only be derived by folding the log. The GET-only Hebbian surface in
--    the API contract stops being a policy and becomes physics.
--
--    w_n = eta * SUM_{i=1..n} ( perf_i * lambda^(n-i) )
--
--    Closed form of w' = lambda*w + eta*perf, which is the recurrence
--    recovered empirically from the July 15 logs.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION artemis.hebbian_fold(
  p_lambda numeric DEFAULT 0.99,
  p_eta    numeric DEFAULT 0.0997
)
RETURNS TABLE (agent_id text, weight numeric, n_events bigint, last_ts timestamptz)
LANGUAGE sql STABLE AS $$
  WITH ordered AS (
    SELECT
      e.agent_id AS aid,
      COALESCE((e.payload->>'performance')::numeric, 1.0) AS perf,
      ROW_NUMBER() OVER (PARTITION BY e.agent_id ORDER BY e.ts) AS i,
      COUNT(*)     OVER (PARTITION BY e.agent_id)           AS n,
      e.ts AS ets
    FROM artemis.outcome_events e
    WHERE e.ledger = 'agent' AND e.agent_id IS NOT NULL
  )
  SELECT
    o.aid,
    ROUND(p_eta * SUM(o.perf * POWER(p_lambda, (o.n - o.i)::numeric)), 4),
    COUNT(*),
    MAX(o.ets)
  FROM ordered o
  GROUP BY o.aid;
$$;
COMMENT ON FUNCTION artemis.hebbian_fold IS
  'Folds outcome_events into Hebbian weights. lambda=0.99 recovered empirically from the July 15 production logs (7.253 -> 7.2791 -> 7.3050 at eta=0.0997). Ceiling w* = eta/(1-lambda) ~= 9.97; neglect half-life ~= 69 events. Pass different params to replay all history under a different formula without touching a single stored row.';

CREATE OR REPLACE VIEW artemis.hebbian_weights AS
  SELECT * FROM artemis.hebbian_fold();
COMMENT ON VIEW artemis.hebbian_weights IS
  'READ-ONLY BY CONSTRUCTION. A view, not a table - there is no row to write. Weights are earned by outcome, never assigned. Mirrors the GET-only Hebbian surface in the API contract.';

-- Provider ledger. Availability lives on its own axis so an outage never
-- contaminates quality history.
CREATE OR REPLACE VIEW artemis.provider_health AS
  SELECT
    provider,
    COUNT(*)                                                AS total_events,
    COUNT(*) FILTER (WHERE event_type = 'provider_failure') AS failures,
    ROUND(1.0 - (COUNT(*) FILTER (WHERE event_type = 'provider_failure')::numeric
                 / NULLIF(COUNT(*), 0)), 4)                 AS availability,
    MAX(ts) FILTER (WHERE event_type = 'provider_failure')  AS last_failure,
    MAX(ts)                                                 AS last_seen
  FROM artemis.outcome_events
  WHERE ledger = 'provider' AND provider IS NOT NULL
  GROUP BY provider;
COMMENT ON VIEW artemis.provider_health IS
  'Provider ledger. The 22:18 Exo outage belongs here, not on any agent weight.';

-- Replay surface backing GET /api/v1/registry/agents/{agent_id}/events
CREATE OR REPLACE VIEW artemis.agent_event_history AS
  SELECT id, ts, event_type, ledger, agent_id, provider, prov_id, payload
  FROM artemis.outcome_events;


-- ---------------------------------------------------------------------
-- 5. RLS — service-role only.
--    These are backend infrastructure tables with no end-user surface.
--    anon / authenticated get nothing. Agents connect with the service key.
-- ---------------------------------------------------------------------
ALTER TABLE artemis.outcome_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE artemis.agent_logs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE artemis.agents         ENABLE ROW LEVEL SECURITY;
ALTER TABLE artemis.violations     ENABLE ROW LEVEL SECURITY;
ALTER TABLE artemis.memory         ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS svc_all ON artemis.outcome_events;
CREATE POLICY svc_all ON artemis.outcome_events TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS svc_all ON artemis.agent_logs;
CREATE POLICY svc_all ON artemis.agent_logs     TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS svc_all ON artemis.agents;
CREATE POLICY svc_all ON artemis.agents         TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS svc_all ON artemis.violations;
CREATE POLICY svc_all ON artemis.violations     TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS svc_all ON artemis.memory;
CREATE POLICY svc_all ON artemis.memory         TO service_role USING (true) WITH CHECK (true);


-- =====================================================================
-- SMOKE TEST — run after applying. Every assertion below should hold.
-- =====================================================================
-- -- 1. An unattributable provider failure is REJECTED (this is the 22:18 fix):
-- INSERT INTO artemis.outcome_events (event_type, ledger) VALUES ('provider_failure','provider');
-- --> ERROR: new row violates check constraint "ledger_attribution"
--
-- -- 2. A correctly attributed one succeeds:
-- INSERT INTO artemis.outcome_events (event_type, ledger, provider, payload)
-- VALUES ('provider_failure','provider','exo',
--         '{"endpoint":"http://localhost:52415/v1/chat/completions","error":"connection refused"}');
--
-- -- 3. History cannot be rewritten:
-- UPDATE artemis.outcome_events SET event_type = 'nope';
-- --> ERROR: artemis.outcome_events is append-only: UPDATE is not permitted.
-- DELETE FROM artemis.outcome_events;
-- --> ERROR: artemis.outcome_events is append-only: DELETE is not permitted.
--
-- -- 4. A weight cannot be asserted:
-- INSERT INTO artemis.hebbian_weights VALUES ('cheater', 99.0, 1, now());
-- --> ERROR: cannot insert into view "hebbian_weights"
--
-- -- 5. Weights emerge from outcomes. Seed three and watch lambda=0.99 work:
-- INSERT INTO artemis.outcome_events (event_type, ledger, agent_id, payload) VALUES
--   ('task_outcome','agent','Summarizer Agent','{"performance":1.0}'),
--   ('task_outcome','agent','Summarizer Agent','{"performance":1.0}'),
--   ('task_outcome','agent','Summarizer Agent','{"performance":1.0}');
-- SELECT * FROM artemis.hebbian_weights;
--
-- -- 6. Replay the SAME history under a different formula, zero data change:
-- SELECT * FROM artemis.hebbian_fold(0.95, 0.0997);   -- faster forgetting
-- SELECT * FROM artemis.hebbian_fold(1.00, 0.0997);   -- no decay (entropy never exported)
-- =====================================================================
