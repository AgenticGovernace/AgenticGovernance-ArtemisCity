# Deployment Guide

## Prerequisites

### System Requirements

**Hardware:**

- CPU: 4+ cores recommended (2+ minimum)
- Memory: 8GB recommended (4GB minimum)
- Storage: 50GB free (SSD recommended)
- Network: 100 Mbps stable connectivity

**Software:**

- Docker 20.10+ or Podman 3.0+
- Docker Compose 1.29+
- Python 3.12 (for CLI tools)
- Git 2.30+

### Infrastructure Dependencies

1. **PostgreSQL / Neon memory ledger** (canonical memory storage)

   - PostgreSQL 16-compatible service; Neon is supported
   - Pooled endpoint for runtime traffic and direct endpoint for manually run
     `psql` migrations
   - Backup and retention policy for immutable revisions and the outbox
2. **Obsidian Vault** (human-readable projection)

   - Local filesystem or network mount
   - At least 10GB initial capacity
   - Projection target, not canonical memory authority in SQL mode
   - Regular backup strategy
3. **Vector Store** (semantic search)

   - Qdrant 1.0+ (recommended)
   - Weaviate 1.0+ (alternative)
   - Milvus 2.0+ (alternative)
   - Minimum 5GB storage
4. **Message Broker** (async operations)

   - Redis 6.0+ (recommended)
   - RabbitMQ 3.8+ (alternative)
   - For Hebbian sync batching and task queuing
5. **Monitoring Stack**

   - Prometheus 2.30+ (metrics)
   - Grafana 8.0+ (visualization)
   - Optional: Loki, Tempo for logs/traces

### Network Ports

| Service                                                    | Port          | Protocol | Status                                                 |
| ---------------------------------------------------------- | ------------- | -------- | ------------------------------------------------------ |
| Kernel API (FastAPI dashboard,`app/api/main.py`)         | 8000          | HTTP     | shipped                                                |
| Express API (`/api/v1/*` boundary, `app/api/index.ts`) | 4000          | HTTP     | shipped                                                |
| Memory Bus                                                 | 8001          | HTTP     | **in-process inside `kernel`** — future split |
| Agent Registry                                             | 8002          | HTTP     | **in-process inside `kernel`** — future split |
| Prometheus                                                 | 9090          | HTTP     | shipped                                                |
| Grafana                                                    | 3000          | HTTP     | shipped                                                |
| Redis                                                      | 6379          | TCP      | shipped                                                |
| Qdrant                                                     | 6333          | HTTP     | shipped                                                |
| Obsidian                                                   | (file system) | N/A      | shipped                                                |

> Memory Bus and Agent Registry are currently library modules
> (`src/integration/memory_bus.py`, `src/integration/agent_registry.py`)
> consumed by the orchestrator inside the `kernel` container. They are
> reserved ports — when those modules graduate to standalone HTTP
> services, add matching `memory-bus` and `registry` entries to
> `docker-compose.yaml` that build from `Dockerfile.python` with their
> own CMDs.

## Docker Setup

### Directory Structure

```
artemis-city/
├── docker-compose.yaml
├── Dockerfile
├── .env.example
├── docs/
├── src/
│   ├── kernel/
│   ├── memory_bus/
│   ├── registry/
│   ├── sandbox/
│   ├── governance/
│   └── hebbian/
├── config/
│   ├── prometheus.yml
│   ├── vector_store_config.yaml
│   └── sandbox_policies.yaml
├── vault/                    # Obsidian vault mount
├── data/
│   ├── checkpoints/
│   ├── logs/
│   └── metrics/
└── scripts/
    ├── init_vault.sh
    ├── health_check.sh
    └── migrate.sh
```

### Docker Compose Configuration

