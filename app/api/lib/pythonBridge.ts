/**
 * Python bridge — JSON stdin/stdout transport between the Express layer
 * and the authoritative Python core (see ``src/api_bridge.py``).
 *
 * Spawns ``python -m src.api_bridge`` per call. Resolves with the
 * envelope's ``data`` field on success; throws an ``APIError`` mapped to
 * the matching HTTP status on failure. Repo root is discovered by
 * walking up from this file's location looking for
 * ``src/api_bridge.py`` — overridable via ``ARTEMIS_REPO_ROOT``.
 */

import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

import { APIError } from '../middleware/errorHandler';

interface BridgeEnvelope {
  ok: boolean;
  data?: any;
  error?: string;
  code?: string;
}

const CODE_TO_STATUS: Record<string, number> = {
  NOT_FOUND: 404,
  INVALID_REQUEST: 400,
  INVALID_JSON: 400,
  UNKNOWN_COMMAND: 500,
  BRIDGE_ERROR: 500,
  INTERNAL_ERROR: 500,
  BRIDGE_UNAVAILABLE: 500,
};

let _cachedRoot: string | null = null;

function findRepoRoot(): string {
  if (process.env.ARTEMIS_REPO_ROOT) {
    return process.env.ARTEMIS_REPO_ROOT;
  }
  if (_cachedRoot) {
    return _cachedRoot;
  }
  let dir = __dirname;
  for (let i = 0; i < 10; i++) {
    if (fs.existsSync(path.join(dir, 'src', 'api_bridge.py'))) {
      _cachedRoot = dir;
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
  throw new APIError(
    'Could not locate src/api_bridge.py; set ARTEMIS_REPO_ROOT',
    500,
    'BRIDGE_UNAVAILABLE'
  );
}

/**
 * Run one Python bridge command and resolve with its `data` payload.
 * Throws an `APIError` mapped to the appropriate HTTP status when the bridge fails.
 *
 * @param command - Bridge command name to invoke inside the Python core.
 * @param payload - JSON-serializable payload forwarded alongside the command.
 * @returns Promise resolving to the `data` field returned by the Python bridge.
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

    child.stdout.on('data', (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString();
    });

    child.on('error', (err: Error) => {
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
        const status = envelope.code ? (CODE_TO_STATUS[envelope.code] ?? 500) : 500;
        reject(new APIError(envelope.error ?? 'Bridge error', status, envelope.code));
      }
    });

    child.stdin.write(request);
    child.stdin.end();
  });
}
