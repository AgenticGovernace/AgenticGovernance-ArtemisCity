/**
 * Mutual-TLS configuration for the Artemis memory server.
 *
 * Unlike `config/index.ts`, nothing here runs at import time. TLS settings are
 * resolved on demand by `loadTlsConfig()` so the module stays constructible in
 * tests and so a misconfiguration surfaces as a thrown error at the call site
 * rather than a bare `process.exit(1)` during module resolution.
 *
 * @module config/tls
 */

import fs from "fs";
import path from "path";

/** Resolved, validated mTLS settings plus the key material they point at. */
export interface TlsConfig {
  /** Whether the listener should terminate TLS and demand a client cert. */
  enabled: boolean;
  /**
   * Interface to bind. Defaults to loopback — this is a local trust domain,
   * and a plaintext bearer-token listener should not sit on every interface.
   * Containers must override it (docker-compose.yml sets 0.0.0.0), because
   * loopback inside a container is unreachable from a published port.
   */
  host: string;
  /** PEM bytes for the server certificate, key, and issuing CA. */
  cert?: Buffer;
  key?: Buffer;
  ca?: Buffer;
  /** Paths the PEM bytes came from, for logging and the status endpoint. */
  certPath?: string;
  keyPath?: string;
  caPath?: string;
  /** Lowest TLS version accepted by the listener. */
  minVersion: "TLSv1.2" | "TLSv1.3";
  /**
   * Whether a valid `Authorization: Bearer` token is *also* required once the
   * certificate has established identity. Certificates answer "who are you";
   * the token remains a cheap scope/rotation lever. Defaults to on.
   */
  requireBearer: boolean;
  /** Directory holding `clients/` manifests and `logs/` handshake ledgers. */
  agentDir: string;
}

/** Raised when mTLS is switched on but the key material cannot be used. */
export class TlsConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TlsConfigError";
  }
}

const truthy = (value: string | undefined, fallback: boolean): boolean => {
  if (value === undefined || value.trim() === "") return fallback;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
};

const readPem = (label: string, filePath: string): Buffer => {
  let resolved: string;
  try {
    resolved = path.resolve(filePath);
  } catch {
    throw new TlsConfigError(`${label} path is not resolvable: ${filePath}`);
  }
  let bytes: Buffer;
  try {
    bytes = fs.readFileSync(resolved);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new TlsConfigError(
      `${label} could not be read (${resolved}): ${detail}`,
    );
  }
  if (!bytes.includes("-----BEGIN")) {
    throw new TlsConfigError(
      `${label} at ${resolved} does not look like PEM (no BEGIN block).`,
    );
  }
  return bytes;
};

/**
 * Default location of the agent registry: `<repo>/.agent`, matching what
 * `scripts/mtls/artemis-mtls.sh` writes. Overridable with `ARTEMIS_AGENT_DIR`
 * so the manifests can live inside an Obsidian vault instead.
 */
export const defaultAgentDir = (
  env: NodeJS.ProcessEnv = process.env,
): string => {
  if (env.ARTEMIS_AGENT_DIR && env.ARTEMIS_AGENT_DIR.trim()) {
    return path.resolve(env.ARTEMIS_AGENT_DIR.trim());
  }
  // src/config/tls.ts -> src/config -> src -> <memory server> -> app -> repo root
  return path.resolve(__dirname, "..", "..", "..", "..", ".agent");
};

/**
 * Resolve mTLS settings from the environment.
 *
 * Fails closed: when `ARTEMIS_MTLS_ENABLED` is on but any of the certificate,
 * key, or CA is missing or unreadable, this throws rather than quietly
 * downgrading to plaintext. A silent downgrade is the one outcome that would
 * make the whole feature worthless.
 *
 * @param env - Environment to read. Injectable so tests need not mutate `process.env`.
 * @returns Validated configuration, with `enabled: false` when mTLS is off.
 * @throws {TlsConfigError} When mTLS is enabled but unusable.
 */
export const loadTlsConfig = (
  env: NodeJS.ProcessEnv = process.env,
): TlsConfig => {
  const enabled = truthy(env.ARTEMIS_MTLS_ENABLED, false);
  const agentDir = defaultAgentDir(env);
  const minVersionRaw = (env.ARTEMIS_MTLS_MIN_VERSION ?? "TLSv1.2").trim();
  if (minVersionRaw !== "TLSv1.2" && minVersionRaw !== "TLSv1.3") {
    throw new TlsConfigError(
      `ARTEMIS_MTLS_MIN_VERSION must be TLSv1.2 or TLSv1.3 (got '${minVersionRaw}').`,
    );
  }

  const base = {
    host: (env.ARTEMIS_MTLS_HOST ?? "127.0.0.1").trim() || "127.0.0.1",
    minVersion: minVersionRaw,
    requireBearer: truthy(env.ARTEMIS_MTLS_REQUIRE_BEARER, true),
    agentDir,
  } as const;

  if (!enabled) {
    return { enabled: false, ...base };
  }

  const certPath = env.ARTEMIS_MTLS_CERT?.trim();
  const keyPath = env.ARTEMIS_MTLS_KEY?.trim();
  const caPath = env.ARTEMIS_MTLS_CA?.trim();

  const missing = [
    !certPath && "ARTEMIS_MTLS_CERT",
    !keyPath && "ARTEMIS_MTLS_KEY",
    !caPath && "ARTEMIS_MTLS_CA",
  ].filter(Boolean);
  if (missing.length > 0) {
    throw new TlsConfigError(
      `ARTEMIS_MTLS_ENABLED is on but ${missing.join(", ")} ${
        missing.length === 1 ? "is" : "are"
      } unset. Run: scripts/mtls/artemis-mtls.sh init-ca && issue-server`,
    );
  }

  return {
    enabled: true,
    ...base,
    cert: readPem("ARTEMIS_MTLS_CERT", certPath as string),
    key: readPem("ARTEMIS_MTLS_KEY", keyPath as string),
    ca: readPem("ARTEMIS_MTLS_CA", caPath as string),
    certPath: path.resolve(certPath as string),
    keyPath: path.resolve(keyPath as string),
    caPath: path.resolve(caPath as string),
  };
};
