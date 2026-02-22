"use strict";
/**
 * Artemis City API
 *
 * Main entry point for the Artemis City REST API.
 * Provides endpoints for agent coordination, memory operations, and ATP messaging.
 *
 * Author: Prinston Palmer
 * Version: 1.0.0
 */
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.app = void 0;
exports.startServer = startServer;
const express_1 = __importDefault(require("express"));
const cors_1 = __importDefault(require("cors"));
const helmet_1 = __importDefault(require("helmet"));
// Routes
const agents_1 = __importDefault(require("./routes/agents"));
const memory_1 = __importDefault(require("./routes/memory"));
const atp_1 = __importDefault(require("./routes/atp"));
const trust_1 = __importDefault(require("./routes/trust"));
const health_1 = __importDefault(require("./routes/health"));
const llm_1 = __importDefault(require("./routes/llm"));
// Middleware
const auth_1 = require("./middleware/auth");
const errorHandler_1 = require("./middleware/errorHandler");
const logger_1 = require("./middleware/logger");
// Config
const PORT = process.env.API_PORT || 4000;
const API_VERSION = 'v1';
// Initialize Express app
const app = (0, express_1.default)();
exports.app = app;
// ============================================================================
// Global Middleware
// ============================================================================
app.use((0, helmet_1.default)());
app.use((0, cors_1.default)());
app.use(express_1.default.json({ limit: '10mb' }));
app.use(express_1.default.urlencoded({ extended: true }));
app.use(logger_1.requestLogger);
// ============================================================================
// Routes
// ============================================================================
// Public routes (no auth)
app.use('/health', health_1.default);
app.use(`/api/${API_VERSION}/health`, health_1.default);
// Protected routes (require auth)
app.use(`/api/${API_VERSION}/agents`, auth_1.authMiddleware, agents_1.default);
app.use(`/api/${API_VERSION}/memory`, auth_1.authMiddleware, memory_1.default);
app.use(`/api/${API_VERSION}/atp`, auth_1.authMiddleware, atp_1.default);
app.use(`/api/${API_VERSION}/trust`, auth_1.authMiddleware, trust_1.default);
app.use(`/api/${API_VERSION}/llm`, auth_1.authMiddleware, llm_1.default);
// API documentation endpoint
app.get(`/api/${API_VERSION}`, (req, res) => {
    res.json({
        name: 'Artemis City API',
        version: '1.0.0',
        apiVersion: API_VERSION,
        endpoints: {
            health: '/health',
            agents: `/api/${API_VERSION}/agents`,
            memory: `/api/${API_VERSION}/memory`,
            atp: `/api/${API_VERSION}/atp`,
            trust: `/api/${API_VERSION}/trust`,
            llm: `/api/${API_VERSION}/llm`
        },
        documentation: `/api/${API_VERSION}/docs`
    });
});
// 404 handler
app.use((req, res) => {
    res.status(404).json({
        success: false,
        error: 'Endpoint not found',
        path: req.path
    });
});
// Error handler
app.use(errorHandler_1.errorHandler);
// ============================================================================
// Server Start
// ============================================================================
function startServer() {
    app.listen(PORT, () => {
        console.log('='.repeat(50));
        console.log('Artemis City API Server');
        console.log('='.repeat(50));
        console.log(`Server running on http://localhost:${PORT}`);
        console.log(`API endpoint: http://localhost:${PORT}/api/${API_VERSION}`);
        console.log(`Health check: http://localhost:${PORT}/health`);
        console.log('='.repeat(50));
    });
}
// Start if run directly
if (require.main === module) {
    startServer();
}
//# sourceMappingURL=index.js.map