```yaml
version: '3.8'

services:
  # Core Artemis Services
  kernel:
    build:
      context: .
      dockerfile: Dockerfile
      target: kernel
    ports:
      - "8000:8000"
    environment:
      - ARTEMIS_ENV=prod
      - ARTEMIS_LOG_LEVEL=INFO
      - ARTEMIS_REGISTRY_URL=http://registry:8002
      - ARTEMIS_MEMORY_BUS_URL=http://memory-bus:8001
      - ARTEMIS_REDIS_URL=redis://redis:6379
    depends_on:
      - registry
      - memory-bus
      - redis
    volumes:
      - ./vault:/data/vault
      - ./data/checkpoints:/data/checkpoints
      - ./logs:/var/log/artemis
    networks:
      - artemis
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  memory-bus:
    build:
      context: .
      dockerfile: Dockerfile
      target: memory-bus
    ports:
      - "8001:8001"
    environment:
      - ARTEMIS_ENV=prod
      - OBSIDIAN_VAULT_PATH=/data/vault
      - ARTEMIS_VECTOR_STORE_URL=http://vector-store:6333
      - ARTEMIS_REDIS_URL=redis://redis:6379
      - ARTEMIS_MEMORY_WRITE_TIMEOUT_MS=200
      - ARTEMIS_MEMORY_SYNC_TIMEOUT_MS=300
    depends_on:
      - vector-store
      - redis
    volumes:
      - ./vault:/data/vault
    networks:
      - artemis
    restart: unless-stopped

  registry:
    build:
      context: .
      dockerfile: Dockerfile
      target: registry
    ports:
      - "8002:8002"
    environment:
      - ARTEMIS_ENV=prod
      - ARTEMIS_REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    networks:
      - artemis
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Infrastructure Services
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - artemis
    restart: unless-stopped
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD:?REDIS_PASSWORD must be set}

  vector-store:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - vector-data:/qdrant/storage
    networks:
      - artemis
    restart: unless-stopped
    environment:
      - QDRANT_API_KEY=${QDRANT_API_KEY:?QDRANT_API_KEY must be set}

  # Monitoring Stack
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    networks:
      - artemis
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:?GRAFANA_PASSWORD must be set}
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana-data:/var/lib/grafana
      - ./config/grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./config/grafana/datasources:/etc/grafana/provisioning/datasources
    networks:
      - artemis
    depends_on:
      - prometheus
    restart: unless-stopped

volumes:
  redis-data:
  vector-data:
  prometheus-data:
  grafana-data:

networks:
  artemis:
    driver: bridge
```

### Environment Configuration

`config/environment-contract.yaml` is the target and ownership manifest. Root
`.env` is the sole local operator source; checked-in service templates define
the shape of generated views. Do not infer completeness from an existing
`.env`, and do not preserve a conflicting value in a service view. Edit root
`.env` and run `./setup_secrets.sh` to reconcile all consumers.

The provisioner uses four value classes:

- **Owned secrets** (`MCP_API_KEY`, `FASTAPI_API_KEY`,
  `ARTEMIS_API_KEY_DEFAULT`, `REDIS_PASSWORD`, `QDRANT_API_KEY`, and
  `GRAFANA_PASSWORD`) are generated on first setup and rotated with
  `./setup_secrets.sh --regenerate`. The shared/API secrets are propagated to
  their declared runtime consumers.
- **Derived values** such as `ARTEMIS_VECTOR_STORE_API_KEY`,
  `VITE_FASTAPI_API_KEY`, and `VITE_MCP_API_KEY` follow their declared root
  sources so consumers cannot drift.
- **Ordinary defaults** fill missing root declarations. Root values are
  preserved; generated service views are replaced from the root plus their
  templates.
- **Operator-supplied memory and vault settings**
  (`ARTEMIS_MEMORY_DATABASE_URL`, `ARTEMIS_MEMORY_MIGRATION_DATABASE_URL`,
  `OBSIDIAN_VAULT_PATH`, and `OBSIDIAN_API_KEY`) are preserved in both normal
  sync and `--regenerate` mode. They are never generated or rotated.
- **Provider credentials and optional values** (`OPENAI_API_KEY`, `EXO_API_KEY`,
  `HF_TOKEN`, `OBSIDIAN_API_KEY`, and similar) remain blank until an operator
  supplies them; the script never fabricates them.

Runtime template locations are:

| Runtime | Template |
|---|---|
| Python core, FastAPI, and Docker Compose | `.env.example` |
| TypeScript Express API and bridge | `app/api/.env.example` |
| React/Vite dashboard | `app/web/frontend/.env.example` |
| Python source runtime | `src/.env.example` |
| Obsidian REST shell | `src/Artemis Agentic Memory Layer/.env.example` |
| Memory MCP server | `services/mcp/artemis-memory/.env.example` |
| Nested provenance mesh | `config/service-env/provenance.env.example` |

