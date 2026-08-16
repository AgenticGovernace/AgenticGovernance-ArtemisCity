# Artemis Ingress, Repository Linking, and Release Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert every active CLI, task-loop, HTTP, bridge, MCP, and desktop-facing surface into a thin adapter over the Routing Kernel, while linking Authstructure, Oracle, and Prove through immutable reviewed contracts rather than reverse synchronization.

**Architecture:** A versioned workspace catalog records ownership and default-deny component transfers without local absolute paths. Authstructure publishes and signs the credential-free authentication receipt; Artemis verifies it and authorizes the operation. Existing entry points build untrusted submissions, obtain trusted authority through the verifier, submit to the ledger/kernel once, and render the resulting outcome or stream.

**Tech Stack:** Python 3.12, FastAPI, TypeScript/Express, React/Vite, MCP Python SDK 2.0, Go, YAML/JSON Schema, pytest, Jest, Hatchling

**Spec:** `docs/superpowers/specs/2026-08-16-artemis-routing-kernel-consolidation-design.md`

**Depends on:**
- `docs/superpowers/plans/2026-08-16-artemis-routing-kernel-containment.md`
- `docs/superpowers/plans/2026-08-16-artemis-routing-kernel-core.md`
- `docs/superpowers/plans/2026-08-16-artemis-task-ledger-back-orchestration.md`

## Global Constraints

- Repositories remain physically separate. Do not create a parent Git repository, symlink repositories, or register dirty checkouts as dependencies.
- Every enabled repository link names an immutable commit, exact source paths, destination, contract version, SHA-256 manifest, tests, and human review.
- Never transfer `.git/**`, worktree metadata, secrets, credentials, databases, logs, caches, virtual environments, dependency trees, build output, or vault contents.
- Artemis City owns the Routing Kernel, task ledger, memory orchestration, Hebbian engine, learning policy, and promoted execution-provenance contract.
- Authstructure owns identity, request-proof verification, authentication receipts, and signing semantics. It does not authorize Artemis routes.
- Prove is an incubator until its selected provenance files are committed on a clean branch with an immutable ref. Artemis never depends on its current dirty checkout.
- Oracle is the desktop/provider consumer of generated contracts. Its historical Artemis snapshot and Hebbian copies are never sync sources.
- Authentication precedes ATP and routing at every ingress. Missing production verifier configuration fails closed.
- Browser code holds only a user session; it never embeds `FASTAPI_API_KEY`, `MCP_API_KEY`, or another service credential.
- TypeScript calls Python only through `app/api/lib/pythonBridge.ts` and never reimplements authentication, authorization, routing, provenance, memory, or learning rules.
- No caller can supply trusted `authority`, `principal`, `auth_receipt`, or `delegation` fields.
- No Codex executable, prompt, agent, route, package, response identity, or compatibility alias is created.
- New and touched code follows `docs/CODING_STANDARDS.md`; preserve unrelated dirty work and use path-only commits.

---

### Task 1: Add a default-deny workspace-link catalog and local status generator

**Files:**
- Create: `config/workspaces/workspace-links.v1.schema.json`
- Create: `config/workspaces/workspace-links.v1.yaml`
- Create: `src/workspaces/__init__.py`
- Create: `src/workspaces/contracts.py`
- Create: `src/workspaces/status.py`
- Create: `src/tests/test_workspace_links.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: logical repository IDs and operator-supplied checkout locations.
- Produces: `WorkspaceCatalogV1`, `WorkspaceLinkV1`, `validate_catalog(path)`, and generated `.artemis/workspace-status.v1.json`.

- [ ] **Step 1: Write failing schema and path-safety tests**

  Assert enabled links require a 40-character commit, 64-character SHA-256,
  non-empty source/destination path arrays, contract version, tests, reviewer,
  and review timestamp. Reject local absolute paths, `..`, `.git`, secrets,
  databases, logs, caches, environments, dependency directories, build output,
  vaults, and inbound targets under Artemis routing/Hebbian/learning modules.

  ```python
  def test_enabled_link_requires_immutable_reviewed_source(tmp_path):
      catalog = catalog_with(enabled=True, source_commit=None, reviewer=None)
      with pytest.raises(CatalogError) as denied:
          validate_catalog_data(catalog)
      assert denied.value.code == "enabled_link_incomplete"


  @pytest.mark.parametrize("path", ["/Users/example/repo", "../repo", ".git/config"])
  def test_committed_catalog_rejects_local_or_unsafe_path(path):
      with pytest.raises(CatalogError):
          validate_catalog_data(catalog_with(source_paths=[path]))
  ```

- [ ] **Step 2: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_workspace_links.py -q
  ```

  Expected: collection fails because `src.workspaces` does not exist.

