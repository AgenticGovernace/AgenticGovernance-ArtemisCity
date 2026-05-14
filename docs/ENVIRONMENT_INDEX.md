# Artemis City Environment Index

This index lists the environment variables read by code in this repository and the local env file where each variable is expected during development. Run `./setup_secrets.sh` from the repository root to scaffold the ignored `.env` files.

## Env File Locations

| Env file | Runtime surface | Notes |
| --- | --- | --- |
| `.env` | Root local shell, Python modules that call `load_dotenv()`, shared values for demos and clients | Broad local development file. Use this when exporting env from the repo root. |
| `src/.env` | Python memory/orchestrator code under `src/` | Used by `src/mcp/config.py` through `python-dotenv` when the process is launched from `src/` or configured to load this file. |
| `src/mcp-server/.env` | TypeScript MCP server | Used by `src/mcp-server/src/index.ts` via `import 'dotenv/config'` when running from `src/mcp-server`. |
| `web/api/.env` | Express API and FastAPI API surfaces | The code reads process environment. Source this file or pass it through a process manager/env-file option. |
| `mcp-server/.env` | Docker Compose wrapper under `mcp-server/` | Used by `mcp-server/docker-compose.yml` when running Compose from that directory. |

## Variable Index

| Variable | Expected location(s) | Used by |
| --- | --- | --- |
| `API_PORT` | `web/api/.env`, `.env` | `web/api/index.ts` Express server port. |
| `API_RATE_LIMIT_MAX` | `src/mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts`. |
| `API_RATE_LIMIT_MESSAGE` | `src/mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts`. |
| `API_RATE_LIMIT_WINDOW_MS` | `src/mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts`. |
| `ARTEMIS_API_KEY_*` | `web/api/.env`, `.env` | `web/api/middleware/auth.ts`; format is `<key>:<role>:<perm1,perm2,...>`. |
| `CORS_ORIGINS` | `src/mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts` and MCP server CORS setup. |
| `FASTAPI_API_KEY` | `web/api/.env`, `.env` | `web/api/main.py` API key auth. Falls back to `MCP_API_KEY`. |
| `FASTAPI_CORS_ORIGINS` | `web/api/.env`, `.env` | `web/api/main.py` CORS allowlist. |
| `LEGAL_DATASET_PATH` | `src/.env`, `.env` | `Projects/Codex_Experiments/legal_summarization/dataset_loader.py`. |
| `MCP_API_KEY` | `.env`, `src/.env`, `src/mcp-server/.env`, `web/api/.env`, `mcp-server/.env` | MCP server auth, Python memory client, Express fallback auth, FastAPI fallback auth, Docker Compose wrapper. Use the same value everywhere. |
| `MCP_BASE_URL` | `.env`, `src/.env` | `integration/memory_client.py` and demos. |
| `MCP_LOG_LEVEL` | `src/mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts` and logger setup. |
| `NODE_ENV` | `web/api/.env`, `.env` | `web/api/middleware/auth.ts` and `web/api/middleware/errorHandler.ts`. |
| `OBSIDIAN_API_KEY` | `src/mcp-server/.env`, `mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts` and Obsidian REST client. |
| `OBSIDIAN_BASE_URL` | `src/mcp-server/.env`, `mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts` and Obsidian REST client. |
| `OBSIDIAN_VAULT_PATH` | `.env`, `src/.env`, `src/mcp-server/.env`, `web/api/.env` | `src/mcp/config.py`, `src/mcp-server/src/config/index.ts`, and `web/api/controllers/memoryController.ts`. |
| `PORT` | `src/mcp-server/.env`, `mcp-server/.env`, `.env` | TypeScript MCP server port and Docker Compose host-port interpolation. |
| `PROXY_TIMEOUT` | `src/mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts`. |
| `SKIP_AUTH` | `web/api/.env`, `.env` | `web/api/middleware/auth.ts`; only honored when `NODE_ENV=development`. |
| `STORAGE_PATH` | `src/mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts`; comma-separated paths. |
| `WORKER_POOL_SIZE` | `src/mcp-server/.env`, `.env` | `src/mcp-server/src/config/index.ts`. |

## Notes

- `MCP_API_KEY` must match between clients and every MCP/API surface that validates client requests.
- `OBSIDIAN_API_KEY` is not generated; copy it from Obsidian's Local REST API plugin settings.
- `web/api/.env` is an index and convenience file. The current Express and FastAPI entrypoints do not call `dotenv` directly, so the file must be sourced or passed in by the command that starts the service.
