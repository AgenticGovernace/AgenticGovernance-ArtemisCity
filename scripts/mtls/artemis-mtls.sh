#!/usr/bin/env bash
#
# artemis-mtls.sh — local certificate authority for the Artemis memory server.
#
# Issues the server certificate and per-agent client certificates that back
# mutual TLS on the Obsidian memory layer, and keeps the vault-side agent
# registry (`.agent/clients/*.yaml`) in sync with what was actually issued.
#
# Private keys live OUTSIDE the repository (default: ~/.artemis/mtls) so a
# stray `git add -A` can never publish them. Only public certificates and the
# YAML manifests are meant to be committed.
#
# Usage:
#   scripts/mtls/artemis-mtls.sh init-ca
#   scripts/mtls/artemis-mtls.sh issue-server [common-name]
#   scripts/mtls/artemis-mtls.sh issue-client <agent-id> [--days N] [--routes a,b]
#   scripts/mtls/artemis-mtls.sh fingerprint <path/to/cert.crt>
#   scripts/mtls/artemis-mtls.sh revoke <agent-id>
#   scripts/mtls/artemis-mtls.sh unrevoke <agent-id>
#   scripts/mtls/artemis-mtls.sh status
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Where private key material lives. Never inside the repo.
MTLS_DIR="${ARTEMIS_MTLS_DIR:-$HOME/.artemis/mtls}"
# Where the committed, human-readable agent registry lives.
AGENT_DIR="${ARTEMIS_AGENT_DIR:-$REPO_ROOT/.agent}"

CLIENTS_DIR="$AGENT_DIR/clients"
CA_KEY="$MTLS_DIR/ca.key"
CA_CRT="$MTLS_DIR/ca.crt"

CA_DAYS="${ARTEMIS_MTLS_CA_DAYS:-3650}"
LEAF_DAYS="${ARTEMIS_MTLS_LEAF_DAYS:-90}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*" >&2; }

require_openssl() {
  command -v openssl >/dev/null 2>&1 || die "openssl not found on PATH"
}

# Emit the SHA-256 fingerprint in Node's `cert.fingerprint256` shape:
# uppercase hex pairs joined by colons, with no "SHA256 Fingerprint=" prefix.
cert_fingerprint() {
  openssl x509 -in "$1" -noout -fingerprint -sha256 \
    | sed 's/^.*Fingerprint=//' \
    | tr '[:lower:]' '[:upper:]'
}

# RFC 3339 / ISO 8601 UTC, which is what the TypeScript registry parses.
# OpenSSL 3 can emit ISO-8601 directly; LibreSSL (macOS /usr/bin/openssl)
# cannot, so fall back to parsing OpenSSL's default "MMM D HH:MM:SS YYYY GMT".
_cert_date() {
  local cert="$1" flag="$2" raw
  raw="$(openssl x509 -in "$cert" -noout -dateopt iso_8601 "$flag" 2>/dev/null || true)"
  if [ -n "$raw" ]; then
    printf '%s\n' "${raw#*=}" | sed 's/ /T/; s/Z*$/Z/'
    return
  fi
  raw="$(openssl x509 -in "$cert" -noout "$flag")"
  python3 -c 'import sys,datetime; print(datetime.datetime.strptime(sys.argv[1].split("=",1)[1].strip(), "%b %d %H:%M:%S %Y %Z").strftime("%Y-%m-%dT%H:%M:%SZ"))' "$raw"
}
cert_not_before() { _cert_date "$1" -startdate; }
cert_not_after()  { _cert_date "$1" -enddate; }

ensure_ca() {
  [ -f "$CA_KEY" ] && [ -f "$CA_CRT" ] \
    || die "no CA at $MTLS_DIR — run: scripts/mtls/artemis-mtls.sh init-ca"
}

cmd_init_ca() {
  require_openssl
  mkdir -p "$MTLS_DIR"
  chmod 700 "$MTLS_DIR"
  if [ -f "$CA_KEY" ]; then
    die "CA already exists at $CA_KEY — refusing to overwrite. Remove it deliberately to rotate."
  fi
  openssl genrsa -out "$CA_KEY" 4096 2>/dev/null
  chmod 600 "$CA_KEY"
  openssl req -x509 -new -nodes -key "$CA_KEY" -sha256 -days "$CA_DAYS" \
    -subj "/CN=artemis-local-mcp-ca/O=Artemis City" -out "$CA_CRT" 2>/dev/null
  chmod 644 "$CA_CRT"
  note "CA created:"
  note "  key  $CA_KEY (0600 — never commit, never copy)"
  note "  cert $CA_CRT"
  note "  fingerprint $(cert_fingerprint "$CA_CRT")"
}

