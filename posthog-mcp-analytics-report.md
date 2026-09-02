# PostHog MCP Analytics — Setup Report

## Summary

Instrumented the **artemis-memory** MCP server (`services/mcp/artemis-memory`) with PostHog MCP analytics using Path P1 (Python `posthog.mcp.instrument()`). Every tool call, `tools/list`, and `initialize` handshake the server handles will now emit `$mcp_*` events to PostHog.

The **artemis-validation** server was not instrumented: it has no CLI entry point (`__main__.py` or `[project.scripts]`), and its `server.py` module explicitly bans environment variable reads (enforced by tests). Instrumentation should be added when a standalone entry point is created for that server.
@todo

---

## What Changed

### Path P1 — official `mcp` SDK server, Python

The server uses `mcp[cli]==2.0.0` (`MCPServer` from `mcp.server.mcpserver`), which is `MCPServer` — FastMCP's name on `mcp` 2.x. `instrument()` from `posthog.mcp` supports it directly.

---

## Files Modified or Created

| File                                                             | Change                                                                                                                                               |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `services/mcp/artemis-memory/pyproject.toml`                     | Added `"posthog>=7.21"` to `[project.dependencies]`                                                                                                  |
| `services/mcp/artemis-memory/src/artemis_memory_mcp/__main__.py` | Added PostHog client at module scope; `instrument()` call in `main()` after server construction; SIGTERM handler and `shutdown()` on both transports |
| `services/mcp/artemis-memory/.env.example`                       | Added `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` placeholder entries                                                                                 |
| `services/mcp/artemis-memory/.env`                               | Created with `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` set to the project values (**not committed**)                                                |

### Installed package

`posthog==7.44.0` (satisfies `>=7.21`) was installed into `services/mcp/artemis-memory/.venv` via `uv pip install`.

---

## How It Works

```python
# __main__.py — module scope (reads env at import time, once)
_posthog = Posthog(
    os.environ["POSTHOG_PROJECT_TOKEN"],
    host=os.environ["POSTHOG_HOST"],
    enable_exception_autocapture=True,
) if POSTHOG_PROJECT_TOKEN else None

# main() — immediately after building the server
if _posthog is not None:
    _mcp_instrument(server, _posthog)
```

The server is guarded: if `POSTHOG_PROJECT_TOKEN` is unset the server starts normally with no analytics. In a `DEBUG=1` environment it prints a warning to stderr (never stdout, which is the protocol channel for STDIO).

Shutdown is handled via:

- **STDIO**: SIGTERM handler + `posthog.shutdown()` after `server.run()` returns
- **HTTP**: `posthog.shutdown()` in a `finally` block around `server.run()`

---

## Events You'll See in PostHog

Once the server handles its next MCP request:

| Event             | When                                                                       |
| ----------------- | -------------------------------------------------------------------------- |
| `$mcp_initialize` | Client connects                                                            |
| `$mcp_tools_list` | Client calls `tools/list`                                                  |
| `$mcp_tool_call`  | Any of `write-memory`, `read-memory`, `search-memory`, `get-memory-status` |
| `$exception`      | Any tool call that raises or returns `isError: true`                       |

---

## Manual Steps Required

1. **Set credentials on the server host.** The `.env` file at `services/mcp/artemis-memory/.env` holds the project token. On any deployment that doesn't load this file, set these two variables in the environment:

   ```
   POSTHOG_PROJECT_TOKEN=phc_AhfFjdyKyXCkdQwgVED9Dxr85Brqc3nWX49LismDMLYD
   POSTHOG_HOST=https://us.i.posthog.com
   ```

2. **Keep `.env` out of git.** Verify `services/mcp/artemis-memory/.env` is covered by `.gitignore` (the wizard-tools `set_env_values` call ensures this, but double-check before pushing).

3. **Update the lockfile.** The `uv.lock` for artemis-memory needs to be regenerated once the parent `artemis-city` `pyproject.toml` build issue is resolved. Run `uv lock` from `services/mcp/artemis-memory/`.

4. **View the dashboard.** See `$mcp_*` events and build dashboards at [PostHog MCP Analytics docs](https://posthog.com/docs/mcp-analytics).

---

## Note on artemis-validation

The `artemis-validation` server (`services/mcp/artemis-validation`) has no CLI entry point. Its test suite explicitly asserts that `server.py` contains no `os.getenv` / `os.environ` calls. To instrument it, create a `__main__.py` (or a `[project.scripts]` entry) that:

1. Bootstraps the `AuthVerifier` and `AuthenticationRequest` from environment credentials
2. Calls `create_server(verifier=..., authentication_request=...)`
3. Instruments the returned server with `instrument(server, posthog)`
4. Adds a `[project.scripts]` entry pointing to the new entry function
