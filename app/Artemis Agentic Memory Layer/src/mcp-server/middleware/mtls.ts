/**
 * Mutual-TLS identity enforcement for the memory server.
 *
 * By the time this middleware runs, Node's TLS layer has already refused any
 * client whose certificate does not chain to our CA — `rejectUnauthorized`
 * kills those connections before a single HTTP byte is parsed. What remains is
 * the second gate, and it is the one that carries the operational weight:
 *
 *   1. Is this specific certificate one we still recognise? (fingerprint pin)
 *   2. Has it been revoked or has it expired?
 *   3. Is this agent allowed on *this* route?
 *
 * Every decision, allow or deny, is appended to the vault handshake ledger.
 *
 * @module mcp-server/middleware/mtls
 */

import { NextFunction, Request, Response } from "express";
import type { TLSSocket, PeerCertificate } from "tls";
import { logger } from "../../utils/logger";
import type {
  AgentRegistry,
  ClientManifest,
} from "../../security/agentRegistry";
import { normalizeFingerprint } from "../../security/agentRegistry";
import type { HandshakeLog } from "../../security/handshakeLog";

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      /** Manifest of the agent whose certificate authorised this request. */
      artemisClient?: ClientManifest;
    }
  }
}

export interface MtlsMiddlewareOptions {
  registry: AgentRegistry;
  handshakeLog: HandshakeLog;
  /** Server common name recorded in the ledger. Defaults to 'localhost'. */
  serverCommonName?: string;
}

/** Narrow an Express socket to a TLS socket when the listener terminates TLS. */
const asTlsSocket = (req: Request): TLSSocket | null => {
  const socket = req.socket as Partial<TLSSocket> | undefined;
  return socket && typeof socket.getPeerCertificate === "function"
    ? (socket as TLSSocket)
    : null;
};

const peerCertificate = (socket: TLSSocket): PeerCertificate | null => {
  const cert = socket.getPeerCertificate(false);
  // Node returns `{}` rather than null when the peer sent no certificate.
  if (!cert || Object.keys(cert).length === 0) return null;
  return cert;
};

const requestRoute = (req: Request): string =>
  (req.originalUrl || req.url || "/").split("?")[0] || "/";

/**
 * Build the mTLS enforcement middleware.
 *
 * @param options - Registry and ledger the middleware should consult and write.
 * @returns Express middleware that authorises by client certificate.
 */
export const createMtlsMiddleware = ({
  registry,
  handshakeLog,
  serverCommonName = "localhost",
}: MtlsMiddlewareOptions) => {
  return function enforceMtls(
    req: Request,
    res: Response,
    next: NextFunction,
  ): void {
    const route = requestRoute(req);
    const remote = req.ip ?? req.socket?.remoteAddress ?? "";
    const socket = asTlsSocket(req);

    const record = (
      result: "accepted" | "rejected",
      fingerprint: string,
      clientCn: string,
      agentId: string,
      reason?: string,
    ) => {
      void handshakeLog.append({
        ts: new Date().toISOString(),
        server_cn: serverCommonName,
        client_cn: clientCn,
        agent_id: agentId,
        client_fingerprint_sha256: fingerprint,
        result,
        method: req.method,
        route,
        remote,
        reason,
      });
    };

    // A plaintext connection reaching a middleware that exists to enforce
    // certificate identity means the listener was misconfigured. Refuse
    // rather than wave the request through.
    if (!socket) {
      logger.error(
        "mTLS middleware saw a non-TLS socket — the listener is not terminating TLS.",
      );
      record("rejected", "", "", "", "no_client_certificate");
      res.status(401).json({
        success: false,
        error: "Unauthorized: client certificate required.",
      });
      return;
    }

    if (!socket.authorized) {
      const why = socket.authorizationError
        ? String(socket.authorizationError)
        : "unverified";
      logger.warn(`Rejected unauthorized TLS peer on ${route}: ${why}`);
      record("rejected", "", "", "", `tls_unauthorized:${why}`);
      res.status(401).json({
        success: false,
        error: "Unauthorized: client certificate was not verified.",
      });
      return;
    }

    const cert = peerCertificate(socket);
    const fingerprint = normalizeFingerprint(cert?.fingerprint256);
    const clientCn = cert?.subject?.CN ? String(cert.subject.CN) : "";

    const decision = registry.authorize(fingerprint, route);

    if (!decision.allowed) {
      const agentId = decision.client?.agentId ?? "";
      logger.warn(
        `Denied ${clientCn || "unidentified client"} on ${route}: ${decision.reason}`,
      );
      record("rejected", fingerprint, clientCn, agentId, decision.reason);
      res.status(decision.status).json({
        success: false,
        error:
          decision.status === 401
            ? "Unauthorized: client certificate required."
            : "Forbidden: client certificate is not authorized for this route.",
        reason: decision.reason,
      });
      return;
    }

    req.artemisClient = decision.client;
    logger.debug(
      `Authorized ${decision.client.agentId} (${clientCn}) on ${route}`,
    );
    record("accepted", fingerprint, clientCn, decision.client.agentId);
    next();
  };
};

export default createMtlsMiddleware;
