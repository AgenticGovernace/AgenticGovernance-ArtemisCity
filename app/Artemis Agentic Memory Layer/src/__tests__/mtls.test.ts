/**
 * End-to-end proof that mutual TLS actually gates the memory server.
 *
 * These tests do not mock TLS. They run `scripts/mtls/artemis-mtls.sh` to mint
 * a real CA and real client certificates, boot the real `src/index.ts`
 * listener, and then drive it over genuine HTTPS handshakes. A test that stubs
 * the socket would pass just as happily against a server that never checked a
 * certificate at all, which is exactly the bug this feature exists to prevent.
 *
 * Run with: npm test  (from app/Artemis Agentic Memory Layer)
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import https from "node:https";
import os from "node:os";
import path from "node:path";
import YAML from "yaml";

import {
  AgentRegistry,
  normalizeFingerprint,
  routeAllowed,
} from "../security/agentRegistry";
import { loadTlsConfig, TlsConfigError } from "../config/tls";
import { HandshakeLog, ledgerFileName } from "../security/handshakeLog";

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const MTLS_SCRIPT = path.join(REPO_ROOT, "scripts", "mtls", "artemis-mtls.sh");
const TEST_TOKEN = "test-bearer-token-not-a-real-secret"; // pragma: allowlist secret

let sandbox: string;
let mtlsDir: string;
let agentDir: string;
let baseUrl: string;
let server: import("http").Server;

/** Run the CA script against the sandbox rather than the operator's real CA. */
const mtls = (...args: string[]): string =>
  execFileSync("bash", [MTLS_SCRIPT, ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      ARTEMIS_MTLS_DIR: mtlsDir,
      ARTEMIS_AGENT_DIR: agentDir,
    },
  });

const clientMaterial = (agentId: string) => ({
  cert: fs.readFileSync(path.join(mtlsDir, "clients", `${agentId}.crt`)),
  key: fs.readFileSync(path.join(mtlsDir, "clients", `${agentId}.key`)),
});

interface Reply {
  status: number;
  body: Record<string, unknown>;
}

/**
 * Make one HTTPS request, optionally presenting a client certificate.
 *
 * Rejects when the TLS handshake itself fails, which is the expected outcome
 * for an absent or untrusted certificate — those never reach Express.
 */
const call = (options: {
  route: string;
  agentId?: string;
  identity?: { cert: Buffer; key: Buffer };
  token?: string | null;
  method?: string;
}): Promise<Reply> => {
  const identity =
    options.identity ??
    (options.agentId ? clientMaterial(options.agentId) : undefined);

  const headers: Record<string, string> = {};
  const token = options.token === undefined ? TEST_TOKEN : options.token;
  if (token !== null) headers.Authorization = `Bearer ${token}`;

  return new Promise((resolve, reject) => {
    const req = https.request(
      `${baseUrl}${options.route}`,
      {
        method: options.method ?? "GET",
        ca: fs.readFileSync(path.join(mtlsDir, "ca.crt")),
        cert: identity?.cert,
        key: identity?.key,
        headers,
        // The server certificate is issued for CN=localhost with a 127.0.0.1
        // SAN, so ordinary hostname verification applies. Nothing is disabled.
        servername: "localhost",
      },
      (res) => {
        let raw = "";
        res.on("data", (chunk) => (raw += chunk));
        res.on("end", () => {
          let body: Record<string, unknown> = {};
          try {
            body = JSON.parse(raw) as Record<string, unknown>;
          } catch {
            body = { _raw: raw };
          }
          resolve({ status: res.statusCode ?? 0, body });
        });
      },
    );
    req.on("error", reject);
    req.end();
  });
};

const readLedger = (): Array<Record<string, string>> => {
  const file = path.join(agentDir, "logs", ledgerFileName(new Date()));
  if (!fs.existsSync(file)) return [];
  const parsed = YAML.parse(fs.readFileSync(file, "utf8"));
  return Array.isArray(parsed) ? parsed : [];
};

