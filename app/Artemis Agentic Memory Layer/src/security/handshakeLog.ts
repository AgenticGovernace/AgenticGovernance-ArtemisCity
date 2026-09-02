/**
 * Append-only handshake ledger for the memory server.
 *
 * Every authorisation decision — accepted or refused — is appended to
 * `<agentDir>/logs/handshakes-YYYY-MM.yaml` as a YAML sequence item. The files
 * are plain text so they can live in the vault under Git alongside the client
 * manifests, giving an auditable paper trail that survives the process.
 *
 * Writes are serialised through a single promise chain so concurrent requests
 * cannot interleave half-written records into the ledger.
 *
 * @module security/handshakeLog
 */

import fs from "fs";
import path from "path";
import YAML from "yaml";
import { logger } from "../utils/logger";
import type { DenyReason } from "./agentRegistry";

/** One entry in the ledger. Field names mirror the client-manifest vocabulary. */
export interface HandshakeRecord {
  ts: string;
  server_cn: string;
  client_cn: string;
  agent_id: string;
  client_fingerprint_sha256: string;
  result: "accepted" | "rejected";
  method: string;
  route: string;
  remote: string;
  reason?: DenyReason | string;
}

/** Values longer than this are truncated before they reach the ledger. */
const MAX_FIELD_LENGTH = 512;

/** Matches C0 control characters, which have no business in an audit line. */
const CONTROL_CHARS = /[\u0000-\u001F\u007F]/g;

/**
 * Render a value as a YAML double-quoted scalar.
 *
 * Request-derived fields (route, method, remote address) are attacker-
 * influenced, so they are escaped rather than interpolated. JSON string
 * escaping is a strict subset of YAML 1.2 double-quoted escaping, which makes
 * `JSON.stringify` a correct and boring encoder here.
 */
const quote = (value: unknown): string => {
  const text = value === undefined || value === null ? "" : String(value);
  const clipped =
    text.length > MAX_FIELD_LENGTH
      ? `${text.slice(0, MAX_FIELD_LENGTH)}...truncated`
      : text;
  return JSON.stringify(clipped.replace(CONTROL_CHARS, " "));
};

const serialize = (record: HandshakeRecord): string => {
  const lines = [
    `- ts: ${quote(record.ts)}`,
    `  server_cn: ${quote(record.server_cn)}`,
    `  client_cn: ${quote(record.client_cn)}`,
    `  agent_id: ${quote(record.agent_id)}`,
    `  client_fingerprint_sha256: ${quote(record.client_fingerprint_sha256)}`,
    `  result: ${quote(record.result)}`,
    `  method: ${quote(record.method)}`,
    `  route: ${quote(record.route)}`,
    `  remote: ${quote(record.remote)}`,
  ];
  if (record.reason) lines.push(`  reason: ${quote(record.reason)}`);
  return `${lines.join("\n")}\n`;
};

/** Monthly ledger filename for a given instant. */
export const ledgerFileName = (when: Date): string => {
  const stamp = Number.isNaN(when.getTime()) ? new Date() : when;
  const month = String(stamp.getUTCMonth() + 1).padStart(2, "0");
  return `handshakes-${stamp.getUTCFullYear()}-${month}.yaml`;
};

/**
 * Serialised, append-only writer over the monthly handshake ledgers.
 */
export class HandshakeLog {
  private readonly logsDir: string;
  private queue: Promise<void> = Promise.resolve();

  constructor(agentDir: string) {
    this.logsDir = path.join(agentDir, "logs");
  }

  /** Absolute path of the directory ledgers are written to. */
  get directory(): string {
    return this.logsDir;
  }

  /**
   * Append one decision to the current month's ledger.
   *
   * Never rejects: failing to write audit output is logged loudly but must not
   * take down the request path it is observing.
   *
   * @param record - The decision to record.
   * @returns A promise resolving once this record is on disk.
   */
  append(record: HandshakeRecord): Promise<void> {
    const file = path.join(this.logsDir, ledgerFileName(new Date(record.ts)));
    const payload = serialize(record);

    this.queue = this.queue
      .then(async () => {
        await fs.promises.mkdir(this.logsDir, { recursive: true });
        await fs.promises.appendFile(file, payload, "utf8");
      })
      .catch((error: unknown) => {
        const detail = error instanceof Error ? error.message : String(error);
        logger.error(`Failed to append handshake record to ${file}: ${detail}`);
      });

    return this.queue;
  }

  /** Flush pending appends. Used by tests and by graceful shutdown. */
  drain(): Promise<void> {
    return this.queue;
  }

  /**
   * Read back the most recent records, newest first.
   *
   * Reads only the current and previous month so the ledger can grow without
   * bounding this call's cost.
   *
   * @param limit - Maximum records to return.
   * @param now - Evaluation instant, injectable for tests.
   */
  async recent(
    limit = 100,
    now: Date = new Date(),
  ): Promise<HandshakeRecord[]> {
    const previous = new Date(
      Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1),
    );
    const files = [ledgerFileName(now), ledgerFileName(previous)];
    const records: HandshakeRecord[] = [];

    for (const name of files) {
      let text: string;
      try {
        text = await fs.promises.readFile(
          path.join(this.logsDir, name),
          "utf8",
        );
      } catch {
        continue;
      }
      try {
        const parsed = YAML.parse(text);
        if (Array.isArray(parsed)) {
          records.push(...(parsed.filter(Boolean) as HandshakeRecord[]));
        }
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        logger.error(
          `Handshake ledger ${name} is not parseable YAML: ${detail}`,
        );
      }
    }

    return records
      .sort((a, b) => String(b.ts).localeCompare(String(a.ts)))
      .slice(0, limit);
  }
}
