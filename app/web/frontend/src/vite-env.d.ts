/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API key for the FastAPI dashboard backend (sent as X-API-Key on every request). */
  readonly VITE_FASTAPI_API_KEY?: string;
  /** Fallback shared key; matches MCP_API_KEY in the root .env. */
  readonly VITE_MCP_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