**Create `.env` file:**

```bash
# Deployment Environment
ARTEMIS_ENV=prod
ARTEMIS_LOG_LEVEL=INFO

# Service URLs
ARTEMIS_KERNEL_URL=http://kernel:8000
ARTEMIS_REGISTRY_URL=http://registry:8002
ARTEMIS_MEMORY_BUS_URL=http://memory-bus:8001

# Storage
OBSIDIAN_VAULT_PATH=/data/vault
ARTEMIS_VECTOR_STORE_URL=http://vector-store:6333
ARTEMIS_VECTOR_STORE_API_KEY=${QDRANT_API_KEY}

# Message Broker
ARTEMIS_REDIS_URL=redis://redis:6379
REDIS_PASSWORD=<generate-a-strong-random-secret>

# Memory Bus
ARTEMIS_MEMORY_BACKEND=legacy
# Operator supplied: runtime uses Neon/Postgres pooled URL; do not commit it.
ARTEMIS_MEMORY_DATABASE_URL=
# Operator supplied: direct endpoint for manual psql migration only; do not commit it.
ARTEMIS_MEMORY_MIGRATION_DATABASE_URL=
ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS=10
ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS=5000
ARTEMIS_MEMORY_OUTBOX_MAX_ATTEMPTS=10
ARTEMIS_MEMORY_OUTBOX_RETRY_BASE_SECONDS=1
ARTEMIS_MEMORY_WRITE_TIMEOUT_MS=200
ARTEMIS_MEMORY_SYNC_TIMEOUT_MS=300
ARTEMIS_MEMORY_CACHE_SIZE_MB=100
ARTEMIS_MEMORY_QUEUE_MAX_BYTES=10485760

# Embedding
ARTEMIS_EMBEDDING_MODEL=text-embedding-3-large
ARTEMIS_EMBEDDING_BATCH_SIZE=100
ARTEMIS_EMBEDDING_API_KEY=${OPENAI_API_KEY}

# Governance
ARTEMIS_APPROVAL_TIER1_ENABLED=true
ARTEMIS_APPROVAL_TIER2_TIMEOUT_HOURS=24
ARTEMIS_APPROVAL_TIER3_TIMEOUT_HOURS=72
ARTEMIS_AUTO_ROLLBACK_ON_ERRORS=true
ARTEMIS_AUTO_ROLLBACK_ERROR_THRESHOLD=0.05

# Sandbox
ARTEMIS_SANDBOX_VIOLATION_QUARANTINE_COUNT=3
ARTEMIS_SANDBOX_VIOLATION_DECAY_DAYS=30

# Security
QDRANT_API_KEY=<generate-a-strong-random-secret>
GRAFANA_PASSWORD=<generate-a-strong-random-secret>

# Monitoring
ARTEMIS_PROMETHEUS_ENABLED=true
ARTEMIS_METRICS_PORT=9090
ARTEMIS_LOG_FORMAT=json
```

### Canonical memory ledger rollout

Keep `ARTEMIS_MEMORY_BACKEND=legacy` until the database migration and rollout
checks are complete. To enable the canonical ledger, set the backend to
`postgres` or `neon` and provide both database URLs through the deployment
secret mechanism:

- `ARTEMIS_MEMORY_DATABASE_URL` is the pooled runtime endpoint used by Artemis
  processes.
- `ARTEMIS_MEMORY_MIGRATION_DATABASE_URL` is the direct endpoint used only by
  the explicit manual `psql` command below; do not route application traffic
  through it. The application does not run DDL and no repository migration
  runner currently consumes this variable.
- `ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS` bounds connection establishment.
- `ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS` is a required positive integer and
  becomes the PostgreSQL statement deadline on every runtime connection. The
  two outbox retry values are reserved/inert in this first slice; they are not
  controls for an implemented worker or retry loop.

Invalid backend selection or a missing/invalid database setting is surfaced as
`MEMORY_DATABASE_CONFIGURATION_ERROR` (HTTP 503). Connections are lazy; a
runtime connection or query failure after configuration is valid is
`MEMORY_STORAGE_UNAVAILABLE` (HTTP 503). Exact SQL reads do not initialize the
local vector or vault projection, and writes commit SQL before attempting to
construct either projection.

