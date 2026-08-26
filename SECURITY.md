# Security Policy

This document owns secret handling, key rotation, and incident response for
Artemis City. It is referenced by `README.md`, `CLAUDE.md` / `AGENTS.md`, and
`.github/instructions/instructions.md` as the authoritative source on these
topics.

## Reporting a vulnerability

Report suspected vulnerabilities privately to the maintainer at
**<prinstonpalmer879@gmail.com>**. Do not open a public issue for an unpatched
security problem. Please include a description, reproduction steps, and the
affected component (Python core, TS Express API, FastAPI dashboard, or the
standalone memory-layer MCP server).

## Secret provisioning

Secrets are **never committed**. The root `.gitignore` already excludes every
`.env` file, and pre-commit hooks (`detect-private-key`, `detect-secrets`, and
a custom staged-file grep) block accidental commits.

`./setup_secrets.sh` is the canonical provisioner. Root `.env` is the only
operator-edited local source. It writes seven outputs:

| File                                    | Read by                                            |
| --------------------------------------- | -------------------------------------------------- |
| `.env`                                  | Operator source; Python core, FastAPI, and Compose |
| `app/api/.env`                          | TypeScript Express API and Python bridge           |
| `app/web/frontend/.env`                 | Vite browser-facing derived aliases                |
| `src/.env`                              | Python source runtime                              |
| `src/Artemis Agentic Memory Layer/.env` | Obsidian REST shell                                |
| `services/mcp/artemis-memory/.env`      | Memory MCP server                                  |
| `services/prove/.env`                   | Provenance service, proxy, MCP, and UI mesh        |

`config/environment-contract.yaml` and the declared templates own each view's
shape. `VITE_FASTAPI_API_KEY`, `VITE_MCP_API_KEY`, and
`ARTEMIS_VECTOR_STORE_API_KEY` are derived from their root source keys. Do not
put an independent credential in a derived field.

The script has three modes:

- `./setup_secrets.sh` (default) — **sync**: preserve ordinary and
  operator-supplied root values, generate missing owned secrets, and replace
  every service view from its template plus root values.
- `./setup_secrets.sh --check` — **read-only**: report any out-of-sync or missing
  keys and exit `1` if local runtime drift is found. PR CI instead runs
  `make env-check`, which never requires a populated `.env`.
- `./setup_secrets.sh --regenerate` — rotate only the six repository-owned
  secrets. Operator credentials, URLs, and identities are preserved.

## Secret scoping

- **Per-environment secrets.** Deploy credentials are scoped per GitHub
  Environment (`dev` / `staging` / `prod`), not per repository. Production
  credentials are therefore unreachable from a `dev` or `staging` deploy.
- **Least privilege.** `MCP_API_KEY` is shared only with declared consumers;
  `FASTAPI_API_KEY` is the dashboard source; `ARTEMIS_API_KEY_DEFAULT` is a
  `key:role:permissions` tuple for Express. Do not widen a template's key set
  without updating and testing the contract.

## Secret scanning gates

- **`detect-secrets`** runs as a pre-commit hook against
  `.secrets.baseline`. A newly introduced secret that is not already audited in
  the baseline fails the local check.
- To (re)generate the baseline after an intentional, audited change:
  `detect-secrets scan > .secrets.baseline` then review with
  `detect-secrets audit .secrets.baseline`.

## Key rotation

Rotate on any suspected exposure, on staff changes, and on a periodic schedule:

1. Run `./setup_secrets.sh --regenerate` to mint fresh values for every canonical
   key across all `.env` files.
2. Update the corresponding **GitHub Environment** secrets (and any deploy-provider
   secret store) so running services pick up the new values.
3. Redeploy each environment so the rotated secrets take effect.
4. Invalidate the old credentials at their source (API providers, databases).

## Incident response

If a secret is leaked or a compromise is suspected:

1. **Rotate immediately** — `./setup_secrets.sh --regenerate` and update the
   environment/provider secret stores (rotation steps above).
2. **Revoke** the exposed credential at its source so the old value cannot be used.
3. **Purge from history** if the secret was committed — remove it from the working
   tree, and scrub it from git history (e.g. `git filter-repo`) before force-pushing;
   a value that ever reached a remote must be treated as compromised regardless.
4. **Audit** access logs for the exposure window to assess blast radius.
5. **Record** the incident (what leaked, when, remediation) and confirm the
   `detect-secrets` baseline no longer contains the value.
