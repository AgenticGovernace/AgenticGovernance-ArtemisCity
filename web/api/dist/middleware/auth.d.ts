/**
 * Authentication Middleware
 *
 * Handles API authentication and authorization.
 */
import { Request, Response, NextFunction } from 'express';
interface AuthenticatedRequest extends Request {
    user?: {
        id: string;
        role: string;
        permissions: string[];
    };
    apiKey?: string;
}
/**
 * Main authentication middleware
 */
export declare const authMiddleware: (req: AuthenticatedRequest, res: Response, next: NextFunction) => void;
/**
 * Permission check middleware factory
 */
export declare const requirePermission: (permission: string) => (req: AuthenticatedRequest, res: Response, next: NextFunction) => void;
/**
 * Role check middleware factory
 */
export declare const requireRole: (...roles: string[]) => (req: AuthenticatedRequest, res: Response, next: NextFunction) => void;
/**
 * Rate limiting middleware
 */
export declare const rateLimit: (options?: {
    windowMs?: number;
    maxRequests?: number;
}) => (req: AuthenticatedRequest, res: Response, next: NextFunction) => void;
export default authMiddleware;
//# sourceMappingURL=auth.d.ts.map