before(async () => {
  sandbox = fs.mkdtempSync(path.join(os.tmpdir(), "artemis-mtls-"));
  mtlsDir = path.join(sandbox, "ca");
  agentDir = path.join(sandbox, ".agent");

  // Short-lived certificates keep the test's blast radius small.
  process.env.ARTEMIS_MTLS_LEAF_DAYS = "2";
  mtls("init-ca");
  mtls("issue-server");
  mtls(
    "issue-client",
    "trusted-agent",
    "--routes",
    "/api/whoami,/api/listNotes",
  );
  mtls("issue-client", "narrow-agent", "--routes", "/api/listNotes");
  mtls("issue-client", "revoked-agent", "--routes", "*");
  mtls("revoke", "revoked-agent");

  // A certificate from a CA the server has never heard of.
  const rogueDir = path.join(sandbox, "rogue");
  execFileSync("bash", [MTLS_SCRIPT, "init-ca"], {
    env: {
      ...process.env,
      ARTEMIS_MTLS_DIR: rogueDir,
      ARTEMIS_AGENT_DIR: agentDir,
    },
    stdio: "ignore",
  });
  execFileSync("bash", [MTLS_SCRIPT, "issue-client", "impostor"], {
    env: {
      ...process.env,
      ARTEMIS_MTLS_DIR: rogueDir,
      ARTEMIS_AGENT_DIR: path.join(sandbox, "rogue-agent-dir"),
    },
    stdio: "ignore",
  });

  Object.assign(process.env, {
    PORT: "0",
    MCP_API_KEY: TEST_TOKEN,
    OBSIDIAN_BASE_URL: "http://127.0.0.1:1",
    OBSIDIAN_API_KEY: "unused-in-these-tests", // pragma: allowlist secret
    MCP_LOG_LEVEL: "error",
    ARTEMIS_MTLS_ENABLED: "1",
    ARTEMIS_MTLS_HOST: "127.0.0.1",
    ARTEMIS_MTLS_CERT: path.join(mtlsDir, "mcp-server.crt"),
    ARTEMIS_MTLS_KEY: path.join(mtlsDir, "mcp-server.key"),
    ARTEMIS_MTLS_CA: path.join(mtlsDir, "ca.crt"),
    ARTEMIS_AGENT_DIR: agentDir,
  });

  const entry = (await import("../index")) as {
    server: import("http").Server;
  };
  server = entry.server;
  await new Promise<void>((resolve) => {
    if (server.listening) return resolve();
    server.once("listening", () => resolve());
  });
  const address = server.address();
  assert.ok(
    address && typeof address === "object",
    "server did not bind a port",
  );
  baseUrl = `https://localhost:${address.port}`;

  // Store the impostor material where clientMaterial() can find it.
  fs.copyFileSync(
    path.join(rogueDir, "clients", "impostor.crt"),
    path.join(mtlsDir, "clients", "impostor.crt"),
  );
  fs.copyFileSync(
    path.join(rogueDir, "clients", "impostor.key"),
    path.join(mtlsDir, "clients", "impostor.key"),
  );
});

after(() => {
  server?.close();
  if (sandbox) fs.rmSync(sandbox, { recursive: true, force: true });
});

describe("fingerprint normalisation", () => {
  const canonical =
    "13:06:A9:8B:38:E3:08:E7:0C:DD:9C:CE:4A:EF:69:97:6D:BB:7D:7B:09:CD:23:2E:3E:FA:17:78:27:3B:67:59";

  it("accepts Node's fingerprint256 shape unchanged", () => {
    assert.equal(normalizeFingerprint(canonical), canonical);
  });

  it("accepts openssl's prefixed, and bare lowercase, forms", () => {
    assert.equal(
      normalizeFingerprint(`SHA256 Fingerprint=${canonical}`),
      canonical,
    );
    assert.equal(
      normalizeFingerprint(canonical.replace(/:/g, "").toLowerCase()),
      canonical,
    );
  });

  it("rejects anything that is not exactly 32 bytes of hex", () => {
    assert.equal(normalizeFingerprint("AB:CD"), "");
    assert.equal(normalizeFingerprint(undefined), "");
    assert.equal(normalizeFingerprint(`${canonical}:AB`), "");
  });
});

describe("route allow-list semantics", () => {
  it("matches exactly by default", () => {
    assert.equal(routeAllowed(["/api/listNotes"], "/api/listNotes"), true);
    assert.equal(routeAllowed(["/api/listNotes"], "/api/listNotesX"), false);
    assert.equal(routeAllowed(["/api/listNotes"], "/api/deleteNote"), false);
  });

  it("treats '*' as every route and '/p/*' as a subtree", () => {
    assert.equal(routeAllowed(["*"], "/api/deleteNote"), true);
    assert.equal(routeAllowed(["/api/*"], "/api/deleteNote"), true);
    assert.equal(routeAllowed(["/api/*"], "/api"), true);
    assert.equal(routeAllowed(["/api/*"], "/apiary/deleteNote"), false);
  });

  it("denies when the list is empty", () => {
    assert.equal(routeAllowed([], "/api/listNotes"), false);
  });
});

