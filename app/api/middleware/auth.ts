/**
 * Authentication Middleware
 *
 * Handles API authentication and authorization.
 */

import { Request, Response, NextFunction } from 'express';
import { sanitizeForLog } from './logger';

interface AuthenticatedRequest extends Request {
  user?: {
    id: string;
    role: string;
    permissions: string[];
  };
  apiKey?: string;
}

interface ApiKeyEntry {
  userId: string;
  role: string;
  permissions: string[];
}

/**
 * Load API keys from environment variables.
 *
 * Expected format per key env var:
 *   ARTEMIS_API_KEY_<NAME>=<key>:<role>:<perm1,perm2,...>
 *
 * Example:
 *   ARTEMIS_API_KEY_ADMIN=my-secret-key:admin:read,write,delete,admin
 *
 * Falls back to MCP_API_KEY with admin role if no ARTEMIS_API_KEY_* vars are set.
 *
 * @returns Mapping of API key strings to the associated user and permission metadata.
 */
function loadApiKeys(): Record<string, ApiKeyEntry> {
  const keys: Record<string, ApiKeyEntry> = {};

  for (const [envName, envValue] of Object.entries(process.env)) {
    if (!envName.startsWith('ARTEMIS_API_KEY_') || !envValue) continue;

    const userId = envName.replace('ARTEMIS_API_KEY_', '').toLowerCase();
    const parts = envValue.split(':');
    if (parts.length < 3) {
      console.warn(`[AUTH] Malformed key env var ${sanitizeForLog(envName)}: expected key:role:permissions`);
      continue;
    }

    const [apiKey, role, permsRaw] = parts;
    keys[apiKey] = {
      userId,
      role,
      permissions: permsRaw.split(',').map(p => p.trim()),
    };
  }

  if (Object.keys(keys).length === 0) {
    const fallbackKey = process.env.MCP_API_KEY;
    if (fallbackKey) {
      keys[fallbackKey] = {
        userId: 'default',
        role: 'admin',
        permissions: ['read', 'write', 'delete', 'admin'],
      };
    } else {
      console.error('[AUTH] No API keys configured. Set ARTEMIS_API_KEY_* or MCP_API_KEY env vars.');
    }
  }

  return keys;
}

const API_KEYS = loadApiKeys();

/**
 * Authenticate an API request with a bearer token or X-API-Key header.
 *
 * @param req - Express request object for the current HTTP call.
 * @param res - Express response object used to send the HTTP response.
 * @param next - Express callback that passes control to the next middleware.
 * @returns Nothing. The middleware completes its work through side effects on the request/response cycle.
 */
export const authMiddleware = (req: AuthenticatedRequest, res: Response, next: NextFunction): void => {
  if (process.env.NODE_ENV === 'development' && process.env.SKIP_AUTH === 'true') {
    console.warn('[AUTH] WARNING: Auth bypass active (SKIP_AUTH=true). Do NOT use in production.');
    req.user = {
      id: 'dev-user',
      role: 'admin',
      permissions: ['read', 'write', 'delete', 'admin']
    };
    next();
    return;
  }

  if (process.env.SKIP_AUTH === 'true' && process.env.NODE_ENV !== 'development') {
    console.error('[AUTH] SKIP_AUTH ignored: NODE_ENV is not "development".');
  }

  const authHeader = req.headers.authorization;
  const apiKey = req.headers['x-api-key'] as string;

  let key: string | undefined;

  if (authHeader?.startsWith('Bearer ')) {
    key = authHeader.substring(7);
  } else if (apiKey) {
    key = apiKey;
  }

  if (!key) {
    res.status(401).json({
      success: false,
      error: 'Authentication required',
      message: 'Please provide an API key via Authorization header (Bearer token) or X-API-Key header'
    });
    return;
  }

  const keyData = API_KEYS[key];
  if (!keyData) {
    res.status(401).json({
      success: false,
      error: 'Invalid API key',
      message: 'The provided API key is not valid'
    });
    return;
  }

  req.user = {
    id: keyData.userId,
    role: keyData.role,
    permissions: keyData.permissions
  };
  req.apiKey = key;

  next();
};

/**
 * Create middleware that requires a specific permission.
 *
 * @param permission - Permission that the generated middleware should require.
 * @returns Express middleware that rejects callers missing the requested permission.
 */
export const requirePermission = (permission: string) => {
  return (req: AuthenticatedRequest, res: Response, next: NextFunction): void => {
    if (!req.user) {
      res.status(401).json({
        success: false,
        error: 'Authentication required'
      });
      return;
    }

    if (!req.user.permissions.includes(permission) && !req.user.permissions.includes('admin')) {
      res.status(403).json({
        success: false,
        error: 'Permission denied',
        message: `This action requires '${permission}' permission`
      });
      return;
    }

    next();
  };
};

/**
 * Create middleware that requires one of the supplied roles.
 *
 * @param roles - Allowed roles for the generated middleware.
 * @returns Express middleware that rejects callers outside the allowed role set.
 */
export const requireRole = (...roles: string[]) => {
  return (req: AuthenticatedRequest, res: Response, next: NextFunction): void => {
    if (!req.user) {
      res.status(401).json({
        success: false,
        error: 'Authentication required'
      });
      return;
    }

    if (!roles.includes(req.user.role)) {
      res.status(403).json({
        success: false,
        error: 'Role not authorized',
        message: `This action requires one of these roles: ${roles.join(', ')}`
      });
      return;
    }

    next();
  };
};

/**
 * Rate limiting state.
 */
const rateLimitStore: Map<string, { count: number; resetTime: number }> = new Map();

/**
 * Create request-rate-limiting middleware.
 *
 * @param options - Optional rate-limit settings such as window size and request budget.
 * @returns Express middleware that enforces the configured request budget.
 */
export const rateLimit = (options: { windowMs?: number; maxRequests?: number } = {}) => {
  const windowMs = options.windowMs || 60000;
  const maxRequests = options.maxRequests || 100;

  return (req: AuthenticatedRequest, res: Response, next: NextFunction): void => {
    const key = req.apiKey || req.ip || 'anonymous';
    const now = Date.now();

    let record = rateLimitStore.get(key);

    if (!record || now > record.resetTime) {
      record = { count: 0, resetTime: now + windowMs };
    }

    record.count++;
    rateLimitStore.set(key, record);

    res.setHeader('X-RateLimit-Limit', maxRequests.toString());
    res.setHeader('X-RateLimit-Remaining', Math.max(0, maxRequests - record.count).toString());
    res.setHeader('X-RateLimit-Reset', record.resetTime.toString());

    if (record.count > maxRequests) {
      res.status(429).json({
        success: false,
        error: 'Rate limit exceeded',
        message: `Too many requests. Please try again after ${Math.ceil((record.resetTime - now) / 1000)} seconds`
      });
      return;
    }

    next();
  };
};

export default authMiddleware;