Compose forwards the selected backend, pooled runtime URL, connection timeout,
and statement timeout to both `kernel` and `express-api`, because the public
Express boundary launches its own Python bridge process. Both services mount
the same `/data/vault` Obsidian projection. The direct migration URL is
intentionally not injected into either long-running container; use it only from
the operator-controlled migration shell. The Express image installs the bridge
dependency boundary from `requirements-bridge.txt`, including the PostgreSQL
driver. Verify an actual image build in prepared CI before rollout; the source
and Compose structural tests do not substitute for a Docker-engine build.

The current vector factory supports local SQLite and the existing direct
PostgreSQL/Supabase-compatible adapter; it does **not** consume
`ARTEMIS_VECTOR_STORE_URL`. Consequently the Compose Qdrant service is not yet
the MemoryBus semantic projection, and the Express container's default local
SQLite vector file is ephemeral. Do not claim durable or cross-container
semantic search in this first slice. Before enabling it, select and verify one
shared persistent vector adapter or add a deterministic rebuild worker from
canonical SQL. Exact SQL reads/writes and Obsidian projection are unaffected by
this limitation.

Never place either URL, an Obsidian bearer token, or a populated vault path in
a committed `.env.example`, log, or browser-facing configuration. The
provisioner preserves supplied values; it does not validate connectivity or
apply migrations. Apply the schema explicitly from an operator-controlled
shell:

```bash
psql "$ARTEMIS_MEMORY_MIGRATION_DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/0001_memory_write_through.sql
```

The migration is internally atomic: it holds a transaction-scoped advisory
migration lock, records `0001_memory_write_through` before domain DDL, and
commits the version row and schema together. A successful repeat fails before
domain DDL with SQLSTATE `P0001` and `migration 0001_memory_write_through is
already applied`. Live first application and repeat-application behavior have
not been verified against PostgreSQL and
are required rollout gates; unit tests validate only the migration's structure.

In SQL mode, a completed database commit plus failed Obsidian projection is
returned as `accepted` with `sync_pending=true`. It is durable and must be
manually retried by replaying the same write with the explicitly retained
idempotency key after connectivity returns; do not perform a competing direct
vault write. If the caller omits the key, the bridge creates and returns a new
UUID for that invocation, and a later keyless call is a new revision rather
than a retry. The first slice has no background worker, automatic backoff, or
dead-letter transition, so pending outbox rows remain pending unless replayed.

For this initial rollout, run one task-executing orchestrator worker; atomic
multi-worker task claims are not implemented yet. Existing deployments must
also rebuild or reset the derived vector index once because canonical path IDs
replace the older underscore-normalized IDs. Build `app/api` before starting
the Express service because `app/api/dist` is an ignored generated artifact.

## Installation & Startup

### Step 1: Initialize Vault

```bash
# Create vault directory structure
./scripts/init_vault.sh

# Expected output:
# ✓ Created vault root
# ✓ Created subdirectories (tasks, agents, decisions, etc.)
# ✓ Initialized git tracking
```

### Step 2: Start Services

```bash
# Pull latest images
docker-compose pull

# Start all services
docker-compose up -d

# Verify services are healthy
docker-compose ps
```

Expected output:

```
NAME                COMMAND             STATUS              PORTS
kernel              "python -m..."      Up (healthy)        8000->8000/tcp
memory-bus          "python -m..."      Up (healthy)        8001->8001/tcp
registry            "python -m..."      Up (healthy)        8002->8002/tcp
redis               "redis-server"      Up (healthy)        6379->6379/tcp
vector-store        "/qdrant ..."       Up (healthy)        6333->6333/tcp
prometheus          "/bin/prometheus"   Up (healthy)        9090->9090/tcp
grafana             "/run.sh"           Up (healthy)        3000->3000/tcp
```

### Step 3: Health Checks

```bash
# Run comprehensive health check
./scripts/health_check.sh

# Check specific services
curl http://localhost:8000/health     # Kernel
curl http://localhost:8001/health     # Memory Bus
curl http://localhost:8002/health     # Registry
```

