# Security Policy

This document owns secret handling, key rotation, and incident response for
Artemis City. It is referenced by `README.md`, `CLAUDE.md` / `AGENTS.md`, and
`.github/instructions/instructions.md` as the authoritative source on these
topics.

## Reporting a vulnerability

Report suspected vulnerabilities privately to the maintainer at
**prinstonpalmer879@gmail.com**. Do not open a public issue for an unpatched
security problem. Please include a description, reproduction steps, and the
affected component (Python core, TS Express API, FastAPI dashboard, or the
standalone memory-layer MCP server).

## Secret provisioning

Secrets are **never committed**. The root `.gitignore` already excludes every
`.env` file, and pre-commit hooks (`detect-private-key`, `detect-secrets`, and
a custom staged-file grep) block accidental commits.

`./setup_secrets.sh` is the canonical provisioner. It writes four `.env` files,
each read by a different consumer:

| File | Read by |
|---|---|
| `.env` | Python core, FastAPI dashboard |
| `app/api/.env` | TS Express API |
| `src/.env` | Memory-layer Python |
| `src/Artemis Agentic Memory Layer/.env` | Standalone MCP server (if present) |

Canonical keys, and the files each one belongs in:

| Key | `.env` | `app/api/.env` | `src/.env` | `…Memory Layer/.env` |
|---|:-:|:-:|:-:|:-:|
| `MCP_API_KEY` | ✓ | ✓ | ✓ | ✓ |
| `FASTAPI_API_KEY` | ✓ | | | |
| `ARTEMIS_API_KEY_DEFAULT` | ✓ | ✓ | | |

The script has three modes:

- `./setup_secrets.sh` (default) — **sync**: discover the value already present
  in root `.env`, propagate it into every other file that declares the same key,
  and generate any missing keys. Existing values are preserved.
- `./setup_secrets.sh --check` — **read-only**: report any out-of-sync or missing
  keys and exit `1` if drift is found. Safe to run in CI.
- `./setup_secrets.sh --regenerate` — **force-rotate ALL canonical keys**. Use
  this after a leak (see below).

## Secret scoping

- **Per-environment secrets.** Deploy credentials are scoped per GitHub
  Environment (`dev` / `staging` / `prod`), not per repository. Production
  credentials are therefore unreachable from a `dev` or `staging` deploy.
- **Least privilege.** `MCP_API_KEY` is shared across components; `FASTAPI_API_KEY`
  is dashboard-only; `ARTEMIS_API_KEY_DEFAULT` is a `key:role:permissions` tuple
  used by the TS Express API. Do not widen a key's file set beyond the table above.

## Secret scanning gates

- **`detect-secrets`** runs both as a pre-commit hook and as the CircleCI
  `secrets-check` job, diffing tracked files against `.secrets.baseline`. A newly
  introduced secret that is not already audited in the baseline fails the check.
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
