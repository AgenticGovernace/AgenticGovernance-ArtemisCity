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
