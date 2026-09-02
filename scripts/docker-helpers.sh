#!/usr/bin/env bash
# Docker Build & Compose helpers for Artemis City
# Usage: source ./scripts/docker-helpers.sh

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yaml}"
ENV_FILE="${ENV_FILE:-.env}"
REGISTRY="${REGISTRY:-}"
IMAGE_PREFIX="${IMAGE_PREFIX:-artemis-city}"

# ============================================
# Helper Functions
# ============================================

log_info() {
  echo -e "${GREEN}[INFO]${NC} $*"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $*" >&2
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $*"
}

check_env() {
  if [ ! -f "$ENV_FILE" ]; then
    log_error "$ENV_FILE not found. Copy .env.docker first:"
    echo "  cp .env.docker .env"
    exit 1
  fi
}

# ============================================
# Build Commands
# ============================================

build_kernel() {
  log_info "Building FastAPI Kernel image..."
  docker build \
    -f src/Dockerfile-python \
    -t "${REGISTRY}${IMAGE_PREFIX}:kernel-latest" \
    --progress=plain \
    . || { log_error "Kernel build failed"; exit 1; }
  log_info "Kernel image built successfully"
}

build_express() {
  log_info "Building Express API image..."
  docker build \
    -f src/Dockerfile \
    -t "${REGISTRY}${IMAGE_PREFIX}:express-api-latest" \
    --progress=plain \
    . || { log_error "Express API build failed"; exit 1; }
  log_info "Express API image built successfully"
}

build_all() {
  build_kernel
  build_express
}

# ============================================
# Compose Commands
# ============================================

compose_up() {
  check_env
  log_info "Starting services..."
  docker compose \
    --env-file "$ENV_FILE" \
    up --pull always -d "$@"
  log_info "Services started. Run 'docker compose logs -f' to watch"
}

compose_down() {
  log_warn "Stopping and removing containers (volumes preserved)..."
  docker compose \
    --env-file "$ENV_FILE" \
    down "$@"
  log_info "Services stopped"
}

compose_logs() {
  check_env
  docker compose \
    --env-file "$ENV_FILE" \
    logs -f "$@"
}

compose_ps() {
  check_env
  docker compose \
    --env-file "$ENV_FILE" \
    ps "$@"
}

compose_config_check() {
  check_env
  log_info "Validating docker-compose.yaml..."
  if docker compose \
    --env-file "$ENV_FILE" \
    config --quiet; then
    log_info "✓ docker-compose.yaml is valid"
  else
    log_error "Invalid docker-compose.yaml"
    exit 1
  fi
}

# ============================================
# Health Checks
# ============================================

health_check() {
  check_env
  log_info "Running health checks..."

  services=("kernel" "express-api" "redis" "vector-store" "prometheus" "grafana")

  for service in "${services[@]}"; do
    status=$(docker compose \
      --env-file "$ENV_FILE" \
      ps "$service" --format json 2>/dev/null | jq -r '.[0].State' 2>/dev/null)

    if [ "$status" = "running" ]; then
      log_info "✓ $service is running"
    else
      log_error "✗ $service is not running (state: $status)"
    fi
  done

  # Check HTTP endpoints
  log_info "Checking HTTP endpoints..."
  
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    log_info "✓ Kernel (:8000) responding"
  else
    log_warn "✗ Kernel (:8000) not responding"
  fi

  if curl -sf http://localhost:4000/health >/dev/null 2>&1; then
    log_info "✓ Express API (:4000) responding"
  else
    log_warn "✗ Express API (:4000) not responding"
  fi

  if curl -sf http://localhost:9090/-/healthy >/dev/null 2>&1; then
    log_info "✓ Prometheus (:9090) responding"
  else
    log_warn "✗ Prometheus (:9090) not responding"
  fi
}

# ============================================
# Image Management
# ============================================

list_images() {
  log_info "Local Artemis City images:"
  docker images "*/artemis-city:*" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
}

prune_images() {
  log_warn "Removing unused images, containers, and dangling layers..."
  docker system prune -af --filter "label!=keep"
  log_info "Cleanup complete"
}

push_images() {
  if [ -z "$REGISTRY" ]; then
    log_error "REGISTRY not set. Export REGISTRY=myregistry.com/"
    exit 1
  fi

  log_info "Pushing images to $REGISTRY..."
  docker push "${REGISTRY}${IMAGE_PREFIX}:kernel-latest"
  docker push "${REGISTRY}${IMAGE_PREFIX}:express-api-latest"
  log_info "Images pushed successfully"
}

# ============================================
# Debugging
# ============================================

debug_service() {
  local service=$1
  if [ -z "$service" ]; then
    log_error "Usage: debug_service <service_name>"
    exit 1
  fi

  check_env
  log_info "Debugging $service..."
  docker compose --env-file "$ENV_FILE" logs -f "$service"
}

inspect_container() {
  local container=$1
  if [ -z "$container" ]; then
    log_error "Usage: inspect_container <container_name>"
    exit 1
  fi

  log_info "Inspecting $container..."
  docker inspect "$container" | jq '.[0] | {
    State: .State,
    Mounts: .Mounts,
    NetworkSettings: .NetworkSettings,
    Config: {
      Env: .Config.Env,
      Cmd: .Config.Cmd,
      WorkingDir: .Config.WorkingDir
    }
  }'
}

# ============================================
# Script Dispatch
# ============================================

if [ $# -eq 0 ]; then
  cat <<EOF
Artemis City Docker Helpers

Usage: source ./scripts/docker-helpers.sh && <command> [args]

Build:
  build_kernel          Build FastAPI Kernel image
  build_express         Build Express API image
  build_all             Build both images

Compose:
  compose_up [svc]      Start services (or just 'svc')
  compose_down          Stop services
  compose_ps            List running containers
  compose_logs [svc]    Stream logs
  compose_config_check  Validate docker-compose.yaml

Health:
  health_check          Check all service health
  debug_service <svc>   Stream logs for a service
  inspect_container <c> Show container details

Images:
  list_images           List Artemis City images
  push_images           Push to registry (set \$REGISTRY first)
  prune_images          Remove unused images/containers

Environment:
  \$REGISTRY             Docker registry (e.g., myacr.azurecr.io/)
  \$ENV_FILE             Path to .env (default: .env)
  \$COMPOSE_FILE         Path to docker-compose.yaml (default: docker-compose.yaml)

Examples:
  compose_up                    # Start all services
  compose_up kernel             # Start just kernel
  compose_logs -f kernel        # Follow kernel logs
  debug_service redis           # Debug redis
  REGISTRY=myacr.azurecr.io/ push_images
EOF
  exit 0
fi

# Execute command if sourced/called with arguments
"$@"
