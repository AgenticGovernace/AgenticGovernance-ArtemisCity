/**
 * Entry point for the Artemis memory server.
 *
 * Two listening modes:
 *
 *   - **Mutual TLS** (`ARTEMIS_MTLS_ENABLED=1`): binds an HTTPS listener that
 *     demands a client certificate signed by the local Artemis CA. Identity is
 *     established at the socket, pinned by fingerprint against the vault's
 *     `.agent/clients/*.yaml` registry, and every decision is appended to the
 *     handshake ledger.
 *   - **Plaintext** (default): the historical HTTP listener with Bearer-token
 *     auth only. Kept for compatibility, and it says so loudly at boot.
 *
 * @module index
 */

import "dotenv/config";
import express from "express";
import cors from "cors";
import http from "http";
import https from "https";
import { PORT } from "./config";
import { loadTlsConfig, TlsConfigError } from "./config/tls";
import { createMcpRouter } from "./mcp-server";
import { createMtlsMiddleware } from "./mcp-server/middleware/mtls";
import { AgentRegistry } from "./security/agentRegistry";
import { HandshakeLog } from "./security/handshakeLog";
import { logger } from "./utils/logger";
import requestLogger from "./utils/requestLogger";

const app = express();

app.use(cors());
app.use(express.json());
app.use(requestLogger);

let tls;
try {
  tls = loadTlsConfig();
} catch (error) {
  if (error instanceof TlsConfigError) {
    // Fail closed. A server asked to run mTLS that cannot must not fall back
    // to plaintext — that is the single failure mode this feature exists to
    // prevent, and a silent downgrade would be worse than never enabling it.
    logger.error(`Refusing to start: ${error.message}`);
    process.exit(1);
  }
  throw error;
}

const handshakeLog = new HandshakeLog(tls.agentDir);

if (tls.enabled) {
  const registry = new AgentRegistry(tls.agentDir);
  const snapshot = registry.load();

  if (snapshot.problems.length > 0) {
    for (const problem of snapshot.problems) {
      logger.error(
        `Client manifest problem — ${problem.file}: ${problem.error}`,
      );
    }
  }
  if (snapshot.clients.length === 0) {
    // Not fatal: an empty registry is a valid "deny everyone" posture, and it
    // is also what a fresh install looks like. Say which directory is empty so
    // the fix is obvious.
    logger.warn(
      `No client manifests in ${registry.directory} — every request will be denied. ` +
        `Issue one with: scripts/mtls/artemis-mtls.sh issue-client <agent-id>`,
    );
  }

  app.use(
    "/api",
    createMtlsMiddleware({
      registry,
      handshakeLog,
      serverCommonName: "localhost",
    }),
  );
}

app.use("/api", createMcpRouter({ requireBearer: tls.requireBearer }));

app.get("/health", (_req, res) => {
  res.status(200).json({
    status: "ok",
    mtls: tls.enabled,
    agent_dir: tls.agentDir,
  });
});

const onListening = (scheme: string) => () => {
  logger.info(`MCP Server running on port ${PORT}`);
  logger.info(`Access at ${scheme}://${tls.host}:${PORT}`);
  if (tls.enabled) {
    logger.info(
      `Mutual TLS enforced (min ${tls.minVersion}); registry ${tls.agentDir}/clients`,
    );
    logger.info(
      `Bearer token ${tls.requireBearer ? "also required" : "NOT required — certificate is the sole factor"}`,
    );
  } else {
    logger.warn(
      "Mutual TLS is DISABLED — this listener is plaintext HTTP authenticated by a shared " +
        "bearer token, which any local process able to read .env can replay. " +
        "Enable it with ARTEMIS_MTLS_ENABLED=1 (see scripts/mtls/artemis-mtls.sh).",
    );
  }
};

const server = tls.enabled
  ? https.createServer(
      {
        cert: tls.cert,
        key: tls.key,
        ca: tls.ca,
        // Ask for a client certificate and refuse the connection outright when
        // it is absent or does not chain to our CA. This runs before Express.
        requestCert: true,
        rejectUnauthorized: true,
        minVersion: tls.minVersion,
      },
      app,
    )
  : http.createServer(app);

server.listen(PORT, tls.host, onListening(tls.enabled ? "https" : "http"));

const shutdown = (signal: string) => {
  logger.info(`Received ${signal}; draining handshake ledger and closing.`);
  server.close(() => {
    void handshakeLog.drain().then(() => process.exit(0));
  });
};

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

export { app, server };
