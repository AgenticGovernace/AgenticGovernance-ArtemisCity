/**
 * Request logger middleware.
 *
 * Emits a concise log entry for each inbound HTTP request before passing control to the next middleware.
 */
import { NextFunction, Request, Response } from "express";
import { logger } from "./logger";
/**
 * Log the request method, URL, and remote IP for incoming HTTP traffic.
 *
 * @param req - Express request object for the incoming HTTP call.
 * @param _res - Express response object, unused by this middleware.
 * @param next - Callback that advances request handling to the next middleware.
 */

const requestLogger = (req: Request, _res: Response, next: NextFunction) => {
  logger.info(`${req.method} ${req.originalUrl} from ${req.ip}`);
  next();
};

export default requestLogger;
