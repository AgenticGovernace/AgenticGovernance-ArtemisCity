"use strict";
/**
 * LLM API Routes
 *
 * Endpoints for interacting with LLM providers (Claude, OpenAI, etc.)
 */
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const llmController_1 = require("../controllers/llmController");
const router = (0, express_1.Router)();
const controller = new llmController_1.LLMController();
/**
 * POST /api/v1/llm/chat
 * Send a chat completion request
 */
router.post('/chat', async (req, res) => {
    try {
        const { messages, model, options } = req.body;
        if (!messages || !Array.isArray(messages)) {
            res.status(400).json({
                success: false,
                error: 'messages array is required'
            });
            return;
        }
        const result = await controller.chat(messages, model, options);
        res.json({
            success: true,
            data: result
        });
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
/**
 * POST /api/v1/llm/complete
 * Send a text completion request
 */
router.post('/complete', async (req, res) => {
    try {
        const { prompt, model, options } = req.body;
        if (!prompt) {
            res.status(400).json({
                success: false,
                error: 'prompt is required'
            });
            return;
        }
        const result = await controller.complete(prompt, model, options);
        res.json({
            success: true,
            data: result
        });
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
/**
 * POST /api/v1/llm/embed
 * Generate embeddings for text
 */
router.post('/embed', async (req, res) => {
    try {
        const { text, model } = req.body;
        if (!text) {
            res.status(400).json({
                success: false,
                error: 'text is required'
            });
            return;
        }
        const result = await controller.embed(text, model);
        res.json({
            success: true,
            data: result
        });
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
/**
 * POST /api/v1/llm/stream
 * Stream a chat completion (SSE)
 */
router.post('/stream', async (req, res) => {
    try {
        const { messages, model, options } = req.body;
        if (!messages || !Array.isArray(messages)) {
            res.status(400).json({
                success: false,
                error: 'messages array is required'
            });
            return;
        }
        // Set up SSE headers
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        await controller.streamChat(messages, model, options, (chunk) => {
            res.write(`data: ${JSON.stringify(chunk)}\n\n`);
        });
        res.write('data: [DONE]\n\n');
        res.end();
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
/**
 * GET /api/v1/llm/models
 * List available models
 */
router.get('/models', async (req, res) => {
    try {
        const models = await controller.listModels();
        res.json({
            success: true,
            data: models
        });
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
/**
 * GET /api/v1/llm/providers
 * List configured providers
 */
router.get('/providers', (req, res) => {
    try {
        const providers = controller.getProviders();
        res.json({
            success: true,
            data: providers
        });
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
/**
 * POST /api/v1/llm/provider
 * Configure a provider
 */
router.post('/provider', async (req, res) => {
    try {
        const { provider, apiKey, baseUrl, options } = req.body;
        if (!provider) {
            res.status(400).json({
                success: false,
                error: 'provider is required'
            });
            return;
        }
        const result = await controller.configureProvider(provider, { apiKey, baseUrl, ...options });
        res.json({
            success: true,
            data: result,
            message: `Provider ${provider} configured successfully`
        });
    }
    catch (error) {
        res.status(400).json({
            success: false,
            error: error.message
        });
    }
});
/**
 * POST /api/v1/llm/atp
 * Process an ATP message through LLM
 */
router.post('/atp', async (req, res) => {
    try {
        const { atpMessage, model, agentId } = req.body;
        if (!atpMessage) {
            res.status(400).json({
                success: false,
                error: 'atpMessage is required'
            });
            return;
        }
        const result = await controller.processATP(atpMessage, model, agentId);
        res.json({
            success: true,
            data: result
        });
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
/**
 * GET /api/v1/llm/usage
 * Get token usage statistics
 */
router.get('/usage', async (req, res) => {
    try {
        const { startDate, endDate, provider } = req.query;
        const usage = await controller.getUsage({
            startDate: startDate,
            endDate: endDate,
            provider: provider
        });
        res.json({
            success: true,
            data: usage
        });
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
exports.default = router;
//# sourceMappingURL=llm.js.map