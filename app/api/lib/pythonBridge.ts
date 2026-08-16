import { spawn } from 'child_process';
import { existsSync } from 'fs';
import { dirname, join, resolve } from 'path';

import { APIError } from '../middleware/errorHandler';

type BridgeSuccessEnvelope = {
  ok: true;
  data: unknown;
};

type BridgeErrorEnvelope = {
  ok: false;
  error: string;
  code: string;
};

type BridgeEnvelope = BridgeSuccessEnvelope | BridgeErrorEnvelope;

const CODE_TO_STATUS: Record<string, number> = {
  NOT_FOUND: 404,
  FORBIDDEN: 403,
  INVALID_REQUEST: 400,
  INVALID_JSON: 400,
  RATE_LIMITED: 429,
  PROVIDER_ERROR: 502,
  SERVICE_UNAVAILABLE: 503,
  TIMEOUT: 504,
  UNKNOWN_COMMAND: 500,
  BRIDGE_ERROR: 500,
  INTERNAL_ERROR: 500,
  BRIDGE_UNAVAILABLE: 500,
  MEMORY_IDEMPOTENCY_CONFLICT: 409,
  MEMORY_STORAGE_UNAVAILABLE: 503,
  MEMORY_DATABASE_CONFIGURATION_ERROR: 503,
  MEMORY_DELETE_UNSUPPORTED: 409,
};

export function bridgeCodeToHttpStatus(code: string): number {
  return CODE_TO_STATUS[code] ?? 500;
}

let cachedRepoRoot: string | null = null;

function findRepoRoot(): string {
  if (process.env.ARTEMIS_REPO_ROOT) {
    return resolve(process.env.ARTEMIS_REPO_ROOT);
  }

  if (cachedRepoRoot) {
    return cachedRepoRoot;
  }

  const startingPoints = [__dirname, process.cwd()];

  for (const start of startingPoints) {
    let current = resolve(start);

    while (current !== dirname(current)) {
      if (existsSync(join(current, 'src', 'api_bridge.py'))) {
        cachedRepoRoot = current;
        return current;
      }
      current = dirname(current);
    }
  }

  throw new APIError(
    'Could not locate repository root containing src/api_bridge.py',
    500,
    'BRIDGE_UNAVAILABLE'
  );
}

function findPython(repoRoot: string): string {
  if (process.env.ARTEMIS_PYTHON) {
    return process.env.ARTEMIS_PYTHON;
  }

  const workspaceCandidates = process.platform === 'win32'
    ? [join(repoRoot, '.venv', 'Scripts', 'python.exe')]
    : [join(repoRoot, '.venv', 'bin', 'python')];
  const workspacePython = workspaceCandidates.find(candidate => existsSync(candidate));
  return workspacePython || 'python3';
}

/**
 * Python bridge: JSON stdin/stdout transport between the Express layer
 * and the authoritative Python core in `src/api_bridge.py`.
 *
 * Spawns `python -m src.api_bridge` per call. Resolves with the envelope's
 * `data` field on success; throws an `APIError` mapped to the matching HTTP
 * status on failure.
 */
export function callBridge(command: string, payload: Record<string, unknown> = {}): Promise<unknown> {
  const repoRoot = findRepoRoot();
  const python = findPython(repoRoot);
  const request = JSON.stringify({ command, payload });

  return new Promise((resolvePromise, reject) => {
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
      console.error(`[python-bridge] spawn failed (${err.name})`);
      reject(new APIError('Python bridge is unavailable', 500, 'BRIDGE_UNAVAILABLE'));
    });

    child.on('close', () => {
      let envelope: BridgeEnvelope;
      try {
        envelope = JSON.parse(stdout) as BridgeEnvelope;
      } catch {
        console.error(
          `[python-bridge] invalid response (stdout_bytes=${Buffer.byteLength(stdout)}, stderr_bytes=${Buffer.byteLength(stderr)})`
        );
        reject(
          new APIError(
            'Python bridge returned an invalid response',
            500,
            'BRIDGE_ERROR'
          )
        );
        return;
      }

      if (envelope.ok === true) {
        resolvePromise(envelope.data);
        return;
      }

      const status = bridgeCodeToHttpStatus(envelope.code);
      reject(new APIError(envelope.error, status, envelope.code));
    });

    child.stdin.write(request);
    child.stdin.end();
  });
}
