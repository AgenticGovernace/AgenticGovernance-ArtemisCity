/**
 * Vault-backed registry of agents authorised to reach the memory server.
 *
 * The registry is a directory of YAML manifests (`.agent/clients/*.yaml`),
 * one per agent, written by `scripts/mtls/artemis-mtls.sh`. Keeping the
 * allow-list in versioned, human-readable files rather than a database is
 * deliberate: revocation becomes a reviewable diff, and the same files feed
 * both this server and the dashboard's Security page.
 *
 * Manifests are re-read whenever the directory's contents change on disk, so
 * `artemis-mtls.sh revoke <agent>` takes effect on the very next request with
 * no restart.
 *
 * @module security/agentRegistry
 */

import fs from "fs";
import path from "path";
import YAML from "yaml";
import { logger } from "../utils/logger";

/** One agent's entry in the registry, normalised from its YAML manifest. */
export interface ClientManifest {
  agentId: string;
  displayName: string;
  /** SHA-256 fingerprint, uppercase hex pairs joined by ':' (Node's shape). */
  fingerprint: string;
  issuedBy: string;
  validFrom: Date | null;
  validTo: Date | null;
  /** Route patterns this agent may call. See `routeAllowed` for semantics. */
  allowedRoutes: string[];
  revoked: boolean;
  notes: string;
  /** Absolute path of the manifest, so denials can name the file to edit. */
  sourceFile: string;
}

/** Why a handshake or request was refused. Recorded verbatim in the ledger. */
export type DenyReason =
  | "no_client_certificate"
  | "unknown_fingerprint"
  | "revoked"
  | "not_yet_valid"
  | "expired"
  | "route_not_allowed";

export type AuthorizationResult =
  | { allowed: true; client: ClientManifest }
  | {
      allowed: false;
      reason: DenyReason;
      status: number;
      /** Present when the certificate was recognised but refused anyway. */
      client?: ClientManifest;
    };

/** A parse failure on one manifest. Surfaced rather than swallowed. */
export interface ManifestProblem {
  file: string;
  error: string;
}

export interface RegistrySnapshot {
  clients: ClientManifest[];
  problems: ManifestProblem[];
  directory: string;
}

/**
 * Normalise a SHA-256 fingerprint to Node's `cert.fingerprint256` shape.
 *
 * Accepts the several forms operators paste in practice: with or without the
 * `SHA256 Fingerprint=` prefix from `openssl`, colon-separated or bare hex,
 * upper or lower case.
 *
 * @param raw - Fingerprint text from a manifest or a certificate.
 * @returns Uppercase hex pairs joined by ':', or '' when unparseable.
 */
export const normalizeFingerprint = (raw: unknown): string => {
  if (typeof raw !== "string") return "";
  const hex = raw
    .replace(/^\s*sha-?256\s*fingerprint\s*=/i, "")
    .replace(/[^0-9a-fA-F]/g, "")
    .toUpperCase();
  if (hex.length !== 64) return "";
  return (hex.match(/.{2}/g) ?? []).join(":");
};

