/**
 * Python Bridge
 *
 * Invokes the authoritative Python core (src/api_bridge.py) for registry and
 * governance operations, exchanging JSON over a child process' stdin/stdout.
 *
 * The TypeScript Express layer is the public HTTP boundary; the Python core
 * remains the single source of truth for agent state. Keeping the bridge
 * stdlib-only (no second HTTP server) means the Python side stays testable in
 * CI without web dependencies.
 */

import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

import { APIError } from '../middleware/errorHandler';

/** Bridge error code -> HTTP status mapping. */
const CODE_TO_STATUS: Record<string, number> = {
  NOT_FOUND: 404,
  INVALID_REQUEST: 400,
  INVALID_JSON: 400,
  UNKNOWN_COMMAND: 500,
  INTERNAL_ERROR: 500,
  BRIDGE_ERROR: 500,
};

interface BridgeSuccess {
  ok: true;
  data: any;
}

interface BridgeFailure {
  ok: false;
  error: string;
  code: string;
}

type BridgeEnvelope = BridgeSuccess | BridgeFailure;

let cachedRepoRoot: string | null = null;

/**
 * Locate the repository root by walking up from this file until a directory
 * containing `src/api_bridge.py` is found. Works under both ts-node-dev
 * (app/api/lib) and the compiled dist layout (app/api/dist/lib).
 */
function findRepoRoot(): string {
  if (cachedRepoRoot) return cachedRepoRoot;

  const override = process.env.ARTEMIS_REPO_ROOT;
  if (override && fs.existsSync(path.join(override, 'src', 'api_bridge.py'))) {
    cachedRepoRoot = override;
    return override;
  }

  let dir = __dirname;
  for (let i = 0; i < 10; i++) {
    if (fs.existsSync(path.join(dir, 'src', 'api_bridge.py'))) {
      cachedRepoRoot = dir;
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }

  throw new APIError(
    'Python core not found (src/api_bridge.py); set ARTEMIS_REPO_ROOT',
    500,
    'BRIDGE_UNAVAILABLE'
  );
}

/**
 * Run a single bridge command and resolve with its `data` payload.
 * Throws an APIError (mapped to the appropriate HTTP status) on failure.
 */
export function callBridge(command: string, payload: Record<string, any> = {}): Promise<any> {
  const repoRoot = findRepoRoot();
  const python = process.env.ARTEMIS_PYTHON || 'python3';
  const request = JSON.stringify({ command, payload });

  return new Promise((resolve, reject) => {
    const child = spawn(python, ['-m', 'src.api_bridge'], {
      cwd: repoRoot,
      env: process.env,
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });

    child.on('error', (err) => {
      reject(new APIError(`Failed to spawn Python bridge: ${err.message}`, 500, 'BRIDGE_UNAVAILABLE'));
    });

    child.on('close', () => {
      let envelope: BridgeEnvelope;
      try {
        envelope = JSON.parse(stdout) as BridgeEnvelope;
      } catch {
        reject(
          new APIError(
            `Invalid bridge response: ${stdout || stderr || 'no output'}`,
            500,
            'BRIDGE_ERROR'
          )
        );
        return;
      }

      if (envelope.ok) {
        resolve(envelope.data);
      } else {
        const status = CODE_TO_STATUS[envelope.code] ?? 500;
        reject(new APIError(envelope.error, status, envelope.code));
      }
    });

    child.stdin.write(request);
    child.stdin.end();
  });
}
