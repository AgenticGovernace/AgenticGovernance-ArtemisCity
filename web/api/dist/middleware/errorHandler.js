"use strict";
/**
 * Error Handler Middleware
 *
 * Centralized error handling for the API.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.asyncHandler = exports.notFoundHandler = exports.errorHandler = exports.Errors = exports.APIError = void 0;
/**
 * Custom API Error class
 */
class APIError extends Error {
    constructor(message, statusCode = 500, code = 'INTERNAL_ERROR', details) {
        super(message);
        this.name = 'APIError';
        this.statusCode = statusCode;
        this.code = code;
        this.details = details;
    }
}
exports.APIError = APIError;
/**
 * Predefined error types
 */
exports.Errors = {
    NotFound: (resource) => new APIError(`${resource} not found`, 404, 'NOT_FOUND'),
    BadRequest: (message, details) => new APIError(message, 400, 'BAD_REQUEST', details),
    Unauthorized: (message = 'Authentication required') => new APIError(message, 401, 'UNAUTHORIZED'),
    Forbidden: (message = 'Permission denied') => new APIError(message, 403, 'FORBIDDEN'),
    Conflict: (message) => new APIError(message, 409, 'CONFLICT'),
    ValidationError: (errors) => new APIError('Validation failed', 400, 'VALIDATION_ERROR', { errors }),
    RateLimited: () => new APIError('Too many requests', 429, 'RATE_LIMITED'),
    InternalError: (message = 'Internal server error') => new APIError(message, 500, 'INTERNAL_ERROR')
};
/**
 * Main error handler middleware
 */
const errorHandler = (err, req, res, next) => {
    // Log error
    console.error(`[ERROR] ${new Date().toISOString()} - ${req.method} ${req.path}`);
    console.error(err.stack || err.message);
    // Determine status code and error details
    let statusCode = 500;
    let code = 'INTERNAL_ERROR';
    let message = 'An unexpected error occurred';
    let details = undefined;
    if (err instanceof APIError) {
        statusCode = err.statusCode;
        code = err.code;
        message = err.message;
        details = err.details;
    }
    else if (err.name === 'ValidationError') {
        statusCode = 400;
        code = 'VALIDATION_ERROR';
        message = err.message;
    }
    else if (err.name === 'SyntaxError' && 'body' in err) {
        statusCode = 400;
        code = 'INVALID_JSON';
        message = 'Invalid JSON in request body';
    }
    else if (err.name === 'UnauthorizedError') {
        statusCode = 401;
        code = 'UNAUTHORIZED';
        message = 'Invalid or expired token';
    }
    // Build error response
    const errorResponse = {
        success: false,
        error: {
            message,
            code,
            statusCode,
            timestamp: new Date().toISOString(),
            path: req.path
        }
    };
    // Include details in development mode
    if (process.env.NODE_ENV === 'development') {
        errorResponse.error.details = details || {
            stack: err.stack?.split('\n').slice(0, 5)
        };
    }
    else if (details && code === 'VALIDATION_ERROR') {
        // Always include validation errors
        errorResponse.error.details = details;
    }
    res.status(statusCode).json(errorResponse);
};
exports.errorHandler = errorHandler;
/**
 * Not found handler for unmatched routes
 */
const notFoundHandler = (req, res) => {
    res.status(404).json({
        success: false,
        error: {
            message: `Route not found: ${req.method} ${req.path}`,
            code: 'ROUTE_NOT_FOUND',
            statusCode: 404,
            timestamp: new Date().toISOString(),
            path: req.path
        }
    });
};
exports.notFoundHandler = notFoundHandler;
/**
 * Async handler wrapper to catch async errors
 */
const asyncHandler = (fn) => {
    return (req, res, next) => {
        Promise.resolve(fn(req, res, next)).catch(next);
    };
};
exports.asyncHandler = asyncHandler;
exports.default = exports.errorHandler;
//# sourceMappingURL=errorHandler.js.map