- [ ] **Step 3: Implement strict contracts and protected-domain policy**

  Use `extra="forbid"`, literal `version="artemis.workspace-links/1"`, and
  immutable models. The link method is one of `contract-package`,
  `reviewed-patch`, `pinned-snapshot`, or `one-time-extraction`. Protected
  inbound destinations include:

  ```python
  PROTECTED_INBOUND_PREFIXES = (
      "src/routing/",
      "src/tasks/",
      "src/integration/hebbian_router.py",
      "src/mcp/hebbian_weights.py",
      "src/routing/learning.py",
  )
  ```

- [ ] **Step 4: Seed the catalog with explicit disabled links**

  Add logical repositories `artemis-city`, `authstructure`, `the-oracle`,
  `prove`, and `historical-obsidian-task-loop`. Record the authority map from
  the approved spec. Keep external transfers `enabled: false` until later tasks
  supply immutable canonical refs and manifests. The Authbuild staging commit
  is recorded only as source provenance:
  `17699e2f9b855fcfe9b104691bd4ca6fd7c8ad3f`.

- [ ] **Step 5: Implement generated local status**

  `python -m src.workspaces.status --catalog config/workspaces/workspace-links.v1.yaml --checkout NAME=PATH` resolves
  each supplied checkout, reads HEAD/branch/dirty state without changing it, and
  writes `.artemis/workspace-status.v1.json`. The catalog stores no checkout
  path. Add the generated file to `.gitignore`.

- [ ] **Step 6: Run tests and commit**

  ```bash
  .venv/bin/python -m pytest src/tests/test_workspace_links.py -q
  .venv/bin/python -m src.workspaces.status \
    --catalog config/workspaces/workspace-links.v1.yaml \
    --checkout artemis-city=/Users/pucci/projects/repository/Artemis_City \
    --checkout authstructure=/Users/pucci/projects/repository/the_oracle
  git status --short .artemis/workspace-status.v1.json
  git add config/workspaces src/workspaces src/tests/test_workspace_links.py \
    .gitignore
  git commit -m "feat(workspaces): add immutable repository link catalog"
  ```

  Expected: generated status is ignored and the committed catalog contains no
  `/Users` or `/Volumes` path.

---

### Task 2: Salvage Authstructure receipt-v2 as a reviewed patch

**Files in canonical Oracle repository:**
- Modify the exact 15 paths changed by source commit `17699e2f9b855fcfe9b104691bd4ca6fd7c8ad3f` under `authstructure/`.
- Create: `authstructure/protocol/migrations/receipt-v2-source.yaml`

**Interfaces:**
- Consumes: valid Authbuild object database at `/Users/pucci/projects/repository/local/Authbuild/the_oracle-private-agentic-mesh`.
- Produces: a canonical Oracle commit containing receipt-v2 durability with explicit source provenance and no unrelated history merge.

- [ ] **Step 1: Use a fresh managed worktree from canonical `origin/main`**

  Invoke `superpowers:using-git-worktrees` before execution. Require the
  canonical Oracle checkout to remain untouched, and create branch
  `feature/authstructure-receipt-v2` from `origin/main` in a fresh temporary
  worktree. Do not branch from the local `main`, which currently contains an
  unrelated observer-state commit.

- [ ] **Step 2: Revalidate source identity and base equivalence**

  In the Authbuild clone, require branch
  `dev/authstructure-production-readiness` to resolve exactly to `17699e2`.
  Enumerate its 15 modified paths. For each path, compare the source parent blob
  at `4b8e707a06e5799d60ed8172e4416614928408c7` with canonical Oracle
  `origin/main`; all 15 must be byte-identical.
  Stop if the commit, count, path set, or any base blob differs.

