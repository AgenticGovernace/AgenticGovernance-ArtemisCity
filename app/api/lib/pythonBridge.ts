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
  INVALID_REQUEST: 400,
  INVALID_JSON: 400,
  UNKNOWN_COMMAND: 500,
  BRIDGE_ERROR: 500,
  INTERNAL_ERROR: 500,
  BRIDGE_UNAVAILABLE: 500,
};

function findRepoRoot(): string {
  if (process.env.ARTEMIS_REPO_ROOT) {
    return resolve(process.env.ARTEMIS_REPO_ROOT);
  }

  const startingPoints = [__dirname, process.cwd()];

  for (const start of startingPoints) {
    let current = resolve(start);

    while (current !== dirname(current)) {
      if (existsSync(join(current, 'src', 'api_bridge.py'))) {
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
        const status = CODE_TO_STATUS[envelope.code] ?? 500;
        reject(new APIError(envelope.error, status, envelope.code));
      }
    });

    child.stdin.write(request);
    child.stdin.end();
  });
}
