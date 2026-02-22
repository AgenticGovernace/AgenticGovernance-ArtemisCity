"use strict";
/**
 * Logger Middleware
 *
 * Request/response logging for the API.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.log = exports.clearLogs = exports.getLogsByPath = exports.getLogsByLevel = exports.getRecentLogs = exports.requestLogger = void 0;
/**
 * Color codes for console output
 */
const colors = {
    reset: '\x1b[0m',
    bright: '\x1b[1m',
    dim: '\x1b[2m',
    red: '\x1b[31m',
    green: '\x1b[32m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
    magenta: '\x1b[35m',
    cyan: '\x1b[36m',
    white: '\x1b[37m'
};
/**
 * Get color for status code
 */
const getStatusColor = (status) => {
    if (status >= 500)
        return colors.red;
    if (status >= 400)
        return colors.yellow;
    if (status >= 300)
        return colors.cyan;
    if (status >= 200)
        return colors.green;
    return colors.white;
};
/**
 * Get color for log level
 */
const getLevelColor = (level) => {
    switch (level) {
        case 'ERROR': return colors.red;
        case 'WARN': return colors.yellow;
        case 'INFO': return colors.green;
        case 'DEBUG': return colors.dim;
        default: return colors.white;
    }
};
/**
 * Format log entry for console
 */
const formatLogEntry = (entry) => {
    const levelColor = getLevelColor(entry.level);
    const statusColor = entry.statusCode ? getStatusColor(entry.statusCode) : colors.white;
    let line = `${colors.dim}[${entry.timestamp}]${colors.reset} `;
    line += `${levelColor}${entry.level.padEnd(5)}${colors.reset} `;
    line += `${colors.bright}${entry.method.padEnd(6)}${colors.reset} `;
    line += `${entry.path} `;
    if (entry.statusCode) {
        line += `${statusColor}${entry.statusCode}${colors.reset} `;
    }
    if (entry.duration !== undefined) {
        const durationColor = entry.duration > 1000 ? colors.yellow : colors.dim;
        line += `${durationColor}${entry.duration}ms${colors.reset} `;
    }
    if (entry.userId) {
        line += `${colors.magenta}[${entry.userId}]${colors.reset} `;
    }
    if (entry.message) {
        line += `${colors.dim}${entry.message}${colors.reset}`;
    }
    if (entry.error) {
        line += `${colors.red}${entry.error}${colors.reset}`;
    }
    return line;
};
/**
 * In-memory log storage (limited buffer)
 */
const logBuffer = [];
const MAX_LOG_BUFFER = 1000;
/**
 * Store log entry
 */
const storeLog = (entry) => {
    logBuffer.push(entry);
    if (logBuffer.length > MAX_LOG_BUFFER) {
        logBuffer.shift();
    }
};
/**
 * Generate request ID
 */
const generateRequestId = () => {
    return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
};
/**
 * Request logger middleware
 */
const requestLogger = (req, res, next) => {
    const startTime = Date.now();
    const requestId = generateRequestId();
    // Attach request ID to request
    req.requestId = requestId;
    // Store original end function
    const originalEnd = res.end;
    const originalJson = res.json;
    // Override res.end to capture response
    res.end = function (chunk, encoding) {
        const duration = Date.now() - startTime;
        const entry = {
            timestamp: new Date().toISOString(),
            level: res.statusCode >= 400 ? (res.statusCode >= 500 ? 'ERROR' : 'WARN') : 'INFO',
            method: req.method,
            path: req.path,
            statusCode: res.statusCode,
            duration,
            ip: req.ip || req.socket.remoteAddress,
            userAgent: req.headers['user-agent'],
            userId: req.user?.id,
            requestId
        };
        // Log to console
        console.log(formatLogEntry(entry));
        // Store log
        storeLog(entry);
        return originalEnd.call(this, chunk, encoding);
    };
    next();
};
exports.requestLogger = requestLogger;
/**
 * Get recent logs
 */
const getRecentLogs = (count = 100) => {
    return logBuffer.slice(-count);
};
exports.getRecentLogs = getRecentLogs;
/**
 * Get logs by level
 */
const getLogsByLevel = (level) => {
    return logBuffer.filter(log => log.level === level);
};
exports.getLogsByLevel = getLogsByLevel;
/**
 * Get logs by path pattern
 */
const getLogsByPath = (pathPattern) => {
    const regex = new RegExp(pathPattern);
    return logBuffer.filter(log => regex.test(log.path));
};
exports.getLogsByPath = getLogsByPath;
/**
 * Clear logs
 */
const clearLogs = () => {
    logBuffer.length = 0;
};
exports.clearLogs = clearLogs;
/**
 * Manual log function
 */
const log = (level, message, context) => {
    const entry = {
        timestamp: new Date().toISOString(),
        level,
        method: context?.method || '-',
        path: context?.path || '-',
        message,
        ...context
    };
    console.log(formatLogEntry(entry));
    storeLog(entry);
};
exports.log = log;
exports.default = exports.requestLogger;
//# sourceMappingURL=logger.js.map