- [ ] **Step 3: Export and inspect a binary-safe patch**

  Create `/private/tmp/authstructure-receipt-v2.patch` from the exact parent to
  commit delta, scoped to the 15 paths. Record patch SHA-256, source/parent
  commits, path hashes before/after, and reviewer in
  `receipt-v2-source.yaml`. Do not add an Authbuild remote or merge unrelated
  histories.

- [ ] **Step 4: Check and apply the exact patch**

  Run `git apply --check` in the fresh canonical worktree, inspect its full
  `--stat` and `--numstat`, then apply it to the index. Confirm the staged set is
  exactly the 15 reviewed paths plus the migration provenance file.

- [ ] **Step 5: Run Authstructure receipt and runtime tests**

  From `authstructure/` run:

  ```bash
  go test ./internal/protocol ./internal/keys ./internal/persistence \
    ./internal/controlplane ./internal/httpapi ./internal/runtime \
    ./internal/operations
  go test ./...
  ```

  Expected: receipt-v2 heads, duplicate-to-original links, response digests,
  migrations, runtime, HTTP, and full Authstructure tests pass.

- [ ] **Step 6: Commit with immutable provenance**

  ```bash
  git add authstructure
  git commit -m "feat(authstructure): promote operational receipt v2"
  ```

  Include source commit and patch SHA-256 in commit trailers. Do not push or
  merge without a separate user-authorized publication step.

---

### Task 3: Publish the generic Authstructure verification and signed receipt contract

**Files in the Task 2 Oracle worktree:**
- Create: `authstructure/api/schemas/authentication-verification-request.schema.json`
- Create: `authstructure/api/schemas/authentication-receipt.schema.json`
- Modify: `authstructure/api/schemas/embed.go`
- Modify: `authstructure/api/openapi.yaml`
- Modify: `authstructure/api/openapi_test.go`
- Create: `authstructure/internal/protocol/authentication.go`
- Create: `authstructure/internal/protocol/authentication_test.go`
- Create: `authstructure/internal/controlplane/verification.go`
- Create: `authstructure/internal/controlplane/verification_test.go`
- Modify: `authstructure/internal/httpapi/server.go`
- Modify: `authstructure/internal/httpapi/server_test.go`
- Modify: `authstructure/internal/runtime/runtime.go`
- Modify: `authstructure/internal/runtime/runtime_test.go`
- Modify: `authstructure/protocol/error-registry.json`

**Interfaces:**
- Consumes: existing `ports.RequestVerifier`, identity authority, bound-token verification, request-proof verification, key ring, and receipt appender.
- Produces: `POST /v1/requests/verify` and version `authstructure.authentication-receipt/1`.

- [ ] **Step 1: Write protocol tests before the endpoint**

  Define a credential-free receipt projection with request ID, authentication
  state, verified identity/capability evidence, verified/expiry times, safe
  reason code, receipt ID/hash/key/signer namespace, and canonical signed
  receipt. Tests reject raw access tokens, token JTI values, certificate PEM,
  private keys, authorization codes, and provider credentials.

