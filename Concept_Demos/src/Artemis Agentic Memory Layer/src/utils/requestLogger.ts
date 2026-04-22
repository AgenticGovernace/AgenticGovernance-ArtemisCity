import { NextFunction, Request, Response } from 'express';
import { logger } from './logger';

/**
 * Express middleware for logging incoming requests.
 * Logs the HTTP method, original URL, and IP address of the requester at INFO level.
 * @param req The Express request object.
 * @param res The Express response object.
 * @param next The next middleware function.
 */
const requestLogger = (req: Request, res: Response, next: NextFunction) => {
  logger.info(`${requestLogger} ${req.originalUrl} from ${req.ip}`);
  next();
};
export default requestLogger;
