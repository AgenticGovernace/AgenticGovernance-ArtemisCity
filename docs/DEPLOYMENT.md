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
- Python 3.10+ (for CLI tools)
- Git 2.30+

### Infrastructure Dependencies

1. **Obsidian Vault** (persistent storage)
   - Local filesystem or network mount
   - At least 10GB initial capacity
   - Regular backup strategy

2. **Vector Store** (semantic search)
   - Qdrant 1.0+ (recommended)
   - Weaviate 1.0+ (alternative)
   - Milvus 2.0+ (alternative)
   - Minimum 5GB storage

3. **Message Broker** (async operations)
   - Redis 6.0+ (recommended)
   - RabbitMQ 3.8+ (alternative)
   - For Hebbian sync batching and task queuing

4. **Monitoring Stack**
   - Prometheus 2.30+ (metrics)
   - Grafana 8.0+ (visualization)
   - Optional: Loki, Tempo for logs/traces

### Network Ports

| Service | Port | Protocol |
|---------|------|----------|
| Kernel API | 8000 | HTTP/gRPC |
| Memory Bus | 8001 | HTTP |
| Agent Registry | 8002 | HTTP |
| Prometheus | 9090 | HTTP |
| Grafana | 3000 | HTTP |
| Redis | 6379 | TCP |
| Qdrant | 6333 | HTTP |
| Obsidian | (file system) | N/A |

## Docker Setup

### Directory Structure

```
artemis-city/
├── docker-compose.yml
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
      - ARTEMIS_ENV=production
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
      - ARTEMIS_ENV=production
      - ARTEMIS_OBSIDIAN_VAULT_PATH=/data/vault
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
      - ARTEMIS_ENV=production
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

**Create `.env` file:**

```bash
# Deployment Environment
ARTEMIS_ENV=production
ARTEMIS_LOG_LEVEL=INFO

# Service URLs
ARTEMIS_KERNEL_URL=http://kernel:8000
ARTEMIS_REGISTRY_URL=http://registry:8002
ARTEMIS_MEMORY_BUS_URL=http://memory-bus:8001

# Storage
ARTEMIS_OBSIDIAN_VAULT_PATH=/data/vault
ARTEMIS_VECTOR_STORE_URL=http://vector-store:6333
ARTEMIS_VECTOR_STORE_API_KEY=${QDRANT_API_KEY}

# Message Broker
ARTEMIS_REDIS_URL=redis://redis:6379
REDIS_PASSWORD=<generate-a-strong-random-secret>

# Memory Bus
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
- [ ] SSL/TLS certificates provisioned (if using HTTPS)
- [ ] Obsidian vault initialized and backed up
- [ ] Database migrations applied (if any)
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
- [ ] Circuit breakers configured

### Data & Backups

- [ ] Vault backup schedule created (daily minimum)
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

For high-load deployments, replicate stateless services:

```yaml
kernel:
  deploy:
    replicas: 3
  labels:
    - "loadbalancer=true"

registry:
  deploy:
    replicas: 2

memory-bus:
  deploy:
    replicas: 2
  environment:
    - ARTEMIS_CACHE_SHARED=true  # Use shared cache (Redis)
```

### Load Balancing

Use Nginx or HAProxy in front:

```nginx
upstream kernel {
  server kernel-1:8000;
  server kernel-2:8000;
  server kernel-3:8000;
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

### Memory Bus Sync Lag Exceeds SLA

```bash
# Check Vector Store health
curl http://localhost:6333/health

# Check Redis queue depth
redis-cli LLEN artemis:sync:queue

# Monitor batching
docker-compose logs memory-bus | grep "batch"
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

# 5. Continue with other services
docker-compose up -d memory-bus
docker-compose up -d registry
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