- [ ] **Step 2: Write verification-service ordering tests**

  Use recording dependencies and require:

  ```text
  validate transport projection
  -> resolve active certificate identity
  -> verify bound access token and capability evidence
  -> verify exact canonical request proof
  -> append signed authenticated receipt
  ```

  A syntactic rejection before proof processing returns a safe ErrorEnvelope and
  no receipt. A verifier rejection after proof processing appends a signed
  rejected receipt with a registered reason and no principal.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  go test ./internal/protocol ./internal/controlplane ./internal/httpapi
  ```

- [ ] **Step 4: Implement the public contract without Artemis authorization**

  The endpoint accepts the original request method, authority, raw target,
  canonical content metadata, required Authstructure proof headers, and body
  bytes needed to verify the signature. It calls a concrete implementation of
  `ports.RequestVerifier`. It returns identity/capability evidence only; it does
  not run `NewPolicyEvaluation`, select an Artemis capability, choose an agent,
  or decide an Artemis target path.

- [ ] **Step 5: Seal authenticated and post-proof denied receipts**

  Use `TenantReceiptAppender` so receipt ID, sequence, prior hash, namespace
  head, timestamp, signing key, persistence, and outbox insertion are one
  transaction. Canonical response and receipt hashes must match the wire body.

- [ ] **Step 6: Compose the service and update OpenAPI**

  Add the verification dependency to runtime composition. Mount the endpoint on
  the protected surface, document success/signed-denial/syntactic-error shapes,
  and make readiness fail when verifier or receipt appender is absent.

- [ ] **Step 7: Run conformance and full tests, then commit**

  ```bash
  go test ./internal/protocol ./internal/controlplane ./internal/httpapi \
    ./internal/runtime
  go test ./...
  git add authstructure
  git commit -m "feat(authstructure): publish request verification receipts"
  ```

  Record the resulting immutable commit and contract schema hashes for Task 4.

---

### Task 4: Enable the Artemis Authstructure adapter with cross-language fixtures

**Files:**
- Create: `config/workspaces/manifests/authstructure-verifier-v1.sha256`
- Create: `src/tests/fixtures/authstructure/authenticated-receipt-v1.json`
- Create: `src/tests/fixtures/authstructure/rejected-receipt-v1.json`
- Create: `src/tests/fixtures/authstructure/jwks-v1.json`
- Modify: `src/auth/authstructure.py`
- Modify: `src/tests/test_auth_verifier.py`
- Modify: `config/workspaces/workspace-links.v1.yaml`
- Modify: `src/tests/test_workspace_links.py`

**Interfaces:**
- Consumes: the published Oracle commit and exact schema/fixture hashes from Task 3.
- Produces: one enabled `contract-package` link and Artemis receipt verification conformance.

- [ ] **Step 1: Generate fixtures from Authstructure, not by hand**

  Use Authstructure's test signer to emit one authenticated receipt, one signed
  post-proof rejection, and the matching JWKS. Commit only credential-free
  public fixtures. Record each file's SHA-256 in the manifest.

- [ ] **Step 2: Add cross-language verification tests**

  Artemis must verify version, canonical receipt bytes/hash, signature key and
  namespace, audience, request ID, verification time, and principal expiry.
  Tamper each field independently and assert a stable fail-closed error. Assert
  rejection receipts never construct an AuthorityContext.

- [ ] **Step 3: Implement the live HTTP verifier**

  Send the non-loggable `AuthenticationRequest` to
  `/v1/requests/verify`, enforce bounded connection/read timeouts, accept only
  the documented content type/status shapes, verify the signed response locally,
  and return `AuthReceiptV1`. Network, schema, signature, key, audience, clock,
  or hash failure is `auth_verifier_unavailable` or `authentication_rejected`;
  none falls back to API-key authority.

- [ ] **Step 4: Enable the reviewed catalog link**

  Set only the Authstructure verifier link to `enabled: true`, using the Task 3
  canonical commit, exact source schemas/fixtures, Artemis destinations,
  contract version, manifest SHA-256, conformance commands, reviewer, and review
  timestamp. Keep Prove and Oracle memory links disabled.

- [ ] **Step 5: Run both sides' conformance tests and commit Artemis changes**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_auth_verifier.py src/tests/test_workspace_links.py
  git add config/workspaces src/auth/authstructure.py \
    src/tests/test_auth_verifier.py src/tests/test_workspace_links.py \
    src/tests/fixtures/authstructure
  git commit -m "feat(auth): verify Authstructure receipt contract"
  ```

---

### Task 5: Collapse CLI, kernel, plan, and Obsidian loop onto the ledger/kernel

**Files:**
- Modify: `src/__init__.py`
- Modify: `src/launch/main.py`
- Modify: `src/interface/artemis_cli.py`
- Modify: `app/kernel/kernel.py`
- Modify: `app/kernel/__init__.py`
- Modify: `app/kernel/cli.py`
- Modify: `app/kernel/artemis_cli.py`
- Modify: `src/Kernel/__init__.py`
- Modify: `Makefile`
- Modify: `src/tests/test_cli_entrypoints.py`
- Modify: `src/tests/test_kernel_smoke.py`
- Modify: `src/tests/test_orchestrator_coverage.py`

