"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
require("dotenv/config");
const express_1 = __importDefault(require("express"));
const cors_1 = __importDefault(require("cors"));
const config_1 = require("./config");
const mcp_server_1 = require("./mcp-server");
const logger_1 = require("./utils/logger");
const requestLogger_1 = __importDefault(require("./utils/requestLogger"));
const app = (0, express_1.default)();
app.use((0, cors_1.default)());
app.use(express_1.default.json());
app.use(requestLogger_1.default);
app.use('/api', mcp_server_1.mcpRouter);
app.get('/health', (_req, res) => {
    res.status(200).json({ status: 'ok' });
});
app.listen(config_1.PORT, () => {
    logger_1.logger.info(`MCP Server running on port ${config_1.PORT}`);
    logger_1.logger.info(`Access at http://localhost:${config_1.PORT}`);
});
