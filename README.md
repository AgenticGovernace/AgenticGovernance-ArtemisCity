# Artemis City

Artemis City is a governed multi-agent orchestration platform. It combines
credential-free authority evidence, strict Artemis Transmission Protocol (ATP)
intent, policy- and trust-aware routing, durable memory, adaptive learning, and
auditable execution across Python, HTTP, CLI, and browser surfaces.

The platform is built around three promises:

- a request cannot gain capabilities from learned scores or transport metadata;
- canonical results and decisions remain attributable and recoverable; and
- every public surface adapts the same Python-owned domain rules instead of
  reimplementing them.

## What is current

The maintained execution path is:

```text
CLI / FastAPI / Express / trusted in-process ingress
                        |
                        v
          Authentication and authority evidence
                        |
                        v
               ATP or trusted typed intent
                        |
                        v
 IntentResolver -> ArtemisAuthorizer -> EligibilityFilter -> HebbianRanker
                        |
                        v
           Orchestrator -> sandbox -> selected agent
                        |
                        v
       provenance -> memory -> eligible learning -> response
```

Authentication and authorization are separate. Authstructure-compatible
receipts prove credential-free identity and scope evidence; Artemis intersects
that evidence with intent, delegation, target-zone policy, and current
capability policy. Trust, quarantine, sandbox admission, and learned history can
only narrow or rank the authorized candidate set.

The complete ownership map is in
[`docs/REPOSITORY_LAYERS.md`](docs/REPOSITORY_LAYERS.md).

## Current features

### One governed Routing Kernel

`src/routing/kernel.py` is the single in-process routing entry point. It runs
intent resolution, authorization, eligibility, and learned ranking in a
load-bearing order. Trusted local callers use an explicit system authority so
their routes remain distinguishable in audit; they do not bypass the kernel.

The currently reviewed ATP execution domain covers `llm_chat`, `reasoning`,
`text_generation`, and `text_summarization`. Tasks outside that code-pinned
domain use the documented legacy compatibility path with a warning instead of
being silently assigned to a general chat agent.

### Typed ATP validation

`src/validation/` exposes `ATPValidationService`, a transport-neutral facade over
the canonical ATP parser and validator. It provides immutable parse and
validation reports, stable issue codes, strict input models, and safe hash or
bracket header formatting.

