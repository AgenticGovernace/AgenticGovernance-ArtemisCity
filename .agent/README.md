# `.agent/` — mutual-TLS agent registry

This directory is the **allow-list and audit trail** for agents that connect to
the Artemis memory server over mutual TLS. It is plain YAML on purpose: a
revocation should be a reviewable diff, not a database mutation.

Two consumers read these files, and neither keeps its own copy:

| Consumer                                           | Reads                           | Purpose                                         |
| -------------------------------------------------- | ------------------------------- | ----------------------------------------------- |
| Memory server (`app/Artemis Agentic Memory Layer`) | `clients/*.yaml`                | Enforces which certificate may call which route |
| Dashboard Security page (`/security`)              | `clients/*.yaml`, `logs/*.yaml` | Shows operators what is being enforced          |

> Not to be confused with `.agents/` (plural) at the repo root, which holds
> agent _skills_. This one is `.agent/` and holds certificate identity.

## Layout

```
.agent/
  clients/<agent-id>.yaml        # one pinned certificate per agent  (commit these)
  logs/handshakes-YYYY-MM.yaml   # append-only decision ledger       (commit these)
```

Private keys are **not** here. They live outside the repository, under
`~/.artemis/mtls` by default, so a stray `git add -A` cannot publish them.

## Client manifest

```yaml
agent_id: codex
display_name: "Codex (CLI)"
cert_fingerprint_sha256: "13:06:A9:...:59" # uppercase hex pairs, 32 bytes
issued_by: "artemis-local-mcp-ca"
valid_from: "2026-08-29T12:26:37Z"
valid_to: "2026-11-27T12:26:37Z"
allowed_routes:
  - "/api/getContext"
  - "/api/listNotes"
revoked: false
notes: "Primary dev agent; rotate before valid_to."
```

Behaviour worth knowing before you hand-edit one:

- **`revoked` is fail-closed.** Anything other than an explicit `false` — a
  missing field, a typo, a comment — denies the agent.
- **Route patterns are exact by default.** `"*"` means every route, `"/api/*"`
  means that subtree; everything else must match the request path exactly.
  Always quote `*`: unquoted, it is YAML alias syntax and the manifest will not
  parse.
- **An unparseable manifest denies the agent**, and is surfaced as a problem on
  the dashboard's Security page rather than being silently skipped.
- **Two manifests claiming one fingerprint disables both.** The server will not
  guess which one wins.
- **Changes take effect on the next request.** The server re-reads this
  directory whenever a file's mtime or size changes; no restart is needed.

## Handshake ledger

Append-only, one file per month, one YAML sequence item per decision:

```yaml
- ts: "2026-08-29T12:01:22Z"
  server_cn: "localhost"
  client_cn: "codex"
  agent_id: "codex"
  client_fingerprint_sha256: "13:06:A9:...:59"
  result: "accepted"
  method: "POST"
  route: "/api/getContext"
  remote: "127.0.0.1"
```

Rejections carry an extra `reason`: `no_client_certificate`,
`unknown_fingerprint`, `revoked`, `not_yet_valid`, `expired`,
`route_not_allowed`, or `tls_unauthorized:<detail>`.

## Operating it

```bash
scripts/mtls/artemis-mtls.sh init-ca                    # once per machine
scripts/mtls/artemis-mtls.sh issue-server               # server certificate
scripts/mtls/artemis-mtls.sh issue-client codex --routes '/api/getContext,/api/listNotes'
scripts/mtls/artemis-mtls.sh status                     # what is registered
scripts/mtls/artemis-mtls.sh revoke codex               # effective immediately
```

Re-running `issue-client` for an existing agent rotates its key and updates the
fingerprint **while preserving the curated `allowed_routes`** — rotation should
not quietly widen or narrow what an agent may do.
