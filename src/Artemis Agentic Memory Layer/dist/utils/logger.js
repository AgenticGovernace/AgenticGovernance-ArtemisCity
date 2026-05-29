"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.logger = void 0;
var LogLevel;
(function (LogLevel) {
    LogLevel[LogLevel["DEBUG"] = 0] = "DEBUG";
    LogLevel[LogLevel["INFO"] = 1] = "INFO";
    LogLevel[LogLevel["WARN"] = 2] = "WARN";
    LogLevel[LogLevel["ERROR"] = 3] = "ERROR";
})(LogLevel || (LogLevel = {}));
const LEVEL_FROM_ENV = {
    debug: LogLevel.DEBUG,
    info: LogLevel.INFO,
    warn: LogLevel.WARN,
    error: LogLevel.ERROR,
};
const currentLogLevel = LEVEL_FROM_ENV[(process.env.MCP_LOG_LEVEL ?? 'info').toLowerCase()] ?? LogLevel.INFO;
const log = (level, message, ...args) => {
    if (level < currentLogLevel)
        return;
    const formatted = `[${new Date().toISOString()}] [${LogLevel[level]}] ${message}`;
    switch (level) {
        case LogLevel.DEBUG:
            console.debug(formatted, ...args);
            break;
        case LogLevel.INFO:
            console.info(formatted, ...args);
            break;
        case LogLevel.WARN:
            console.warn(formatted, ...args);
            break;
        case LogLevel.ERROR:
            console.error(formatted, ...args);
            break;
    }
};
exports.logger = {
    debug: (message, ...args) => log(LogLevel.DEBUG, message, ...args),
    info: (message, ...args) => log(LogLevel.INFO, message, ...args),
    warn: (message, ...args) => log(LogLevel.WARN, message, ...args),
    error: (message, ...args) => log(LogLevel.ERROR, message, ...args),
};
