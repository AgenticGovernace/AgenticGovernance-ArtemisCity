#!/usr/bin/env bash
# ============================================
#  ARTEMIS CITY - SECRET SETUP SCRIPT
# ============================================
# Populates the four .env files used across the repo with a single,
# consistent set of canonical keys. Designed to be re-runnable: drift
# is healed instead of multiplied.
#
# Target files (each in the location its consumer expects):
#
#   .env                                       Python core (orchestrator,
#                                              memory bus, registry, FastAPI
#                                              dashboard in app/api/main.py)
#   app/api/.env                               TypeScript Express API
#                                              (app/api/index.ts and routes)
#   src/.env                                   Legacy / memory-layer Python
#   src/Artemis Agentic Memory Layer/.env      Memory-layer MCP server
#                                              (if the directory exists)
#
# Canonical keys (shared across the relevant files, see CONSUMERS table):
#
#   MCP_API_KEY              shared MCP / FastAPI auth — every consumer
#   FASTAPI_API_KEY          FastAPI dashboard (app/api/main.py) — root only
#   ARTEMIS_API_KEY_DEFAULT  TS Express admin key (key:role:perms tuple)
#                            — root + app/api/.env
#
# Deployment-only keys (root .env only):
#
#   REDIS_PASSWORD           Redis password for docker-compose.yaml
#   QDRANT_API_KEY           Vector store API key
#   GRAFANA_PASSWORD         Grafana admin password
#
# Modes:
#
#   ./setup_secrets.sh             default: discover existing canonical keys
#                                  from root .env, generate missing ones,
#                                  sync to every file that declares them.
#   ./setup_secrets.sh --check     read-only: report drift without writing.
#   ./setup_secrets.sh --regenerate  force-rotate ALL canonical keys.
#
# Discover precedence: if a canonical key already exists in `.env` (root),
# its value is preserved and propagated to every other file that declares
# the same key. New files get the canonical value the first time, never a
# fresh roll. Re-runs are idempotent.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------

MODE=sync   # sync | check | regenerate

for arg in "$@"; do
    case "$arg" in
        --check)      MODE=check ;;
        --regenerate) MODE=regenerate ;;
        -h|--help)
            sed -n '2,40p' "$0" | sed 's/^# //;s/^#//'
            exit 0
            ;;
        *)
            echo -e "${RED}!!${NC} unknown flag: $arg" >&2
            echo "    valid: --check, --regenerate, --help" >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Static config — which file consumes which canonical key
# ---------------------------------------------------------------------------

ROOT_ENV=".env"
TS_API_ENV="app/api/.env"
SRC_ENV="src/.env"
MEMORY_ENV="src/Artemis Agentic Memory Layer/.env"

ROOT_EXAMPLE=".env.example"
TS_API_EXAMPLE="app/api/.env.example"
SRC_EXAMPLE="src/.env.example"
MEMORY_EXAMPLE="src/Artemis Agentic Memory Layer/.env.example"

# CONSUMERS table: which files should hold which canonical keys.
# Keep this in sync with each .env.example's declared vars.
# Format: "<canonical_key>|<file1>|<file2>|..."
CONSUMERS=(
    "MCP_API_KEY|${ROOT_ENV}|${TS_API_ENV}|${SRC_ENV}|${MEMORY_ENV}"
    "FASTAPI_API_KEY|${ROOT_ENV}"
    "ARTEMIS_API_KEY_DEFAULT|${ROOT_ENV}|${TS_API_ENV}"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

generate_key() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        python3 -c "import secrets; print(secrets.token_hex(32))"
    fi
}

# Portable in-place sed.
inplace_sed() {
    local script="$1" file="$2"
    if [[ "${OSTYPE:-}" == "darwin"* ]]; then
        sed -i '' "$script" "$file"
    else
        sed -i "$script" "$file"
    fi
}

# Read the value of KEY from FILE, stripping any wrapping quotes. Returns
# empty string when KEY is absent, commented out, or the file is missing.
read_env_value() {
    local key="$1" file="$2"
    if [[ ! -f "$file" ]]; then
        printf ''
        return
    fi
    awk -v k="$key" -F= '
        $0 ~ "^" k "=" {
            sub("^" k "=", "")
            gsub(/^["'"'"']/, "")
            gsub(/["'"'"']$/, "")
            print
            exit
        }
    ' "$file"
}

