"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const logger_1 = require("./logger");
const requestLogger = (req, _res, next) => {
    logger_1.logger.info(`${req.method} ${req.originalUrl} from ${req.ip}`);
    next();
};
exports.default = requestLogger;
