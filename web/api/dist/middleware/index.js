"use strict";
/**
 * Middleware Index
 *
 * Exports all middleware modules.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.log = exports.clearLogs = exports.getLogsByPath = exports.getLogsByLevel = exports.getRecentLogs = exports.requestLogger = exports.Errors = exports.APIError = exports.asyncHandler = exports.notFoundHandler = exports.errorHandler = exports.rateLimit = exports.requireRole = exports.requirePermission = exports.authMiddleware = void 0;
var auth_1 = require("./auth");
Object.defineProperty(exports, "authMiddleware", { enumerable: true, get: function () { return auth_1.authMiddleware; } });
Object.defineProperty(exports, "requirePermission", { enumerable: true, get: function () { return auth_1.requirePermission; } });
Object.defineProperty(exports, "requireRole", { enumerable: true, get: function () { return auth_1.requireRole; } });
Object.defineProperty(exports, "rateLimit", { enumerable: true, get: function () { return auth_1.rateLimit; } });
var errorHandler_1 = require("./errorHandler");
Object.defineProperty(exports, "errorHandler", { enumerable: true, get: function () { return errorHandler_1.errorHandler; } });
Object.defineProperty(exports, "notFoundHandler", { enumerable: true, get: function () { return errorHandler_1.notFoundHandler; } });
Object.defineProperty(exports, "asyncHandler", { enumerable: true, get: function () { return errorHandler_1.asyncHandler; } });
Object.defineProperty(exports, "APIError", { enumerable: true, get: function () { return errorHandler_1.APIError; } });
Object.defineProperty(exports, "Errors", { enumerable: true, get: function () { return errorHandler_1.Errors; } });
var logger_1 = require("./logger");
Object.defineProperty(exports, "requestLogger", { enumerable: true, get: function () { return logger_1.requestLogger; } });
Object.defineProperty(exports, "getRecentLogs", { enumerable: true, get: function () { return logger_1.getRecentLogs; } });
Object.defineProperty(exports, "getLogsByLevel", { enumerable: true, get: function () { return logger_1.getLogsByLevel; } });
Object.defineProperty(exports, "getLogsByPath", { enumerable: true, get: function () { return logger_1.getLogsByPath; } });
Object.defineProperty(exports, "clearLogs", { enumerable: true, get: function () { return logger_1.clearLogs; } });
Object.defineProperty(exports, "log", { enumerable: true, get: function () { return logger_1.log; } });
//# sourceMappingURL=index.js.map