/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Canonical FastAPI dashboard key, read from the project's root `.env`
   * (written by `setup_secrets.sh`). Exposed to the client because
   * `vite.config.ts` lists it in `envPrefix`.
   */
  readonly FASTAPI_API_KEY?: string;
  /** Shared MCP key fallback, same source as above. */
  readonly MCP_API_KEY?: string;
  /** Optional override placed in `app/web/frontend/.env` (VITE_-prefixed). */
  readonly VITE_FASTAPI_API_KEY?: string;
  /** Optional override placed in `app/web/frontend/.env` (VITE_-prefixed). */
  readonly VITE_MCP_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
