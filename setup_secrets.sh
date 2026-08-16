#!/usr/bin/env bash
# Artemis City — complete runtime environment provisioner.
#
#   ./setup_secrets.sh              backfill templates and generate missing owned secrets
#   ./setup_secrets.sh --check      report missing keys/drift without writing
#   ./setup_secrets.sh --regenerate rotate all secrets owned by this script
#
# Existing ordinary settings and provider credentials are preserved. The
# matching .env.example for each runtime location is the authoritative list of
# keys, so an existing .env is never assumed to be complete.

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
            sed -n '2,48p' "$0" | sed 's/^# //;s/^#//'
            exit 0
            ;;
        *)
            echo -e "$RED!!$NC unknown flag: $arg" >&2
            echo "    valid: --check, --regenerate, --help" >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Runtime locations and template ownership
# ---------------------------------------------------------------------------

ROOT_ENV=".env"
TS_API_ENV="app/api/.env"
SRC_ENV="src/.env"
MEMORY_ENV="src/Artemis Agentic Memory Layer/.env"

ROOT_EXAMPLE=".env.example"
TS_API_EXAMPLE="app/api/.env.example"
SRC_EXAMPLE="src/.env.example"
MEMORY_EXAMPLE="src/Artemis Agentic Memory Layer/.env.example"

# Every runtime location is reconciled against its own template. The root,
# Python, and bridge templates intentionally overlap: a process launched from
# any supported location must receive a complete configuration.
TARGETS=(
    "$ROOT_EXAMPLE|$ROOT_ENV|Python core, FastAPI, Docker Compose (.env)"
    "$TS_API_EXAMPLE|$TS_API_ENV|TypeScript Express API (app/api/.env)"
    "$SRC_EXAMPLE|$SRC_ENV|Python source runtime (src/.env)"
    "$MEMORY_EXAMPLE|$MEMORY_ENV|Standalone memory-layer MCP server"
)

# Secret ownership is explicit below in is_owned_secret, secret_value, and the
# discovery calls. Only those values are generated or rotated; provider
# credentials and ordinary configuration values are never invented.

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

# Read the active value of KEY from FILE, stripping one pair of wrapping
# quotes. Commented declarations and missing files return an empty value.
read_env_value() {
    local key="$1" file="$2"
    if [[ ! -f "$file" ]]; then
        printf ''
        return
    fi
    awk -v k="$key" '
        $0 ~ "^" k "=" {
            value = $0
            sub("^" k "=", "", value)
            if (value ~ /^".*"$/ || value ~ /^'"'"'.*'"'"'$/) {
                value = substr(value, 2, length(value) - 2)
            }
            print value
            exit
        }
    ' "$file"
}

# Does FILE contain an active declaration for KEY?
active_declares() {
    local key="$1" file="$2"
    [[ -f "$file" ]] || return 1
    grep -qE "^$key=" "$file"
}

# Replace the first active/commented declaration, or append KEY=VALUE. Values
# are passed through awk rather than sed so URLs, colons, and ampersands do not
# become replacement expressions. Generated secret values are hex-safe.
set_env_var() {
    local key="$1" value="$2" file="$3"
    local tmp="$file.tmp.$$"

    awk -v k="$key" -v v="$value" '
        BEGIN { replaced = 0 }
        $0 ~ "^#?[[:space:]]*" k "=" {
            if (!replaced) {
                print k "=" v
                replaced = 1
            }
            next
        }
        { print }
        END {
            if (!replaced) print k "=" v
        }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
    # The temporary-file replacement otherwise inherits the process umask;
    # environment files contain secrets and must remain owner-readable only.
    chmod 600 "$file"
}

# Values copied from an example but not usable as secrets. Empty optional
# values are deliberately placeholders; only owned secret fields use this
# predicate to trigger generation.
is_placeholder() {
    local value="$1"
    case "$value" in
        ""|__MISSING__|your_*_here|"<*"|*\>|\${*}|change_me|CHANGE_ME|changeme|CHANGEME|replace_me|REPLACE_ME)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_owned_secret() {
    case "$1" in
        MCP_API_KEY|FASTAPI_API_KEY|ARTEMIS_API_KEY_DEFAULT|REDIS_PASSWORD|QDRANT_API_KEY|GRAFANA_PASSWORD)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_derived_value() {
    [[ "$1" == "ARTEMIS_VECTOR_STORE_API_KEY" ]]
}

