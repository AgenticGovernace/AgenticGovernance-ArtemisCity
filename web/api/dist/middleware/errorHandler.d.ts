/**
 * Error Handler Middleware
 *
 * Centralized error handling for the API.
 */
import { Request, Response, NextFunction } from 'express';
/**
 * Custom API Error class
 */
export declare class APIError extends Error {
    statusCode: number;
    code: string;
    details?: any;
    constructor(message: string, statusCode?: number, code?: string, details?: any);
}
/**
 * Predefined error types
 */
export declare const Errors: {
    NotFound: (resource: string) => APIError;
    BadRequest: (message: string, details?: any) => APIError;
    Unauthorized: (message?: string) => APIError;
    Forbidden: (message?: string) => APIError;
    Conflict: (message: string) => APIError;
    ValidationError: (errors: any[]) => APIError;
    RateLimited: () => APIError;
    InternalError: (message?: string) => APIError;
};
/**
 * Main error handler middleware
 */
export declare const errorHandler: (err: Error | APIError, req: Request, res: Response, next: NextFunction) => void;
/**
 * Not found handler for unmatched routes
 */
export declare const notFoundHandler: (req: Request, res: Response) => void;
/**
 * Async handler wrapper to catch async errors
 */
export declare const asyncHandler: (fn: (req: Request, res: Response, next: NextFunction) => Promise<any>) => (req: Request, res: Response, next: NextFunction) => void;
export default errorHandler;
//# sourceMappingURL=errorHandler.d.ts.map