**Interfaces:**
- Consumes: `AuthVerifier`, task ledger, `RoutingKernel.execute/stream`, and task projection worker.
- Produces: all documented module/Makefile compatibility commands as one-task adapters.

- [ ] **Step 1: Write one-delegation tests for every command surface**

  Cover `make cli`, `python -m src`, `make kernel`,
  `python -m app.kernel.cli`, `python -m app.kernel.artemis_cli`,
  `python -m src.interface.artemis_cli`, `python -m src --atp`, typed
  `--plan`, `make orchestrator`, `python -m src.launch.main`,
  `python -m src --orchestrator`, and `python -m src.mcp`. Each test injects one
  recording kernel and asserts exactly one submit/execute call per task.

- [ ] **Step 2: Write no-private-runtime assertions**

  Assert `app.kernel.Kernel` does not construct/import `AgentRouter`, private
  agents, private MemoryBus, or JSON state. Assert plan and Obsidian paths submit
  to the ledger and workers claim atomically; neither updates a note to running
  before a claim.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_cli_entrypoints.py \
    src/tests/test_kernel_smoke.py \
    src/tests/test_orchestrator_coverage.py
  ```

- [ ] **Step 4: Implement typed adapter construction**

  Non-ATP local chat uses the documented typed Execute intent; ATP input always
  remains strict. The adapter sends transport proof to Authstructure, creates a
  trusted root AuthorityContext from the verified receipt, computes input hash
  and idempotency keys, submits the envelope, and calls the kernel once.

- [ ] **Step 5: Preserve inspection-only commands**

  `make hebbian` and `make agent-stats` read canonical learning state and never
  execute a task. Create no installed executable and no old-name compatibility
  prompt.

- [ ] **Step 6: Run focused tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_cli_entrypoints.py \
    src/tests/test_kernel_smoke.py \
    src/tests/test_orchestrator_coverage.py \
    src/tests/test_task_ledger.py
  git add src/__init__.py src/launch/main.py src/interface/artemis_cli.py \
    app/kernel src/Kernel/__init__.py Makefile \
    src/tests/test_cli_entrypoints.py src/tests/test_kernel_smoke.py \
    src/tests/test_orchestrator_coverage.py
  git commit -m "refactor(cli): delegate all commands to Routing Kernel"
  ```

---

### Task 6: Make FastAPI fail closed and remove browser service credentials

**Files:**
- Modify: `app/api/main.py`
- Modify: `src/tests/test_dashboard_api.py`
- Modify: `app/web/frontend/vite.config.ts`
- Modify: `app/web/frontend/src/api.ts`
- Modify: `app/web/frontend/src/vite-env.d.ts`
- Modify: `app/web/frontend/.env.example`

**Interfaces:**
- Consumes: HTTP `AuthenticationRequest`, `AuthorityContextFactory`, and injected Routing Kernel.
- Produces: public liveness, protected readiness/execution, and session-based browser calls.

- [ ] **Step 1: Write fail-closed endpoint matrix tests**

  Parameterize `/api/execute-task`, `/api/execute-all-pending`,
  `/api/cli/execute`, and `/api/cli/execute/stream`. Missing/wrong/unverifiable
  proof must produce 401 or 503 and zero note creation, routing, dispatch,
  memory, provenance child, or learning calls. `/health` may remain public
  liveness; readiness must report verifier availability.

- [ ] **Step 2: Replace request-controlled strictness tests**

  Remove `atp_strict` from `ExecuteInstructionRequest`, set Pydantic
  `extra="forbid"`, and assert caller `authority`, `principal`, `delegation`, or
  strictness fields return 422. Capability/agent remain narrowing constraints.

