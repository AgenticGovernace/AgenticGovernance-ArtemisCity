/**
 * Logger Middleware
 *
 * Request/response logging for the API.
 */
import { Request, Response, NextFunction } from 'express';
/**
 * Log levels
 */
type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
/**
 * Log entry interface
 */
interface LogEntry {
    timestamp: string;
    level: LogLevel;
    method: string;
    path: string;
    statusCode?: number;
    duration?: number;
    ip?: string;
    userAgent?: string;
    userId?: string;
    requestId?: string;
    message?: string;
    error?: string;
}
/**
 * Request logger middleware
 */
export declare const requestLogger: (req: Request, res: Response, next: NextFunction) => void;
/**
 * Get recent logs
 */
export declare const getRecentLogs: (count?: number) => LogEntry[];
/**
 * Get logs by level
 */
export declare const getLogsByLevel: (level: LogLevel) => LogEntry[];
/**
 * Get logs by path pattern
 */
export declare const getLogsByPath: (pathPattern: string) => LogEntry[];
/**
 * Clear logs
 */
export declare const clearLogs: () => void;
/**
 * Manual log function
 */
export declare const log: (level: LogLevel, message: string, context?: Partial<LogEntry>) => void;
export default requestLogger;
//# sourceMappingURL=logger.d.ts.map