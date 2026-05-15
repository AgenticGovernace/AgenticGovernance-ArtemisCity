import { NextFunction, Request, Response } from 'express';
import { logger } from './logger';

const requestLogger = (req: Request, _res: Response, next: NextFunction) => {
  logger.info(`${req.method} ${req.originalUrl} from ${req.ip}`);
  next();
};

export default requestLogger;