### Step 4: Verify Integrations

```bash
# Test memory bus write-through
curl -X POST http://localhost:8001/test/write \
  -H "Content-Type: application/json" \
  -d '{"content": "test", "path": "test.md"}'

# Test agent registry
curl http://localhost:8002/agents

# Test vector store
curl http://localhost:6333/health
```

## Monitoring Setup

### Prometheus Configuration

**File: `config/prometheus.yml`**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    environment: production

scrape_configs:
  - job_name: 'artemis'
    static_configs:
      - targets:
        - 'kernel:8000'
        - 'memory-bus:8001'
        - 'registry:8002'
    metrics_path: '/metrics'

  - job_name: 'redis'
    static_configs:
      - targets: ['redis:6379']

  - job_name: 'vector-store'
    static_configs:
      - targets: ['vector-store:6333']
    metrics_path: '/metrics'
```

### Grafana Dashboards

**Key Dashboards to Create:**

1. **System Overview**

   - Kernel throughput (tasks/sec)
   - Agent availability
   - Error rates (p50/p95/p99)
2. **Memory Bus Health**

   - Write latency (histogram)
   - Sync lag (Obsidian → Vector Store)
   - Cache hit ratio
3. **Governance Metrics**

   - Approval times by tier
   - Sandbox violations
   - Rollback frequency
4. **Agent Performance**

   - Per-agent success rate
   - Trust score trends
   - Hebbian weight distribution

### Alerting Rules

**File: `config/prometheus/alerts.yml`**

```yaml
groups:
  - name: artemis_alerts
    rules:
      - alert: KernelHighErrorRate
        expr: rate(artemis_kernel_errors_total[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High kernel error rate"

      - alert: MemoryBusLowLatency
        expr: artemis_memory_write_latency_p95 > 300
        for: 5m
        annotations:
          summary: "Memory bus write latency exceeding SLA"

      - alert: SandboxViolationQuarantine
        expr: increase(artemis_sandbox_violations_total[1h]) >= 3
        annotations:
          summary: "Agent quarantined due to violations"

      - alert: VectorStoreUnhealthy
        expr: vector_store_status != 1
        for: 1m
        annotations:
          summary: "Vector store is unhealthy"
```

## Production Checklist

Before going live, verify all items:

### Pre-Deployment

- [ ] All environment variables configured (`.env`)
- [ ] Runtime pooled database URL and migration direct URL supplied through the
  deployment secret mechanism (not a checked-in file)
- [ ] SSL/TLS certificates provisioned (if using HTTPS)
- [ ] Obsidian vault initialized, backed up, and treated as a projection target
- [ ] Database migration applied with the documented manual `psql` command and
  direct migration URL
- [ ] Service discovery configured (if using Kubernetes)
- [ ] Backup strategy documented (daily snapshots)
- [ ] Log aggregation configured (optional: ELK, Loki)

### Network & Security

- [ ] Firewall rules configured (only needed ports exposed)
- [ ] Redis password set and enforced
- [ ] Vector store API key secured (in secrets manager)
- [ ] Service-to-service authentication enabled (mTLS)
- [ ] Rate limiting configured on public endpoints
- [ ] DDoS protection enabled (if using cloud)

### Monitoring & Observability

- [ ] Prometheus scraping all targets
- [ ] Grafana dashboards created and tested
- [ ] Alert rules configured and tested
- [ ] Log format set to JSON for parsing
- [ ] Distributed tracing enabled (optional)
- [ ] Health check endpoints verified

### High Availability

- [ ] Container restart policies set to `unless-stopped`
- [ ] Service dependencies mapped (restart order)
- [ ] Load balancer configured (if multiple replicas)
- [ ] Session affinity configured (if needed)
- [ ] Database connection pooling enabled
- [ ] Manual idempotent replay procedure reviewed for pending projections
- [ ] Circuit breakers configured

### Data & Backups

- [ ] Vault backup schedule created (daily minimum)
- [ ] Canonical SQL ledger backup and restore procedure tested
- [ ] Vector store backup strategy defined
- [ ] Redis persistence enabled (appendonly)
- [ ] Checkpoint retention policy set (60 days minimum)
- [ ] Disaster recovery plan documented
- [ ] Restore procedure tested

### Documentation

- [ ] Runbooks created for common incidents
- [ ] Team trained on deployment process
- [ ] On-call schedule established
- [ ] Escalation paths documented
- [ ] Change log maintained
- [ ] Service SLOs defined

## Scaling

### Horizontal Scaling

The initial SQL-authoritative rollout supports **one task-executing kernel**.
Task discovery and the pending-to-running transition do not yet use a SQL
compare-and-set lease, so multiple kernel replicas could execute the same
pending task. Keep the kernel at one replica until that claim contract exists.

Only independently deployed stateless services may be replicated today:

```yaml
kernel:
  deploy:
    replicas: 1  # Required while task claiming is single-worker.

registry:
  deploy:
    replicas: 2
```

`MemoryBus` is currently an in-process kernel component, not a standalone
Compose service. A future standalone projector or horizontally scaled kernel
must first add an atomic SQL task lease and an outbox claim/worker contract.

### Load Balancing

Use Nginx or HAProxy in front:

```nginx
upstream kernel {
  server kernel-1:8000;
}

server {
  listen 80;
  location / {
    proxy_pass http://kernel;
    proxy_connect_timeout 5s;
  }
}
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
docker-compose logs kernel

# Verify environment
docker-compose config | grep ARTEMIS

# Restart clean
docker-compose down
docker-compose up --force-recreate
```

### Memory Bus Projection Is Pending

```bash
# Confirm the SQL backend and runtime URL are configured without printing it.
./setup_secrets.sh --check

# MemoryBus runs inside the kernel in this release.
docker-compose logs kernel

# Restore Obsidian projection connectivity, then have the caller replay the
# same write with the retained receipt idempotency key. Omitting it starts a
# new operation. This first slice has no worker to retry it.
# Do not rewrite the note manually as compensation.
```

### Agent Quarantine Threshold

```bash
# Check violations
curl http://localhost:8002/agents/{agent_id}/violations

# Clear violations (if approved)
curl -X POST http://localhost:8002/agents/{agent_id}/clear-violations

# Verify trust score recovery
curl http://localhost:8002/agents/{agent_id}/trust-score
```

## Updating

### Rolling Update

```bash
# 1. Build new images
docker-compose build

# 2. Start updated services one-by-one
docker-compose up -d kernel

# 3. Wait for health checks
sleep 30

# 4. Verify metrics
curl http://localhost:9090/api/v1/query?query=up

# 5. Continue with the public Express boundary. MemoryBus and registry remain
#    in-process kernel components in this release.
docker-compose up -d express-api
```

### Rollback

```bash
# If using git versions:
git checkout <previous-tag>

# Restart containers
docker-compose down
docker-compose up -d

# Restore from checkpoint (if needed)
./scripts/restore_checkpoint.sh <checkpoint_id>
```

For a memory-ledger rollout rollback, set
`ARTEMIS_MEMORY_BACKEND=legacy` through the deployment environment and redeploy
the prior compatible release. This stops new SQL-mode writes; it does not
delete committed revisions or pending outbox events. Preserve the database and
manually replay pending projections before re-enabling `postgres` or `neon`.

## Performance Tuning

### Resource Limits

```yaml
kernel:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 4G
      reservations:
        cpus: '1'
        memory: 2G
```

### Cache Optimization

```bash
ARTEMIS_MEMORY_CACHE_SIZE_MB=500      # Increase for larger workloads
ARTEMIS_EMBEDDING_BATCH_SIZE=200      # Batch embeddings for efficiency
```

### Connection Pooling

```bash
ARTEMIS_DB_POOL_SIZE=20
ARTEMIS_REDIS_POOL_SIZE=10
ARTEMIS_VECTOR_STORE_POOL_SIZE=5
```

## Backup & Restore

### Backup Vault

```bash
# Full backup
tar -czf vault-backup-$(date +%Y%m%d).tar.gz vault/

# Push to S3 (example)
aws s3 cp vault-backup-*.tar.gz s3://artemis-backups/
```

### Backup Vector Store

```bash
# Via Qdrant API
curl http://vector-store:6333/snapshots | jq .

# Extract snapshot
docker-compose exec vector-store \
  curl http://localhost:6333/snapshots/create
```