- [ ] **Step 3: Run FastAPI tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_dashboard_api.py -q
  ```

- [ ] **Step 4: Replace `_require_api_key` with verified authority**

  Use an application factory with injected verifier/kernel in tests. Production
  readiness fails closed when verifier configuration is absent. Both JSON and
  SSE endpoints build one submission/envelope and delegate exactly once. Render
  the same outcome/provenance IDs; SSE `complete` appears only after durable
  finalization.

- [ ] **Step 5: Remove all service-key client injection**

  Delete Vite `define` entries and frontend reads for `FASTAPI_API_KEY`,
  `MCP_API_KEY`, and `VITE_*_API_KEY`. Browser requests use
  `credentials: "include"` for the Authstructure-backed user session. The
  frontend example environment contains public values only.

- [ ] **Step 6: Run Python and frontend checks, then commit**

  ```bash
  .venv/bin/python -m pytest src/tests/test_dashboard_api.py -q
  npm --prefix app/web/frontend run build
  grep -RInE "FASTAPI_API_KEY|MCP_API_KEY|VITE_.*API_KEY" \
    app/web/frontend/src app/web/frontend/vite.config.ts
  git add app/api/main.py src/tests/test_dashboard_api.py \
    app/web/frontend/vite.config.ts app/web/frontend/src/api.ts \
    app/web/frontend/src/vite-env.d.ts app/web/frontend/.env.example
  git commit -m "fix(api): require verified authority before execution"
  ```

  Expected grep result: no browser/runtime service-key references.

---

### Task 7: Collapse Express and the Python bridge onto governed kernel commands

**Files:**
- Modify: `app/api/middleware/auth.ts`
- Modify: `app/api/lib/pythonBridge.ts`
- Modify: `app/api/index.ts`
- Modify: `app/api/v1/llm.ts`
- Modify: `app/api/controllers/atpController.ts`
- Modify: relevant route/controller files that execute or preview tasks
- Modify: `src/api_bridge.py`
- Create: `app/api/__tests__/authstructureAuth.test.ts`
- Create: `app/api/__tests__/routingBridgeRoutes.test.ts`
- Modify: `src/tests/test_api_bridge.py`
- Modify: `src/tests/test_api_bridge_coverage.py`
- Modify: `src/tests/test_api_bridge_llm.py`

**Interfaces:**
- Consumes: raw transport proof, Authstructure verifier, and `RoutingKernel.execute/stream/preview`.
- Produces: bridge commands `routing.execute`, `routing.stream`, and `routing.preview`.

- [ ] **Step 1: Write real TypeScript authentication tests**

  Cover absent verifier config, missing token/session, invalid proof, valid proof,
  and permission/role fields supplied by the caller. TypeScript may extract
  opaque proof but must not invent users, roles, permissions, capabilities, or
  authority. `SKIP_AUTH` is ignored outside an explicit dependency-injected
  development test configuration.

- [ ] **Step 2: Write bridge anti-bypass tests**

  Assert payloads containing `authority`, `principal`, `auth_receipt`, or
  `delegation` are rejected. Assert `llm.chat`, `llm.complete`, `atp.send`, and
  execution routes each delegate to one governed kernel command; no handler
  constructs `LLMAgent` or `HebbianRouter` directly. `atp.route` maps only to
  side-effect-free `routing.preview`.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_api_bridge.py \
    src/tests/test_api_bridge_coverage.py \
    src/tests/test_api_bridge_llm.py
  npm --prefix app/api test -- --runInBand
  ```

- [ ] **Step 4: Extend the bridge envelope safely**

  Send opaque authentication evidence to Python without logging it. Python
  verifies evidence, builds trusted authority, and invokes the kernel. Keep
  stdout reserved for exactly one JSON response/stream protocol; diagnostics
  use stderr/logger. Remove `_run_llm()` and private `_route_atp()` execution
  authority.

- [ ] **Step 5: Make TypeScript controllers thin projections**

  Controllers validate transport shape, call one bridge command, translate
  stable errors to HTTP status, and render the result. They contain no policy,
  registry, memory, provenance, or learning algorithm.