# Does FILE declare KEY at all (including commented-out)? Used to decide
# whether the file is a consumer of this canonical key.
file_declares() {
    local key="$1" file="$2"
    [[ -f "$file" ]] || return 1
    grep -qE "^#?\s*${key}=" "$file"
}

# Set KEY=VALUE in FILE. Replaces an existing line (commented or not),
# otherwise appends to the file.
set_env_var() {
    local key="$1" value="$2" file="$3"
    local escaped
    escaped=$(printf '%s' "$value" | sed -e 's/[\/&]/\\&/g')

    if grep -Eq "^#?\s*${key}=" "$file" 2>/dev/null; then
        inplace_sed "s/^#\?\s*${key}=.*/${key}=${escaped}/" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

# Treat values that match the *_here placeholder pattern (from .env.example)
# as if they were empty, so the script never preserves a stale placeholder
# as if it were a real key.
is_placeholder() {
    local v="$1"
    [[ -z "$v" ]] && return 0
    [[ "$v" =~ ^your_.*_here ]] && return 0
    return 1
}

# Prompt before copying an example over an absent target.
should_create() {
    local target="$1"
    if [[ -f "$target" ]]; then
        return 0  # already there, nothing to ask
    fi
    echo -e "${YELLOW}!${NC}  $target does not exist"
    read -p "   Create from its .env.example? (Y/n): " -r reply
    [[ ! "$reply" =~ ^[Nn]$ ]]
}

# ---------------------------------------------------------------------------
# Deployment-only block (root .env only) — preserved from prior versions.
# ---------------------------------------------------------------------------

add_root_deployment_env_if_absent() {
    local target="$1"

    # Idempotency: only append the deployment block when the first entry
    # in it is missing.
    if grep -qE "^ARTEMIS_API_KEY_DEFAULT=" "$target"; then
        return 0
    fi

    cat >> "$target" <<'EOF'

# ============================================
# 🚀 DEPLOYMENT / DOCKER COMPOSE CONFIGURATION
# ============================================
# Generated by setup_secrets.sh from docs/DEPLOYMENT.md defaults.
# docker-compose.yaml reads this root .env file for required service secrets.
EOF

    set_env_var "ARTEMIS_API_KEY_DEFAULT" "${TS_KEY}:admin:read,write,delete,admin" "$target"
    set_env_var "ARTEMIS_LOG_LEVEL" "INFO" "$target"
    set_env_var "ARTEMIS_KERNEL_URL" "http://kernel:8000" "$target"
    set_env_var "ARTEMIS_REGISTRY_URL" "http://registry:8002" "$target"
    set_env_var "ARTEMIS_MEMORY_BUS_URL" "http://memory-bus:8001" "$target"
    set_env_var "ARTEMIS_OBSIDIAN_VAULT_PATH" "/data/vault" "$target"
    set_env_var "ARTEMIS_VECTOR_STORE_URL" "http://vector-store:6333" "$target"
    set_env_var "ARTEMIS_VECTOR_STORE_API_KEY" "$QDRANT_KEY" "$target"
    set_env_var "ARTEMIS_REDIS_URL" "redis://redis:6379" "$target"
    set_env_var "REDIS_PASSWORD" "$REDIS_KEY" "$target"
    set_env_var "ARTEMIS_MEMORY_WRITE_TIMEOUT_MS" "200" "$target"
    set_env_var "ARTEMIS_MEMORY_SYNC_TIMEOUT_MS" "300" "$target"
    set_env_var "ARTEMIS_MEMORY_CACHE_SIZE_MB" "100" "$target"
    set_env_var "ARTEMIS_MEMORY_QUEUE_MAX_BYTES" "10485760" "$target"
    set_env_var "ARTEMIS_EMBEDDING_MODEL" "text-embedding-3-large" "$target"
    set_env_var "ARTEMIS_EMBEDDING_BATCH_SIZE" "100" "$target"
    set_env_var "ARTEMIS_EMBEDDING_API_KEY" "" "$target"
    set_env_var "ARTEMIS_APPROVAL_TIER1_ENABLED" "true" "$target"
    set_env_var "ARTEMIS_APPROVAL_TIER2_TIMEOUT_HOURS" "24" "$target"
    set_env_var "ARTEMIS_APPROVAL_TIER3_TIMEOUT_HOURS" "72" "$target"
    set_env_var "ARTEMIS_AUTO_ROLLBACK_ON_ERRORS" "true" "$target"
    set_env_var "ARTEMIS_AUTO_ROLLBACK_ERROR_THRESHOLD" "0.05" "$target"
    set_env_var "ARTEMIS_SANDBOX_VIOLATION_QUARANTINE_COUNT" "3" "$target"
    set_env_var "ARTEMIS_SANDBOX_VIOLATION_DECAY_DAYS" "30" "$target"
    set_env_var "QDRANT_API_KEY" "$QDRANT_KEY" "$target"
    set_env_var "GRAFANA_PASSWORD" "$GRAFANA_KEY" "$target"
    set_env_var "ARTEMIS_PROMETHEUS_ENABLED" "true" "$target"
    set_env_var "ARTEMIS_METRICS_PORT" "9090" "$target"
    set_env_var "ARTEMIS_LOG_FORMAT" "json" "$target"
}

# ---------------------------------------------------------------------------
# Phase 1 — Discover canonical values
# ---------------------------------------------------------------------------

# For each canonical key, prefer the existing value in root .env. Fall
# back to any other file that has it. Generate fresh only when nothing
# survives. In --regenerate mode, ignore existing values entirely.

discover_or_generate() {
    local key="$1"; shift
    local files=("$@")

    if [[ "$MODE" == "regenerate" ]]; then
        generate_key
        return
    fi

    local v=""
    for f in "${files[@]}"; do
        v="$(read_env_value "$key" "$f")"
        if ! is_placeholder "$v"; then
            printf '%s' "$v"
            return
        fi
    done
    generate_key
}

# Resolve canonical values for the three shared keys plus the deployment
# extras (which always rotate on first run but are preserved on re-runs).
MCP_KEY="$(discover_or_generate "MCP_API_KEY" "$ROOT_ENV" "$TS_API_ENV" "$SRC_ENV" "$MEMORY_ENV")"
FASTAPI_KEY="$(discover_or_generate "FASTAPI_API_KEY" "$ROOT_ENV")"

# ARTEMIS_API_KEY_DEFAULT is stored as "<key>:admin:read,write,delete,admin"
# in the .env files. Extract just the key portion for canonical purposes;
# the suffix is rebuilt below.
_existing_ts_full=""
if [[ "$MODE" != "regenerate" ]]; then
    for f in "$ROOT_ENV" "$TS_API_ENV"; do
        v="$(read_env_value "ARTEMIS_API_KEY_DEFAULT" "$f")"
        if ! is_placeholder "$v"; then
            _existing_ts_full="$v"
            break
        fi
    done
fi
if [[ -n "$_existing_ts_full" ]]; then
    TS_KEY="${_existing_ts_full%%:*}"
else
    TS_KEY="$(generate_key)"
fi

# Deployment extras: preserve when present, only generate on first run.
REDIS_KEY="$(discover_or_generate "REDIS_PASSWORD" "$ROOT_ENV")"
QDRANT_KEY="$(discover_or_generate "QDRANT_API_KEY" "$ROOT_ENV")"
GRAFANA_KEY="$(discover_or_generate "GRAFANA_PASSWORD" "$ROOT_ENV")"

# The ARTEMIS_API_KEY_DEFAULT value carries the role/perm suffix.
TS_VALUE="${TS_KEY}:admin:read,write,delete,admin"

# ---------------------------------------------------------------------------
# Phase 2 — Ensure each .env exists (offer to create from .env.example)
# ---------------------------------------------------------------------------

ensure_env_file() {
    local example="$1" target="$2" label="$3"

    if [[ -f "$target" ]]; then
        return 0
    fi
    if [[ ! -f "$example" ]]; then
        echo -e "  ${YELLOW}skip${NC} $label — neither file nor example exists"
        return 1
    fi
    if [[ "$MODE" == "check" ]]; then
        echo -e "  ${YELLOW}drift${NC} $target missing (would be created from $example)"
        return 1
    fi
    if ! should_create "$target"; then
        echo -e "  ${YELLOW}skip${NC} $label — user declined to create"
        return 1
    fi
    mkdir -p "$(dirname "$target")"
    cp "$example" "$target"
    chmod 600 "$target"
    echo -e "  ${GREEN}created${NC} $target from $example"
    return 0
}

# ---------------------------------------------------------------------------
# Phase 3 — Sync canonical keys into every consumer
# ---------------------------------------------------------------------------

# Returns 0 when the key is already at its canonical value in the file,
# 1 otherwise. Used by --check mode to report drift.
in_sync() {
    local key="$1" expected="$2" file="$3"
    local actual
    actual="$(read_env_value "$key" "$file")"
    [[ "$actual" == "$expected" ]]
}

sync_key() {
    local key="$1" expected="$2" file="$3"

    if [[ ! -f "$file" ]]; then
        return 0
    fi
    if ! file_declares "$key" "$file"; then
        # File doesn't declare this key — don't add it on its own. The
        # template (.env.example) decides which keys belong where; if it
        # changed and this file is stale, the user can `cp .env.example`
        # by hand or re-run from a clean slate.
        return 0
    fi

    if in_sync "$key" "$expected" "$file"; then
        return 0
    fi

    if [[ "$MODE" == "check" ]]; then
        echo -e "  ${YELLOW}drift${NC} $file — $key out of sync"
        return 1
    fi

    set_env_var "$key" "$expected" "$file"
    echo -e "  ${GREEN}synced${NC} $file — $key"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo "Artemis City — Secure Environment Setup ($MODE)"
echo "================================================"
echo ""

echo -e "${BLUE}1. Discover canonical key values${NC}"
case "$MODE" in
    sync)        echo "  preserving existing keys from $ROOT_ENV; generating only what's missing." ;;
    regenerate)  echo "  rotating ALL canonical keys (existing values discarded)." ;;
    check)       echo "  read-only check; reporting drift without writing." ;;
