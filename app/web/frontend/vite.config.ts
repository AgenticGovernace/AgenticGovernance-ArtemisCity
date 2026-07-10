import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

// Resolve the repo root from this config's location so Vite can read the
// project's root `.env` (written by `setup_secrets.sh`) instead of
// requiring a separate `app/web/frontend/.env`.
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Read the project's root .env so `FASTAPI_API_KEY` / `MCP_API_KEY`
  // (provisioned by setup_secrets.sh) flow into Vite without duplication.
  envDir: repoRoot,
  // Default-deny everything except `VITE_*`. Explicitly allow exactly the
  // two FastAPI dashboard keys api.ts reads so we don't accidentally
  // bundle any other non-VITE_ secrets from the root .env into the
  // client. (envPrefix is prefix-matching, but these full names exact-
  // match the only vars we want to expose.)
  envPrefix: ['VITE_', 'FASTAPI_API_KEY', 'MCP_API_KEY'],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000', // FastAPI backend
        changeOrigin: true,
        // No rewrite needed: the /api prefix is forwarded as-is.

      },
      // /health is unauthenticated on the FastAPI side and used by the
      // sidebar's live session card. Forward it without rewriting.
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