The library is implemented and tested. It does not yet have a dedicated public
HTTP or MCP transport; existing Express ATP routes continue to use the Python
bridge commands listed in [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

### Credential-free authority contracts

`src/auth/` defines strict immutable contracts for principals, verified scopes,
authentication receipts, acting/requesting parties, and bounded delegation.
Credential-bearing field names and proof echoes are rejected recursively.

The Authstructure adapter validates versioned canonical receipt artifacts and
returns only stable, credential-free denial codes. Production configuration
intentionally fails closed until the external Authstructure verifier contract is
enabled and conformant.

### Canonical memory with derived projections

`src/integration/memory_bus.py` supports a reversible legacy mode and explicit
PostgreSQL/Neon modes. In SQL mode, an immutable revision, current head, and
Obsidian projection outbox event commit atomically. Vector and Obsidian
projections are derived: projection failure leaves the canonical write accepted
and pending instead of erasing or misreporting it.

Exact reads, list operations, and statistics come from SQL in SQL mode. Semantic
search uses the derived vector index; vault keyword scanning remains a
legacy-mode behavior. Full guarantees are in
[`docs/MEMORY_BUS.md`](docs/MEMORY_BUS.md).

### Verified model execution and governed compression

`LLMAgent` records redacted Exo wire evidence: concrete endpoint, status,
request/response identifiers, observed model, latency, attempts, output length,
and SHA-256. Provider availability failures and cancellations are not treated as
agent-quality failures and cannot train trust or Hebbian weights.

Long successful output is preserved as an exact non-embedded artifact before a
governed `text_summarization` child is routed. The final result links the raw
artifact and exposes compressed follow-on context without pretending locally
generated fallback text came from Exo.

### Security-hardened boundaries

Maintained boundaries use path containment checks, safe temporary replacement,
stable error codes, request-log normalization, credential redaction, explicit
provider failure classification, and fail-closed configuration. Security and
dependency gates run through `make security` and the CI promotion workflow.

## Runtime surfaces

| Surface                   | Path                | Role                                                             | Run command              |
| ------------------------- | ------------------- | ---------------------------------------------------------------- | ------------------------ |
| Python orchestration core | `src/`              | Agents, routing, auth, ATP validation, governance, memory, tests | `make run`               |
| In-process kernel         | `app/kernel/`       | Packaged local router and concrete kernel agents                 | `make kernel`            |
| FastAPI dashboard         | `app/api/main.py`   | Dashboard-oriented `/api/*` backend                              | `make api`               |
| TypeScript Express API    | `app/api/**/*.ts`   | External `/api/v1/*` boundary                                    | `make express-api`       |
| JSON bridge               | `src/api_bridge.py` | Express-to-Python stdin/stdout protocol                          | Spawned by Express       |
| React dashboard           | `app/web/frontend/` | Operator UI; Vite proxies `/api/*` to FastAPI                    | `make frontend`          |
| Launch demos              | `src/launch/`       | Maintained CLI demonstrations                                    | `make demo`              |
| Concept demos             | `Concept_Demos/`    | Static prototypes and compatibility examples                     | `python3 -m http.server` |

`src/Artemis Agentic Memory Layer/` is a working Express/TS service (`make server`)
that fronts the Obsidian Local REST API. It is not registered in the root npm
workspace, and despite its name it is branding-only — plain REST, no
`@modelcontextprotocol/sdk` dependency, not an authoritative Model Context
Protocol implementation. The real MCP SDK is used under `services/mcp/`, where
Python servers (`artemis-validation`, `artemis-memory`) adapt `src/` domain
services over the official `mcp` package. See
[`docs/PROJECT_BOUNDARIES.md`](docs/PROJECT_BOUNDARIES.md) for the full surface
map.

## Repository map

```text
.
├── app/
│   ├── api/                    # FastAPI dashboard + TS Express boundary
│   ├── kernel/                 # Packaged in-process kernel
│   ├── scripts/                # Operational utilities
│   └── web/frontend/           # React/Vite operator dashboard
├── Concept_Demos/              # Static prototypes
├── config/
│   ├── environments/           # dev, staging, and prod policy profiles
│   ├── service-env/            # Tracked templates for external/nested services
│   ├── environment-contract.yaml # Runtime targets and variable ownership
│   └── routing/                # Reviewed intent and authorization policy
├── docs/                       # Authoritative architecture and operations docs
├── monitoring/                 # Prometheus and alert configuration
├── src/
│   ├── agents/                 # Capability-specific agents and ATP primitives
│   ├── auth/                   # Credential-free authority contracts/verifier
│   ├── governance/             # Trust, approval, checkpoint, rollback rules
│   ├── integration/            # Registry, memory, sandbox, learning adapters
│   ├── launch/                 # Canonical CLI and maintained demonstrations
│   ├── mcp/                    # Orchestrator, Hebbian storage, vector store
│   ├── memory/                 # Memory backends and compatibility integration
│   ├── obsidian_integration/   # Validated vault paths and Markdown adapters
│   ├── routing/                # Shared Routing Kernel and policy stages
│   ├── tests/                  # Canonical Python test suite
│   ├── validation/             # Typed ATP parse/validate/format facade
│   └── api_bridge.py           # TypeScript-to-Python JSON bridge
├── Makefile                    # Root development and service contract
├── pyproject.toml              # Canonical Python package manifest
├── package.json                # Root Node workspace coordinator
└── setup_secrets.sh            # Environment provisioning and drift checks
```

The Python wheel includes `src/` and `app/kernel/`. It excludes dashboard,
frontend, and operational application directories so those application modules
are not bundled into core consumers.

## Quick start

### Prerequisites

- Python 3.12
- Node.js 24 or newer for the checked-in root workspace
- `uv`, `make`, and npm
- optional Obsidian Local REST API, Exo, PostgreSQL/Neon, Qdrant, or hosted
  embedding services for the features you enable

### Install

```bash
make venv
source .venv/bin/activate
make install-dev
make install-web
```

The root Makefile owns dependency installation. Do not create a second package
installation inside `app/api` or `app/web/frontend`.

### Configure

```bash
./setup_secrets.sh              # preserve values and backfill missing settings
./setup_secrets.sh --check      # read-only drift detection
./setup_secrets.sh --regenerate # rotate Artemis-owned generated secrets
```

Root `.env` is the only local operator source. The provisioner reconciles it
against `.env.example`, then generates exact service views for Express, Vite,
the Python core, the Obsidian REST shell, the Memory MCP server, and the
provenance mesh. `config/environment-contract.yaml` owns that target list and
the source-to-derived mappings. Service `.env` files are outputs; edit root
`.env` and rerun setup instead of editing a generated view.

Only six Artemis-owned secrets are generated or rotated: `MCP_API_KEY`,
`FASTAPI_API_KEY`, `ARTEMIS_API_KEY_DEFAULT`, `REDIS_PASSWORD`,
`QDRANT_API_KEY`, and `GRAFANA_PASSWORD`. Provider credentials and operator
settings such as database URLs, MCP bearer identity, `OPENAI_API_KEY`,
`EXO_API_KEY`, `HF_TOKEN`, `OBSIDIAN_API_KEY`, `ANTHROPIC_API_KEY`, and
`GITHUB_TOKEN` are never fabricated or rotated.

Use `ARTEMIS_ENV=dev|staging|prod` to select the environment profile. Use
`ARTEMIS_MEMORY_BACKEND=postgres` or `neon` only with valid SQL configuration;
explicit SQL mode fails closed instead of silently falling back to legacy
memory.

### Validate

```bash
make env-check    # code/profile/template contract; safe for PR CI
make env-fix      # deterministic policy repair; never touches .env files
make env-live-check # manifest-declared endpoint checks
make check       # Black, Ruff, isort, and MyPy gates
make test        # canonical Python suite
make security    # static, dependency, and secret checks
make docs        # strict MkDocs build, including rendered docstrings
```

`make setup-hooks` installs pre-commit, pre-push, and commit-message hooks.
Pre-commit runs the deterministic policy fixer; pre-push performs the read-only
live dependency checks.

Run the full operator gate with:

```bash
make all
```

### Start services

In separate terminals:

```bash
make api          # FastAPI dashboard on :8000
make frontend     # Vite dashboard on :5173, proxying /api to :8000
make express-api  # external TypeScript API on :4000
```

The frontend talks to FastAPI. External versioned clients use Express. Express
invokes Python-owned behavior only through `app/api/lib/pythonBridge.ts` and
`src/api_bridge.py`.

### Run the CLI and demos

```bash
make run
make demo
make hebbian
make agent-stats AGENT="Research Agent"
```

`make help` lists every supported root command.

## Development rules

- Start with [`AGENTS.md`](AGENTS.md) and
  [`.github/instructions/instructions.md`](.github/instructions/instructions.md).
- Keep `AGENTS.md` and `CLAUDE.md` byte-for-byte identical.
- Add bridge commands in Python first, then expose them through a thin Express
  controller and route.
- Keep the Routing Kernel as the single in-process routing entry point.
- Do not let trust, Hebbian history, or requested metadata invent a capability.
- Preserve full provider output before governed compression.
- Keep diagnostics off MCP stdio stdout.
- Document public contracts and non-obvious behavior with Google-style Python
  docstrings; avoid comments that merely repeat annotations.
- Treat generated, vendored, archived, test-only, and reverse-sync-held files as
  outside broad documentation cleanups.

The active coding and test requirements are in
[`docs/CODING_STANDARDS.md`](docs/CODING_STANDARDS.md) and
[`docs/TEST_PLAN.md`](docs/TEST_PLAN.md).

## CI and branch model

GitHub Actions owns the active source, test, security, lineage, live, and
promotion gates. This checkout has no CircleCI configuration:

```text
feature/* --PR--> dev --validated promotion--> staging --> prod
```

Pull requests run only deterministic source gates. Promotions then pass through
the protected `staging` and `prod` GitHub Environments, whose reviewer and wait
settings own approvals, before either branch is fast-forwarded. See
[`docs/CICD.md`](docs/CICD.md) and [`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md).

## Documentation

- [`docs/index.md`](docs/index.md) — documentation home
- [`docs/REPOSITORY_LAYERS.md`](docs/REPOSITORY_LAYERS.md) — ownership and data
  flow for every maintained layer
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design and invariants
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) — current HTTP/bridge and ATP
  contracts
- [`docs/PYTHON_API.md`](docs/PYTHON_API.md) — rendered auth and ATP validation
  docstrings
- [`docs/MEMORY_BUS.md`](docs/MEMORY_BUS.md) — canonical memory protocol
- [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) — trust, approval, and rollback
- [`docs/PROJECT_BOUNDARIES.md`](docs/PROJECT_BOUNDARIES.md) — active,
  transitional, and unavailable project surfaces
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — environment and secret ownership

## License

Artemis City is licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).