cmd_issue_server() {
  require_openssl; ensure_ca
  local cn="${1:-localhost}"
  local key="$MTLS_DIR/mcp-server.key"
  local crt="$MTLS_DIR/mcp-server.crt"
  local csr; csr="$(mktemp)"
  local ext; ext="$(mktemp)"
  trap 'rm -f "$csr" "$ext"' RETURN

  cat > "$ext" <<EXT
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,DNS:$cn,IP:127.0.0.1,IP:::1
EXT

  openssl genrsa -out "$key" 4096 2>/dev/null
  chmod 600 "$key"
  openssl req -new -key "$key" -subj "/CN=$cn/O=Artemis City" -out "$csr" 2>/dev/null
  openssl x509 -req -in "$csr" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
    -out "$crt" -days "$LEAF_DAYS" -sha256 -extfile "$ext" 2>/dev/null

  note "server certificate issued for CN=$cn (valid ${LEAF_DAYS}d)"
  note "  ARTEMIS_MTLS_CERT=$crt"
  note "  ARTEMIS_MTLS_KEY=$key"
  note "  ARTEMIS_MTLS_CA=$CA_CRT"
}

cmd_issue_client() {
  require_openssl; ensure_ca
  local agent_id="${1:-}"
  [ -n "$agent_id" ] || die "usage: issue-client <agent-id> [--days N] [--routes a,b]"
  shift
  # Agent ids become filenames and YAML keys — keep them boring on purpose.
  [[ "$agent_id" =~ ^[a-z0-9][a-z0-9_-]{0,63}$ ]] \
    || die "agent id must match ^[a-z0-9][a-z0-9_-]{0,63}$ (got '$agent_id')"

  local days="$LEAF_DAYS"
  local routes=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --days)   days="${2:?--days needs a value}"; shift 2 ;;
      --routes) routes="${2:?--routes needs a value}"; shift 2 ;;
      *) die "unknown flag: $1" ;;
    esac
  done

  mkdir -p "$MTLS_DIR/clients" "$CLIENTS_DIR"
  local key="$MTLS_DIR/clients/$agent_id.key"
  local crt="$MTLS_DIR/clients/$agent_id.crt"
  local csr; csr="$(mktemp)"
  local ext; ext="$(mktemp)"
  trap 'rm -f "$csr" "$ext"' RETURN

  cat > "$ext" <<EXT
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
EXT

  openssl genrsa -out "$key" 4096 2>/dev/null
  chmod 600 "$key"
  openssl req -new -key "$key" -subj "/CN=$agent_id/O=Artemis City" -out "$csr" 2>/dev/null
  openssl x509 -req -in "$csr" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
    -out "$crt" -days "$days" -sha256 -extfile "$ext" 2>/dev/null

  local fp; fp="$(cert_fingerprint "$crt")"
  local manifest="$CLIENTS_DIR/$agent_id.yaml"

  # Preserve an operator-curated route list across re-issue (rotation) unless
  # --routes was passed explicitly. Rotating a key should not silently widen
  # or narrow what an agent is allowed to call.
  if [ -z "$routes" ] && [ -f "$manifest" ]; then
    note "re-issuing $agent_id; keeping existing allowed_routes from $manifest"
    python3 - "$manifest" "$fp" "$(cert_not_before "$crt")" "$(cert_not_after "$crt")" <<'PY'
import re, sys
path, fp, nbf, naf = sys.argv[1:5]
text = open(path).read()
def setkey(t, key, value):
    pat = re.compile(rf'^({re.escape(key)}:).*$', re.M)
    return pat.sub(lambda m: f'{m.group(1)} {value}', t) if pat.search(t) else t + f'\n{key}: {value}\n'