- [ ] **Step 6: Run tests, type checking, and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_api_bridge.py \
    src/tests/test_api_bridge_coverage.py \
    src/tests/test_api_bridge_llm.py
  npm --prefix app/api test -- --runInBand
  npm --prefix app/api run typecheck
  git add app/api src/api_bridge.py src/tests/test_api_bridge.py \
    src/tests/test_api_bridge_coverage.py src/tests/test_api_bridge_llm.py
  git commit -m "refactor(bridge): route execution through governed kernel"
  ```

---

### Task 8: Record safe Oracle/Prove roles and run the full release proof

**Files:**
- Modify: `config/workspaces/workspace-links.v1.yaml`
- Create: `docs/audits/2026-08-16-prove-promotion-readiness.md`
- Create: `docs/audits/2026-08-16-oracle-contract-consumer.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PROJECT_BOUNDARIES.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/MEMORY_BUS.md`
- Modify: `docs/TEST_PLAN.md`
- Modify: `README.md`
- Modify together: `AGENTS.md` and `CLAUDE.md`

**Interfaces:**
- Consumes: completed implementation and current external-repository evidence.
- Produces: disabled-by-default Prove/Oracle promotion records, synchronized docs, and end-to-end release evidence.

- [ ] **Step 1: Keep unsafe external links disabled**

  Record Prove's current facts: no remote, dirty working tree, and provenance
  core/MCP candidates without an immutable committed source. Record Oracle as a
  desktop/provider consumer and Authstructure owner, not an Artemis routing or
  Hebbian source. The catalog entries remain `enabled: false` until a separate
  clean branch, immutable ref, path manifest, conformance tests, and human
  review exist.

- [ ] **Step 2: Document the promotion exit criteria**

  Prove may contribute typed provenance-backed memory receipts, persistence/query
  ports, transport adapters, and conformance tests. Artemis owns the promoted
  schema and runtime; promotion ends when Prove consumes the generated Artemis
  contract. Oracle consumes generated auth/memory/routing contracts and exports
  only named Authstructure/desktop interfaces. Neither can transfer Hebbian
  calculations into Artemis.

- [ ] **Step 3: Align authoritative docs with live behavior**

  Update architecture, boundary, API, memory, test, and operator docs in the
  same change. Keep `AGENTS.md` and `CLAUDE.md` byte-identical. Remove stale
  statements that API keys may live in browser bundles, ATP strictness defaults
  off, `src/Kernel` owns a runtime, or Obsidian note state is authoritative.

- [ ] **Step 4: Run the full canonical test and adapter suites**

  ```bash
  make test
  npm --prefix app/api test -- --runInBand
  npm --prefix app/api run typecheck
  npm --prefix app/web/frontend run build
  make check
  make security
  make package-check
  ```

  Record baseline failures separately from regressions; do not weaken a gate.

- [ ] **Step 5: Inspect live client-visible contracts**

  From installed artifacts and running test transports, inspect representative
  FastAPI OpenAPI, Express envelopes, MCP `inputSchema`, `outputSchema`,
  `structuredContent`, authentication denials, ATP conflicts, no-eligible-agent
  errors, replayed task outcomes, and stream terminal events. Do not substitute
  annotations or JSON-string returns for live evidence.

- [ ] **Step 6: Prove the end-to-end ordering contract**

  Run one authenticated non-stream task, one stream task, one rejected ATP
  task, one child graph, one projection retry, and one finalization recovery.
  Evidence must show authentication/ATP/authorization before dispatch; durable
  outcome and linked provenance before exactly-one learning; atomic child
  admission/fan-in; and no agent replay after durable finalizing state.

- [ ] **Step 7: Prove release identity and repository-link safety**

  Inspect wheel/sdist exact payloads and an isolated wheel install. Search the
  active package, registry, CLI output, HTTP/MCP envelopes, and generated state
  for a Codex runtime identity. Validate every enabled workspace link's commit,
  paths, manifest hash, tests, and review. Confirm no committed catalog/status
  file contains a local absolute checkout path.

- [ ] **Step 8: Commit documentation and proof records**

  ```bash
  cmp AGENTS.md CLAUDE.md
  git diff --check
  git add config/workspaces/workspace-links.v1.yaml \
    docs/audits/2026-08-16-prove-promotion-readiness.md \
    docs/audits/2026-08-16-oracle-contract-consumer.md \
    docs/ARCHITECTURE.md docs/PROJECT_BOUNDARIES.md \
    docs/API_REFERENCE.md docs/MEMORY_BUS.md docs/TEST_PLAN.md \
    README.md AGENTS.md CLAUDE.md
  git commit -m "docs: record governed routing release proof"
  ```