describe("TLS configuration fails closed", () => {
  it("throws rather than downgrading when enabled without key material", () => {
    assert.throws(
      () => loadTlsConfig({ ARTEMIS_MTLS_ENABLED: "1" } as NodeJS.ProcessEnv),
      TlsConfigError,
    );
  });

  it("throws when a configured path does not exist", () => {
    assert.throws(
      () =>
        loadTlsConfig({
          ARTEMIS_MTLS_ENABLED: "1",
          ARTEMIS_MTLS_CERT: "/nonexistent/a.crt",
          ARTEMIS_MTLS_KEY: "/nonexistent/a.key",
          ARTEMIS_MTLS_CA: "/nonexistent/ca.crt",
        } as NodeJS.ProcessEnv),
      TlsConfigError,
    );
  });

  it("stays disabled, and does not throw, when the flag is off", () => {
    const config = loadTlsConfig({} as NodeJS.ProcessEnv);
    assert.equal(config.enabled, false);
    assert.equal(config.requireBearer, true);
  });
});

describe("registry manifest handling", () => {
  it("treats a manifest with a missing 'revoked' field as revoked", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "artemis-reg-"));
    fs.mkdirSync(path.join(dir, "clients"), { recursive: true });
    const fp = "A".repeat(64);
    fs.writeFileSync(
      path.join(dir, "clients", "sloppy.yaml"),
      `agent_id: sloppy\ncert_fingerprint_sha256: "${fp}"\nallowed_routes:\n  - "*"\n`,
    );
    const registry = new AgentRegistry(dir);
    const decision = registry.authorize(fp, "/api/whoami");
    assert.equal(decision.allowed, false);
    assert.equal(decision.allowed === false && decision.reason, "revoked");
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("disables both entries when two manifests claim one fingerprint", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "artemis-reg-"));
    fs.mkdirSync(path.join(dir, "clients"), { recursive: true });
    const fp = "B".repeat(64);
    for (const name of ["one", "two"]) {
      fs.writeFileSync(
        path.join(dir, "clients", `${name}.yaml`),
        `agent_id: ${name}\ncert_fingerprint_sha256: "${fp}"\nrevoked: false\nallowed_routes:\n  - "*"\n`,
      );
    }
    const registry = new AgentRegistry(dir);
    const decision = registry.authorize(fp, "/api/whoami");
    assert.equal(decision.allowed, false);
    assert.equal(
      decision.allowed === false && decision.reason,
      "unknown_fingerprint",
    );
    assert.equal(registry.load().problems.length, 1);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("keeps a duplicated fingerprint denied past the second claimant", () => {
    // Regression: deleting the map entry on the second claim let a THIRD
    // manifest re-insert the same fingerprint and be authorised.
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "artemis-reg-"));
    fs.mkdirSync(path.join(dir, "clients"), { recursive: true });
    const fp = normalizeFingerprint("AB".repeat(32));
    for (const name of ["one", "two", "three"]) {
      fs.writeFileSync(
        path.join(dir, "clients", `${name}.yaml`),
        `agent_id: ${name}\ncert_fingerprint_sha256: "${fp}"\nrevoked: false\nallowed_routes:\n  - "*"\n`,
      );
    }
    const registry = new AgentRegistry(dir);
    const decision = registry.authorize(fp, "/api/whoami");
    assert.equal(decision.allowed, false);
    assert.equal(
      decision.allowed === false && decision.reason,
      "unknown_fingerprint",
    );
    assert.equal(registry.load().problems.length, 2);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("denies an expired certificate even though it is not revoked", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "artemis-reg-"));
    fs.mkdirSync(path.join(dir, "clients"), { recursive: true });
    const fp = "C".repeat(64);
    fs.writeFileSync(
      path.join(dir, "clients", "stale.yaml"),
      `agent_id: stale\ncert_fingerprint_sha256: "${fp}"\nrevoked: false\n` +
        `valid_from: "2020-01-01T00:00:00Z"\nvalid_to: "2020-02-01T00:00:00Z"\n` +
        `allowed_routes:\n  - "*"\n`,
    );
    const registry = new AgentRegistry(dir);
    const decision = registry.authorize(fp, "/api/whoami");
    assert.equal(decision.allowed === false && decision.reason, "expired");
    fs.rmSync(dir, { recursive: true, force: true });
  });
});