esac
echo ""

echo -e "${BLUE}2. Ensure each .env file exists${NC}"
ensure_env_file "$ROOT_EXAMPLE"    "$ROOT_ENV"    "Python core (.env)" || true
ensure_env_file "$TS_API_EXAMPLE"  "$TS_API_ENV"  "TS Express API (app/api/.env)" || true
ensure_env_file "$SRC_EXAMPLE"     "$SRC_ENV"     "Memory-layer Python (src/.env)" || true
ensure_env_file "$MEMORY_EXAMPLE"  "$MEMORY_ENV"  "Memory-layer MCP server" || true
echo ""

echo -e "${BLUE}3. Sync canonical keys${NC}"
DRIFT_COUNT=0
for entry in "${CONSUMERS[@]}"; do
    IFS='|' read -r KEY FIRST REST <<<"$entry"
    files=("$FIRST")
    while [[ -n "$REST" ]]; do
        IFS='|' read -r NEXT REST <<<"$REST"
        files+=("$NEXT")
    done

    case "$KEY" in
        MCP_API_KEY)              EXPECTED="$MCP_KEY" ;;
        FASTAPI_API_KEY)          EXPECTED="$FASTAPI_KEY" ;;
        ARTEMIS_API_KEY_DEFAULT)  EXPECTED="$TS_VALUE" ;;
    esac

    for f in "${files[@]}"; do
        if ! sync_key "$KEY" "$EXPECTED" "$f"; then
            DRIFT_COUNT=$((DRIFT_COUNT + 1))
        fi
    done