const asDate = (raw: unknown): Date | null => {
  if (raw instanceof Date) return Number.isNaN(raw.getTime()) ? null : raw;
  if (typeof raw !== "string" || !raw.trim()) return null;
  const parsed = new Date(raw.trim());
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const asStringArray = (raw: unknown): string[] => {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((entry): entry is string => typeof entry === "string")
    .map((entry) => entry.trim())
    .filter(Boolean);
};

/**
 * Decide whether an agent's `allowed_routes` cover a concrete request path.
 *
 * Supported patterns:
 *   - `"*"`            — every route on this server.
 *   - `"/api/prefix/*"`— that path and anything beneath it.
 *   - `"/api/getContext"` — exact match (trailing slash insensitive).
 *
 * Matching is exact-by-default on purpose: a typo in a manifest should shut an
 * agent out, never quietly widen its reach.
 *
 * @param patterns - The manifest's `allowed_routes` entries.
 * @param routePath - Request path, already stripped of query string.
 * @returns True when at least one pattern covers the path.
 */
export const routeAllowed = (
  patterns: string[],
  routePath: string,
): boolean => {
  const target = routePath.replace(/\/+$/, "") || "/";
  return patterns.some((pattern) => {
    const candidate = pattern.trim();
    if (candidate === "*") return true;
    if (candidate.endsWith("/*")) {
      const prefix = candidate.slice(0, -2).replace(/\/+$/, "");
      return target === prefix || target.startsWith(`${prefix}/`);
    }
    return target === (candidate.replace(/\/+$/, "") || "/");
  });
};

const parseManifest = (file: string, text: string): ClientManifest => {
  const doc = YAML.parse(text) as Record<string, unknown> | null;
  if (!doc || typeof doc !== "object") {
    throw new Error("manifest is empty or not a YAML mapping");
  }
  const agentId = typeof doc.agent_id === "string" ? doc.agent_id.trim() : "";
  if (!agentId) throw new Error("missing required field 'agent_id'");

  const fingerprint = normalizeFingerprint(doc.cert_fingerprint_sha256);
  if (!fingerprint) {
    throw new Error(
      "missing or malformed 'cert_fingerprint_sha256' (expected 64 hex characters)",
    );
  }

  return {
    agentId,
    displayName:
      typeof doc.display_name === "string" && doc.display_name.trim()
        ? doc.display_name.trim()
        : agentId,
    fingerprint,
    issuedBy: typeof doc.issued_by === "string" ? doc.issued_by.trim() : "",
    validFrom: asDate(doc.valid_from),
    validTo: asDate(doc.valid_to),
    allowedRoutes: asStringArray(doc.allowed_routes),
    // Anything other than an explicit `false` counts as revoked. A manifest
    // whose revoked field is missing or garbled must not grant access.
    revoked: doc.revoked !== false,
    notes: typeof doc.notes === "string" ? doc.notes : "",
    sourceFile: file,
  };
};

/** Cheap change-detection signature over the manifest directory. */
const directorySignature = (dir: string): string => {
  let names: string[];
  try {
    names = fs
      .readdirSync(dir)
      .filter((n) => n.endsWith(".yaml") || n.endsWith(".yml"));
  } catch {
    return "missing";
  }
  return names
    .sort()
    .map((name) => {
      try {
        const stat = fs.statSync(path.join(dir, name));
        return `${name}:${stat.mtimeMs}:${stat.size}`;
      } catch {
        return `${name}:gone`;
      }
    })
    .join("|");
};

/**
 * Reads and caches `<agentDir>/clients/*.yaml`.
 *
 * The cache is invalidated by file mtime/size rather than a timer, so an
 * operator's revocation is authoritative immediately instead of "within N
 * seconds" — the latency window of a TTL cache is exactly the window an
 * attacker with a just-revoked cert would want.
 */
export class AgentRegistry {
  private readonly clientsDir: string;
  private signature = "";
  private snapshot: RegistrySnapshot;
  private byFingerprint = new Map<string, ClientManifest>();

  constructor(agentDir: string) {
    this.clientsDir = path.join(agentDir, "clients");
    this.snapshot = { clients: [], problems: [], directory: this.clientsDir };
  }

  /** Absolute path of the directory this registry watches. */
  get directory(): string {
    return this.clientsDir;
  }

  /** Current registry contents, reloading from disk if anything changed. */
  load(): RegistrySnapshot {
    const signature = directorySignature(this.clientsDir);
    if (signature === this.signature) return this.snapshot;

    const clients: ClientManifest[] = [];
    const problems: ManifestProblem[] = [];
    let names: string[] = [];
    try {
      names = fs
        .readdirSync(this.clientsDir)
        .filter((n) => n.endsWith(".yaml") || n.endsWith(".yml"))
        .sort();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      problems.push({
        file: this.clientsDir,
        error: `directory unreadable: ${detail}`,
      });
    }

    for (const name of names) {
      const file = path.join(this.clientsDir, name);
      try {
        clients.push(parseManifest(file, fs.readFileSync(file, "utf8")));
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        problems.push({ file, error: detail });
        logger.error(`Ignoring unusable client manifest ${name}: ${detail}`);
      }
    }

    const byFingerprint = new Map<string, ClientManifest>();
    // A fingerprint that was ever claimed twice stays disabled for the rest of
    // the pass. Deleting the map entry alone is not enough: with three or more
    // manifests, the third sees no existing entry and would be inserted,
    // re-authorising the very certificate the duplicate check exists to refuse.
    const contested = new Set<string>();
    for (const client of clients) {
      if (contested.has(client.fingerprint)) {
        problems.push({
          file: client.sourceFile,
          error:
            "duplicate fingerprint already claimed by another manifest; entry disabled",
        });
        continue;
      }
      const existing = byFingerprint.get(client.fingerprint);
      if (existing) {
        // Two manifests claiming one certificate makes authorisation
        // ambiguous. Refuse both rather than pick a winner by filename.
        problems.push({
          file: client.sourceFile,
          error: `duplicate fingerprint also claimed by ${path.basename(existing.sourceFile)}; both entries disabled`,
        });
        byFingerprint.delete(client.fingerprint);
        contested.add(client.fingerprint);
        continue;
      }
      byFingerprint.set(client.fingerprint, client);
    }

    this.signature = signature;
    this.byFingerprint = byFingerprint;
    this.snapshot = { clients, problems, directory: this.clientsDir };
    logger.debug(
      `Agent registry loaded: ${clients.length} manifest(s), ${problems.length} problem(s)`,
    );
    return this.snapshot;
  }

  /**
   * Authorise a verified peer certificate against a concrete request path.
   *
   * The TLS layer has already proven the certificate chains to our CA by the
   * time this runs; everything here is the second gate — is this specific
   * certificate still one we recognise, still live, and allowed on this route.
   *
   * @param fingerprint - `cert.fingerprint256` from the TLS socket.
   * @param routePath - Request path without query string.
   * @param now - Evaluation instant, injectable for tests.
   * @returns An allow decision with the manifest, or a deny with reason and HTTP status.
   */
  authorize(
    fingerprint: string | undefined,
    routePath: string,
    now: Date = new Date(),
  ): AuthorizationResult {
    this.load();

    const normalized = normalizeFingerprint(fingerprint);
    if (!normalized) {
      return { allowed: false, reason: "no_client_certificate", status: 401 };
    }

    const client = this.byFingerprint.get(normalized);
    if (!client) {
      return { allowed: false, reason: "unknown_fingerprint", status: 403 };
    }

    // Revocation outranks every other check, including validity dates: an
    // operator saying "this key is compromised" must not be second-guessed.
    if (client.revoked) {
      return { allowed: false, reason: "revoked", status: 403, client };
    }
    if (client.validFrom && now < client.validFrom) {
      return { allowed: false, reason: "not_yet_valid", status: 403, client };
    }
    if (client.validTo && now > client.validTo) {
      return { allowed: false, reason: "expired", status: 403, client };
    }
    if (!routeAllowed(client.allowedRoutes, routePath)) {
      return {
        allowed: false,
        reason: "route_not_allowed",
        status: 403,
        client,
      };
    }
    return { allowed: true, client };
  }
}