# Authstructure fields are public operator configuration. They are validated
# by the runtime loader and are never generated, derived, propagated, or
# rotated by this provisioner.
is_operator_authstructure_config() {
    case "$1" in
        ARTEMIS_AUTHSTRUCTURE_URL|ARTEMIS_AUTHSTRUCTURE_AUDIENCE|ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE|ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_valid_authstructure_identifier() {
    local value="$1"
    [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$ ]]
}

is_valid_authstructure_hostname() {
    local hostname="$1" label octet octet_number
    local -a labels
    [[ -n "$hostname" && ${#hostname} -le 253 ]] || return 1
    [[ "$hostname" != .* && "$hostname" != *. ]] || return 1
    IFS='.' read -r -a labels <<< "$hostname"
    if [[ "$hostname" =~ ^[0-9.]+$ ]]; then
        [[ ${#labels[@]} -eq 4 ]] || return 1
        for octet in "${labels[@]}"; do
            [[ "$octet" =~ ^[0-9]{1,3}$ ]] || return 1
            [[ ${#octet} -eq 1 || "$octet" != 0* ]] || return 1
            octet_number=$((10#$octet))
            (( octet_number <= 255 )) || return 1
        done
        return 0
    fi
    for label in "${labels[@]}"; do
        [[ -n "$label" && ${#label} -le 63 ]] || return 1
        [[ "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
    done
}

# Authstructure endpoints require HTTPS. Plain HTTP is accepted only for the
# explicit loopback hosts used by local conformance fixtures.
is_valid_authstructure_url() {
    local value="$1" scheme remainder authority host port port_number
    [[ -n "$value" && ! "$value" =~ [[:space:]] ]] || return 1
    [[ "$value" != *"?"* && "$value" != *"#"* ]] || return 1

    case "$value" in
        https://*) scheme=https; remainder="${value#https://}" ;;
        http://*)  scheme=http; remainder="${value#http://}" ;;
        *) return 1 ;;
    esac
    authority="${remainder%%/*}"
    [[ -n "$authority" && "$authority" != *"@"* ]] || return 1

    host="$authority"
    if [[ "$authority" == *":"* ]]; then
        host="${authority%:*}"
        port="${authority##*:}"
        [[ "$port" =~ ^[0-9]{1,5}$ ]] || return 1
        port_number=$((10#$port))
        (( port_number >= 1 && port_number <= 65535 )) || return 1
    fi
    is_valid_authstructure_hostname "$host" || return 1
    if [[ "$scheme" == "http" ]]; then
        [[ "$host" == "localhost" || "$host" == "127.0.0.1" ]] || return 1
    fi
}

is_valid_authstructure_value() {
    local key="$1" value="$2"
    case "$key" in
        ARTEMIS_AUTHSTRUCTURE_URL)
            is_valid_authstructure_url "$value"
            ;;
        ARTEMIS_AUTHSTRUCTURE_AUDIENCE|ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE|ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID)
            is_valid_authstructure_identifier "$value"
            ;;
        *)
            return 1
            ;;
    esac
}

# Mutating modes must prove every declared Authstructure field is already
# operator-supplied and valid before prompts, file creation, secret discovery,
# rotation, or reconciliation. Diagnostics expose only the key and safe state.
preflight_authstructure_for_mutation() {
    local entry example target _label line key value state
    local invalid=0

    for entry in "${TARGETS[@]}"; do
        IFS='|' read -r example target _label <<< "$entry"
        [[ -f "$example" ]] || continue

        while IFS= read -r line || [[ -n "$line" ]]; do
            [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
            key="${BASH_REMATCH[1]}"
            is_operator_authstructure_config "$key" || continue

            state=""
            if [[ ! -f "$target" ]]; then
                state="missing target"
            elif ! active_declares "$key" "$target"; then
                state="missing"
            else
                value="$(read_env_value "$key" "$target")"
                if [[ -z "$value" ]]; then
                    state="blank"
                elif ! is_valid_authstructure_value "$key" "$value"; then
                    state="malformed"
                fi
            fi

            if [[ -n "$state" ]]; then
                echo -e "  $YELLOW""incomplete$NC $target — $key $state; operator action required"
                invalid=1
            fi
        done < "$example"
    done

    return "$invalid"
}

should_create() {
    local target="$1"
    if [[ -f "$target" ]]; then
        return 0
    fi
    echo -e "$YELLOW!$NC  $target does not exist"
    read -r -p "   Create from its .env.example? (Y/n): " reply
    [[ ! "$reply" =~ ^[Nn]$ ]]
}

ensure_env_file() {
    local example="$1" target="$2" label="$3"

    if [[ -f "$target" ]]; then
        return 0
    fi
    if [[ ! -f "$example" ]]; then
        echo -e "  $YELLOW""skip$NC $label — neither file nor example exists"
        return 1
    fi
    if [[ "$MODE" == "check" ]]; then
        echo -e "  $YELLOW""drift$NC $target missing (would be created from $example)"
        return 1
    fi
    if ! should_create "$target"; then
        echo -e "  $YELLOW""skip$NC $label — user declined to create"
        return 1
    fi
    mkdir -p "$(dirname "$target")"
    cp "$example" "$target"
    chmod 600 "$target"
    echo -e "  $GREEN""created$NC $target from $example"
    return 0
}

# Discover one owned secret across its declared consumers. Root values win,
# then the remaining runtime files. In check mode, use a marker instead of
# minting a value so a read-only check has no side effects.
discover_secret() {
    local key="$1"; shift
    local file value

    if [[ "$MODE" == "regenerate" ]]; then
        generate_key
        return
    fi

    for file in "$@"; do
        value="$(read_env_value "$key" "$file")"
        if ! is_placeholder "$value"; then
            printf '%s' "$value"
            return
        fi
    done

    if [[ "$MODE" == "check" ]]; then
        printf '__MISSING__'
    else
        generate_key
    fi
}

if [[ "$MODE" != "check" ]] && ! preflight_authstructure_for_mutation; then
    echo -e "$RED""Setup incomplete:$NC operator-supplied configuration requires action."
    exit 1
fi

# Discover canonical values before creating files so a partial checkout does
# not cause a new key to replace a value that exists in another runtime file.
MCP_KEY="$(discover_secret MCP_API_KEY "$ROOT_ENV" "$TS_API_ENV" "$SRC_ENV" "$MEMORY_ENV")"
FASTAPI_KEY="$(discover_secret FASTAPI_API_KEY "$ROOT_ENV")"
REDIS_KEY="$(discover_secret REDIS_PASSWORD "$ROOT_ENV")"
QDRANT_KEY="$(discover_secret QDRANT_API_KEY "$ROOT_ENV")"
GRAFANA_KEY="$(discover_secret GRAFANA_PASSWORD "$ROOT_ENV")"

if [[ "$MODE" == "regenerate" ]]; then
    TS_VALUE="$(generate_key):admin:read,write,delete,admin"
else
    TS_VALUE="$(discover_secret ARTEMIS_API_KEY_DEFAULT "$ROOT_ENV" "$TS_API_ENV")"
    if [[ "$TS_VALUE" == "__MISSING__" && "$MODE" != "check" ]]; then
        TS_VALUE="$(generate_key):admin:read,write,delete,admin"
    fi
fi

secret_value() {
    case "$1" in
        MCP_API_KEY)              printf '%s' "$MCP_KEY" ;;
        FASTAPI_API_KEY)          printf '%s' "$FASTAPI_KEY" ;;
        ARTEMIS_API_KEY_DEFAULT)  printf '%s' "$TS_VALUE" ;;
        REDIS_PASSWORD)           printf '%s' "$REDIS_KEY" ;;
        QDRANT_API_KEY)           printf '%s' "$QDRANT_KEY" ;;
        GRAFANA_PASSWORD)         printf '%s' "$GRAFANA_KEY" ;;
        *)                         return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Template reconciliation
# ---------------------------------------------------------------------------

in_sync() {
    local key="$1" expected="$2" file="$3"
    [[ "$(read_env_value "$key" "$file")" == "$expected" ]]
}

sync_key() {
    local key="$1" expected="$2" file="$3"

    if [[ ! -f "$file" ]]; then
        return 1
    fi
    if in_sync "$key" "$expected" "$file"; then
        return 0
    fi
    if [[ "$MODE" == "check" ]]; then
        echo -e "  $YELLOW""drift$NC $file — $key out of sync"
        return 1
    fi
    set_env_var "$key" "$expected" "$file"
    echo -e "  $GREEN""synced$NC $file — $key"
}

# Add every active KEY=VALUE declaration from a runtime template. Existing
# ordinary values are left untouched; absent/commented declarations are added
# from the template. Owned secrets are always reconciled to their canonical
# value, and the vector-store API key is a derived alias of QDRANT_API_KEY.
sync_template() {
    local example="$1" target="$2"
    local line key template_value expected
    local changed=0

    [[ -f "$target" ]] || return 0
    [[ -f "$example" ]] || return 0

    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        key="${BASH_REMATCH[1]}"
        template_value="${BASH_REMATCH[2]}"

        if is_owned_secret "$key"; then
            expected="$(secret_value "$key")"
        elif is_derived_value "$key"; then
            expected="$QDRANT_KEY"
        elif is_operator_authstructure_config "$key"; then
            expected="$template_value"
        else
            expected="$template_value"
        fi

        if is_operator_authstructure_config "$key"; then
            if ! active_declares "$key" "$target"; then
                if [[ "$MODE" == "check" ]]; then
                    echo -e "  $YELLOW""drift$NC $target — missing $key"
                else
                    echo -e "  $YELLOW""incomplete$NC $target — missing $key; operator action required"
                fi
                changed=1
                continue
            fi

            local configured_value reason
            configured_value="$(read_env_value "$key" "$target")"
            if ! is_valid_authstructure_value "$key" "$configured_value"; then
                if [[ -z "$configured_value" ]]; then
                    reason="blank"
                else
                    reason="malformed"
                fi
                if [[ "$MODE" == "check" ]]; then
                    echo -e "  $YELLOW""drift$NC $target — $key $reason"
                else
                    echo -e "  $YELLOW""preserved$NC $target — $key $reason; operator action required"
                fi
                changed=1
            fi
            continue
        fi

        if ! active_declares "$key" "$target"; then
            if [[ "$MODE" == "check" ]]; then
                echo -e "  $YELLOW""drift$NC $target — missing $key"
                changed=1
            else
                set_env_var "$key" "$expected" "$target"
                echo -e "  $GREEN""added$NC $target — $key"
            fi
            continue
        fi

        if is_owned_secret "$key" || is_derived_value "$key"; then
            if ! sync_key "$key" "$expected" "$target"; then
                changed=1
            fi
        fi
    done < "$example"

    return "$changed"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo "Artemis City — Secure Environment Setup ($MODE)"
echo "================================================"
echo ""
case "$MODE" in
    sync)        echo "Syncing every runtime template; preserving existing values and generating missing owned secrets." ;;
    regenerate)  echo "Rotating owned secrets and reconciling every runtime template." ;;
    check)       echo "Read-only check; reporting missing keys and secret drift without writing." ;;
esac
echo ""

DRIFT_COUNT=0

echo -e "$BLUE""1. Ensure runtime env files exist$NC"
for entry in "${TARGETS[@]}"; do
    IFS='|' read -r example target label <<< "$entry"
    if ! ensure_env_file "$example" "$target" "$label"; then
        [[ "$MODE" == "check" ]] && DRIFT_COUNT=$((DRIFT_COUNT + 1))
    fi
done
echo ""

echo -e "$BLUE""2. Reconcile all declared variables$NC"
for entry in "${TARGETS[@]}"; do
    IFS='|' read -r example target _label <<< "$entry"
    if ! sync_template "$example" "$target"; then
        DRIFT_COUNT=$((DRIFT_COUNT + 1))
    fi
done
echo ""

echo "================================================"
case "$MODE" in
    check)
        if [[ "$DRIFT_COUNT" -gt 0 ]]; then
            echo -e "$RED""drift detected:$NC $DRIFT_COUNT issue(s) above"
            echo "   re-run without --check to sync"
            exit 1
        fi
        echo -e "$GREEN""all runtime env files match their templates and owned secrets.$NC"
        ;;
    sync|regenerate)
        if [[ "$DRIFT_COUNT" -gt 0 ]]; then
            echo -e "$RED""Setup incomplete:$NC operator-supplied configuration requires action."
            exit 1
        fi
        echo -e "$GREEN""Setup complete.$NC"
        echo ""
        echo "Value ownership:"
        echo "  - MCP/API/deployment secrets are generated here and rotate with --regenerate."
        echo "  - Authstructure public configuration is operator-supplied and never generated or rotated."
        echo "  - Existing ordinary settings and provider credentials are preserved."
        echo "  - Missing ordinary settings come from the matching .env.example."
        echo ""
        echo "Next steps:"
        echo "  1. Set OBSIDIAN_API_KEY and OBSIDIAN_VAULT_PATH for vault-backed runs."
        echo "  2. Set provider credentials (OPENAI_API_KEY, EXO_API_KEY, or HF_TOKEN) only if used."
        echo "  3. Verify alignment with: ./setup_secrets.sh --check"
        echo "  4. Rotate owned secrets with: ./setup_secrets.sh --regenerate"
        ;;
esac
