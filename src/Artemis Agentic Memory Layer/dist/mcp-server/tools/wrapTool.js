"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.wrapTool = wrapTool;
const logger_1 = require("../../utils/logger");
function wrapTool(name, fn) {
    return async (...args) => {
        try {
            logger_1.logger.debug(`${name} called`, ...args);
            const payload = await fn(...args);
            logger_1.logger.info(`${name} succeeded`);
            return { success: true, ...payload };
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            logger_1.logger.error(`${name} failed: ${message}`);
            return { success: false, error: message };
        }
    };
}