describe("live server over real TLS", () => {
  it("accepts a registered agent on an allowed route and reports its identity", async () => {
    const reply = await call({
      route: "/api/whoami",
      agentId: "trusted-agent",
    });
    assert.equal(reply.status, 200);
    assert.equal(reply.body.mtls, true);
    assert.equal(reply.body.agent_id, "trusted-agent");
  });

  it("refuses a connection that presents no client certificate", async () => {
    await assert.rejects(
      () =>
        call({ route: "/api/whoami", identity: undefined, agentId: undefined }),
      (error: NodeJS.ErrnoException) => {
        // The handshake dies at the socket; the exact code varies by platform
        // and TLS version, so assert only that Express never answered.
        assert.ok(error instanceof Error, "expected a transport-level failure");
        return true;
      },
    );
  });

  it("refuses a certificate signed by an unknown CA", async () => {
    await assert.rejects(() =>
      call({ route: "/api/whoami", agentId: "impostor" }),
    );
  });

  it("denies a registered agent on a route outside its allow-list", async () => {
    const reply = await call({ route: "/api/whoami", agentId: "narrow-agent" });
    assert.equal(reply.status, 403);
    assert.equal(reply.body.reason, "route_not_allowed");
  });

  it("denies a revoked agent even with a valid, CA-signed certificate", async () => {
    const reply = await call({
      route: "/api/whoami",
      agentId: "revoked-agent",
    });
    assert.equal(reply.status, 403);
    assert.equal(reply.body.reason, "revoked");
  });

  it("still requires the bearer token as a second factor", async () => {
    const wrong = await call({
      route: "/api/whoami",
      agentId: "trusted-agent",
      token: "not-the-token",
    });
    assert.equal(wrong.status, 403);

    const absent = await call({
      route: "/api/whoami",
      agentId: "trusted-agent",
      token: null,
    });
    assert.equal(absent.status, 401);
  });

  it("honours a revocation written to disk without a restart", async () => {
    const before = await call({
      route: "/api/whoami",
      agentId: "trusted-agent",
    });
    assert.equal(before.status, 200);

    mtls("revoke", "trusted-agent");
    const after = await call({
      route: "/api/whoami",
      agentId: "trusted-agent",
    });
    assert.equal(after.status, 403);
    assert.equal(after.body.reason, "revoked");

    mtls("unrevoke", "trusted-agent");
    const restored = await call({
      route: "/api/whoami",
      agentId: "trusted-agent",
    });
    assert.equal(restored.status, 200);
  });
});

describe("handshake ledger", () => {
  it("records both accepted and rejected decisions as parseable YAML", async () => {
    await call({ route: "/api/whoami", agentId: "trusted-agent" });
    await call({ route: "/api/whoami", agentId: "revoked-agent" });
    await new HandshakeLog(agentDir).drain();
    // The live server owns its own queue; give it a turn to flush.
    await new Promise((resolve) => setTimeout(resolve, 150));

    const entries = readLedger();
    assert.ok(entries.length > 0, "ledger should not be empty");

    const accepted = entries.filter((e) => e.result === "accepted");
    const rejected = entries.filter((e) => e.result === "rejected");
    assert.ok(accepted.length > 0, "expected at least one accepted handshake");
    assert.ok(rejected.length > 0, "expected at least one rejected handshake");

    const revocation = rejected.find((e) => e.reason === "revoked");
    assert.ok(revocation, "revocation should be recorded with its reason");
    assert.equal(revocation.agent_id, "revoked-agent");
    assert.match(
      revocation.client_fingerprint_sha256,
      /^[0-9A-F]{2}(:[0-9A-F]{2}){31}$/,
    );
    assert.equal(revocation.route, "/api/whoami");

    const success = accepted.find((e) => e.agent_id === "trusted-agent");
    assert.ok(success, "accepted handshake should name the agent");
    assert.equal(success.client_cn, "trusted-agent");
  });

  it("escapes attacker-controlled route text instead of injecting YAML", async () => {
    const log = new HandshakeLog(path.join(sandbox, "inject"));
    await log.append({
      ts: new Date().toISOString(),
      server_cn: "localhost",
      client_cn: 'evil"\n- ts: "forged',
      agent_id: "x",
      client_fingerprint_sha256: "",
      result: "rejected",
      method: "GET",
      route: '/api/x"\nresult: "accepted',
      remote: "127.0.0.1",
      reason: "unknown_fingerprint",
    });
    await log.drain();

    const file = path.join(
      sandbox,
      "inject",
      "logs",
      ledgerFileName(new Date()),
    );
    const parsed = YAML.parse(fs.readFileSync(file, "utf8"));
    assert.equal(parsed.length, 1, "injection must not create a second record");
    assert.equal(parsed[0].result, "rejected");
  });
});
