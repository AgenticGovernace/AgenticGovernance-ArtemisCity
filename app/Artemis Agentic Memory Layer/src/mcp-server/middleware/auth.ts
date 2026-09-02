import { Request, Response, NextFunction } from "express";
import { timingSafeEqual } from "crypto";
import { MCP_API_KEY } from "../../config";
import { logger } from "../../utils/logger";

/**
 * Compare two secrets without leaking their contents through timing.
 *
 * `timingSafeEqual` throws on length mismatch, which would itself be an
 * oracle, so both sides are hashed to a fixed width first by comparing
 * equal-length buffers padded to the longer input.
 *
 * @param a - Candidate value supplied by the caller.
 * @param b - Expected value from configuration.
 * @returns True when the values are byte-identical.
 */
const constantTimeEquals = (a: string, b: string): boolean => {
  const left = Buffer.from(a, "utf8");
  const right = Buffer.from(b, "utf8");
  const width = Math.max(left.length, right.length);
  const paddedLeft = Buffer.alloc(width);
  const paddedRight = Buffer.alloc(width);
  left.copy(paddedLeft);
  right.copy(paddedRight);
  // Length still has to be part of the verdict, but it is folded in after the
  // constant-time comparison so the comparison itself never short-circuits.
  return (
    timingSafeEqual(paddedLeft, paddedRight) && left.length === right.length
  );
};

/**
 * Middleware to authenticate requests using a Bearer token.
 *
 * When mutual TLS is enabled this is the *second* factor: the certificate
 * establishes identity at the socket, and this token carries scope and gives
 * operators a cheap rotation lever that does not require reissuing a cert.
 * When mTLS is disabled it is the only factor, which is why the server logs a
 * warning at boot in that mode.
 *
 * @param req The Express request object.
 * @param res The Express response object.
 * @param next The next middleware function in the stack.
 * @returns void
 */
const authenticateMCP = (
  req: Request,
  res: Response,
  next: NextFunction,
): void => {
  const authHeader = req.headers.authorization;

  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    logger.warn("Authentication failed: Missing or malformed Bearer token.");
    res
      .status(401)
      .json({ success: false, error: "Unauthorized: Bearer token required." });
    return;
  }

  const token = authHeader.split(" ")[1].trim();

  // Ensure MCP_API_KEY is not empty, though config validation should prevent this.
  if (!MCP_API_KEY) {
    logger.error("Server configuration error: MCP_API_KEY is not set.");
    res
      .status(500)
      .json({ success: false, error: "Server configuration error." });
    return;
  }

  if (constantTimeEquals(token, MCP_API_KEY)) {
    logger.debug("Authentication successful for incoming request.");
    next();
    return;
  }

  logger.warn("Authentication failed: Invalid MCP_API_KEY provided.");
  res
    .status(403)
    .json({ success: false, error: "Forbidden: Invalid API Key." });
};

export default authenticateMCP;
