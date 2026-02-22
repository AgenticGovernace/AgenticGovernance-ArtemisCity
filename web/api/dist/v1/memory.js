"use strict";
/**
 * Memory Routes
 *
 * Endpoints for vault/memory operations via MCP.
 */
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const memoryController_1 = require("../controllers/memoryController");
const router = (0, express_1.Router)();
const controller = new memoryController_1.MemoryController();
/**
 * GET /api/v1/memory/stats
 * Get vault statistics
 */
router.get('/stats', async (req, res) => {
    try {
        const stats = await controller.getStats();
        res.json({
            success: true,
            data: stats
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
 * POST /api/v1/memory/read
 * Read a file from the vault
 */
router.post('/read', async (req, res) => {
    try {
        const { path } = req.body;
        if (!path) {
            res.status(400).json({
                success: false,
                error: 'path is required'
            });
            return;
        }
        const result = await controller.readFile(path);
        if (!result) {
            res.status(404).json({
                success: false,
                error: `File not found: ${path}`
            });
            return;
        }
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
 * POST /api/v1/memory/write
 * Write content to the vault
 */
router.post('/write', async (req, res) => {
    try {
        const { path, content, metadata } = req.body;
        if (!path || content === undefined) {
            res.status(400).json({
                success: false,
                error: 'path and content are required'
            });
            return;
        }
        const result = await controller.writeFile(path, content, metadata);
        res.json({
            success: true,
            data: result,
            message: 'File written successfully'
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
 * POST /api/v1/memory/search
 * Search the vault
 */
router.post('/search', async (req, res) => {
    try {
        const { query, path, tags, limit = 10 } = req.body;
        if (!query) {
            res.status(400).json({
                success: false,
                error: 'query is required'
            });
            return;
        }
        const results = await controller.search(query, { path, tags, limit });
        res.json({
            success: true,
            data: results,
            count: results.length
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
 * POST /api/v1/memory/list
 * List files in a directory
 */
router.post('/list', async (req, res) => {
    try {
        const { path = '' } = req.body;
        const files = await controller.listFiles(path);
        res.json({
            success: true,
            data: files,
            count: files.length
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
 * POST /api/v1/memory/delete
 * Delete a file from the vault
 */
router.post('/delete', async (req, res) => {
    try {
        const { path } = req.body;
        if (!path) {
            res.status(400).json({
                success: false,
                error: 'path is required'
            });
            return;
        }
        const success = await controller.deleteFile(path);
        if (!success) {
            res.status(404).json({
                success: false,
                error: `File not found: ${path}`
            });
            return;
        }
        res.json({
            success: true,
            message: 'File deleted successfully'
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
 * GET /api/v1/memory/context
 * Get current context
 */
router.get('/context', async (req, res) => {
    try {
        const context = await controller.getContext();
        res.json({
            success: true,
            data: context
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
 * PUT /api/v1/memory/context
 * Update context
 */
router.put('/context', async (req, res) => {
    try {
        const { key, value } = req.body;
        if (!key) {
            res.status(400).json({
                success: false,
                error: 'key is required'
            });
            return;
        }
        const context = await controller.updateContextData(key, value);
        res.json({
            success: true,
            data: context,
            message: 'Context updated'
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
 * DELETE /api/v1/memory/context
 * Clear context
 */
router.delete('/context', async (req, res) => {
    try {
        await controller.clearContext();
        res.json({
            success: true,
            message: 'Context cleared'
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
//# sourceMappingURL=memory.js.map