text = setkey(text, 'cert_fingerprint_sha256', f'"{fp}"')
text = setkey(text, 'valid_from', f'"{nbf}"')
text = setkey(text, 'valid_to', f'"{naf}"')
text = setkey(text, 'revoked', 'false')
open(path, 'w').write(text)
PY
  else
    # Every route is emitted as a quoted YAML scalar. Unquoted values such as
    # `*` are YAML alias syntax, not strings, and would make the manifest
    # unparseable -- which the server treats as "agent unknown", a denial whose
    # cause is far from obvious. Quote first, debug never.
    local route_block
    if [ -n "$routes" ]; then
      route_block="$(printf '%s' "$routes" | tr ',' '\n' \
        | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' \
        | grep -v '^$' \
        | sed 's/\\/\\\\/g; s/"/\\"/g; s/^/  - "/; s/$/"/')"
      [ -n "$route_block" ] || die "--routes was given but parsed to no usable routes"
    else
      route_block="  - \"*\""
    fi
    cat > "$manifest" <<MANIFEST
# Artemis City — mTLS client manifest
# Generated by scripts/mtls/artemis-mtls.sh. Safe to commit: public data only.
agent_id: $agent_id
display_name: "$agent_id"
cert_fingerprint_sha256: "$fp"
issued_by: "artemis-local-mcp-ca"
valid_from: "$(cert_not_before "$crt")"
valid_to: "$(cert_not_after "$crt")"
allowed_routes:
$route_block
revoked: false
notes: "Issued $(date -u +%Y-%m-%dT%H:%M:%SZ). Rotate before valid_to."
MANIFEST
  fi

  note "client certificate issued for $agent_id (valid ${days}d)"
  note "  fingerprint $fp"
  note "  manifest    $manifest"
  note "  cert        $crt"
  note "  key         $key (0600 — never commit)"
}

cmd_fingerprint() {
  require_openssl
  [ -n "${1:-}" ] || die "usage: fingerprint <path/to/cert.crt>"
  [ -f "$1" ] || die "no such file: $1"
  cert_fingerprint "$1"
}

set_revoked() {
  local agent_id="$1" value="$2"
  local manifest="$CLIENTS_DIR/$agent_id.yaml"
  [ -f "$manifest" ] || die "no manifest for '$agent_id' at $manifest"
  if grep -q '^revoked:' "$manifest"; then
    python3 - "$manifest" "$value" <<'PY'
import re, sys
path, value = sys.argv[1:3]
text = open(path).read()
open(path, 'w').write(re.sub(r'^revoked:.*$', f'revoked: {value}', text, flags=re.M))
PY
  else
    printf 'revoked: %s\n' "$value" >> "$manifest"
  fi
  note "$agent_id revoked=$value ($manifest)"
  note "the memory server reloads manifests on the next request — no restart needed"
}

cmd_revoke()   { [ -n "${1:-}" ] || die "usage: revoke <agent-id>";   set_revoked "$1" true; }
cmd_unrevoke() { [ -n "${1:-}" ] || die "usage: unrevoke <agent-id>"; set_revoked "$1" false; }

cmd_status() {
  printf 'CA dir      : %s\n' "$MTLS_DIR"
  printf 'Registry dir: %s\n' "$CLIENTS_DIR"
  if [ -f "$CA_CRT" ]; then
    printf 'CA          : present (%s)\n' "$(cert_fingerprint "$CA_CRT")"
  else
    printf 'CA          : MISSING — run init-ca\n'
  fi
  printf '\nRegistered clients:\n'
  shopt -s nullglob
  local found=0
  for m in "$CLIENTS_DIR"/*.yaml; do
    found=1
    printf '  %-24s revoked=%-5s valid_to=%s\n' \
      "$(basename "$m" .yaml)" \
      "$(grep -m1 '^revoked:' "$m" | awk '{print $2}')" \
      "$(grep -m1 '^valid_to:' "$m" | cut -d'"' -f2)"
  done
  [ "$found" -eq 1 ] || printf '  (none)\n'
}

case "${1:-}" in
  init-ca)      shift; cmd_init_ca "$@" ;;
  issue-server) shift; cmd_issue_server "$@" ;;
  issue-client) shift; cmd_issue_client "$@" ;;
  fingerprint)  shift; cmd_fingerprint "$@" ;;
  revoke)       shift; cmd_revoke "$@" ;;
  unrevoke)     shift; cmd_unrevoke "$@" ;;
  status)       shift; cmd_status "$@" ;;
  ""|-h|--help|help)
    sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    ;;
  *) die "unknown command '$1' (try --help)" ;;
esac
