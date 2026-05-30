#!/usr/bin/env bash
# ============================================
#  ARTEMIS CITY - SECRET SETUP SCRIPT
# ============================================
# Generates fresh keys and populates the four env files used across the
# repo, each in the location its consumer expects:
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
# Generated keys:
#   MCP_API_KEY              shared MCP / FastAPI auth (matches across files)
#   FASTAPI_API_KEY          FastAPI dashboard (app/api/main.py)
#   ARTEMIS_API_KEY_DEFAULT  TS Express admin key (key:role:perms tuple)
#
# Usage: ./setup_secrets.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

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

# sed -i is portable when called via this wrapper.
inplace_sed() {
    local script="$1" file="$2"
    if [[ "${OSTYPE:-}" == "darwin"* ]]; then
        sed -i '' "$script" "$file"
    else
        sed -i "$script" "$file"
    fi
}

# Substitute a placeholder with a value in a file. Skips silently when the
# placeholder is absent (file may legitimately not declare that key).
set_value() {
    local placeholder="$1" value="$2" file="$3"
    if grep -q "$placeholder" "$file" 2>/dev/null; then
        local escaped
        escaped=$(printf '%s' "$value" | sed -e 's/[\/&]/\\&/g')
        inplace_sed "s/$placeholder/$escaped/g" "$file"
    fi
}

# Prompt before overwriting an existing file. Returns 0 to proceed.
should_write() {
    local target="$1"
    if [[ ! -f "$target" ]]; then
        return 0
    fi
    echo -e "${YELLOW}!${NC}  $target already exists"
    read -p "   Overwrite? (y/N): " -r reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

# Copy an example file to its target, apply all known key substitutions, and
# lock permissions. Pure no-op if the example is missing.
provision_env() {
    local example="$1" target="$2" label="$3"

    echo -e "${BLUE}>${NC} $label"
    echo "  example: $example"
    echo "  target:  $target"

    if [[ ! -f "$example" ]]; then
        echo -e "  ${YELLOW}skip${NC} — example not found"
        echo ""
        return 0
    fi

    if ! should_write "$target"; then
        echo -e "  ${YELLOW}skip${NC} — kept existing"
        echo ""
        return 0
    fi

    mkdir -p "$(dirname "$target")"
    cp "$example" "$target"

    # Apply substitutions. Each is a no-op when the placeholder is absent.
    set_value "your_secure_api_key_here" "$MCP_KEY" "$target"
    set_value "your_fastapi_api_key_here" "$FASTAPI_KEY" "$target"
    set_value "your_default_api_key_here" "$TS_KEY" "$target"

    chmod 600 "$target"

    if git check-ignore "$target" >/dev/null 2>&1; then
        echo -e "  ${GREEN}ok${NC} written (chmod 600, git-ignored)"
    else
        echo -e "  ${RED}!!${NC} written but NOT git-ignored — fix .gitignore before committing"
    fi
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo "Artemis City — Secure Environment Setup"
echo "========================================"
echo ""

MCP_KEY="$(generate_key)"
FASTAPI_KEY="$(generate_key)"
TS_KEY="$(generate_key)"

provision_env ".env.example"     ".env"     "Python core (.env)"
provision_env "app/api/.env.example" "app/api/.env" "TypeScript Express API (app/api/.env)"
provision_env "src/.env.example" "src/.env" "Memory-layer Python (src/.env)"
provision_env \
    "src/Artemis Agentic Memory Layer/.env.example" \
    "src/Artemis Agentic Memory Layer/.env" \
    "Memory-layer MCP server"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo -e "${GREEN}Setup complete.${NC}"
echo ""
echo "Generated keys (matching the entries written to the .env files):"
echo "  MCP_API_KEY              = $MCP_KEY"
echo "  FASTAPI_API_KEY          = $FASTAPI_KEY"
echo "  ARTEMIS_API_KEY_DEFAULT  = ${TS_KEY}:admin:read,write,delete,admin"
echo ""
echo "Next steps:"
echo "  1. Add your Obsidian REST API key to .env:"
echo -e "     ${YELLOW}OBSIDIAN_API_KEY=<your key from Obsidian > Settings > Local REST API>${NC}"
echo "  2. Set OBSIDIAN_VAULT_PATH if your vault isn't at <repo>/obsidian_vault."
echo "  3. If you skipped any existing .env, confirm MCP_API_KEY matches across"
echo "     consumers before starting cross-service workflows."
echo ""
echo "Security notes:"
echo "  - All written .env files are chmod 600."
echo "  - .gitignore covers .env at any depth — verified per file above."
echo "  - Re-running this script prompts before overwriting each file."
