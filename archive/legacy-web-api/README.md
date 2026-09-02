# Legacy Web API Copy

This directory holds the old `../../app/web/backend` FastAPI copies that predate the
current project split.

The maintained dashboard backend is `app/api/main.py`. The React frontend lives
under `app/web/frontend/` and proxies `/api/*` to that FastAPI backend during
local development.

These files are retained only for reference while the repository is being
separated into clearer project surfaces.