done
echo ""

echo -e "${BLUE}4. Deployment block on root .env (idempotent)${NC}"
if [[ "$MODE" != "check" && -f "$ROOT_ENV" ]]; then
    add_root_deployment_env_if_absent "$ROOT_ENV"
    echo "  ok"
else
    echo "  skipped (mode=$MODE)"
fi
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo "================================================"
case "$MODE" in
    check)
        if [[ "$DRIFT_COUNT" -gt 0 ]]; then
            echo -e "${RED}drift detected:${NC} $DRIFT_COUNT issue(s) above"
            echo "   re-run without --check to sync"
            exit 1
        else
            echo -e "${GREEN}all canonical keys in sync.${NC}"
        fi
        ;;
    sync|regenerate)
        echo -e "${GREEN}Setup complete.${NC}"
        echo ""
        echo "Next steps:"
        echo "  1. Add your Obsidian REST API key to .env:"
        echo -e "     ${YELLOW}OBSIDIAN_API_KEY=<your key from Obsidian > Settings > Local REST API>${NC}"
        echo "  2. Add OPENAI_API_KEY or ARTEMIS_EMBEDDING_API_KEY if you use hosted embeddings."
        echo "  3. Set OBSIDIAN_VAULT_PATH for local runs if your vault isn't at <repo>/obsidian_vault."
        echo "  4. docker-compose.yaml can now read REDIS_PASSWORD, QDRANT_API_KEY,"
        echo "     GRAFANA_PASSWORD, and ARTEMIS_API_KEY_DEFAULT from the root .env."
        echo "  5. To verify alignment any time: ./setup_secrets.sh --check"
        echo "  6. To rotate ALL secrets: ./setup_secrets.sh --regenerate"
        ;;
esac
