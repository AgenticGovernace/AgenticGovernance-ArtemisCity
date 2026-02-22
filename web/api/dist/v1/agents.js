"use strict";
/**
 * Agent Routes
 *
 * Endpoints for agent registry operations.
 */
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const agentController_1 = require("../controllers/agentController");
const router = (0, express_1.Router)();
const controller = new agentController_1.AgentController();
/**
 * GET /api/v1/agents
 * List all registered agents
 */
router.get('/', async (req, res) => {
    try {
        const agents = await controller.getAllAgents();
        res.json({
            success: true,
            data: agents,
            count: agents.length
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
 * GET /api/v1/agents/:id
 * Get agent by ID
 */
router.get('/:id', async (req, res) => {
    try {
        const agent = await controller.getAgent(req.params.id);
        if (!agent) {
            res.status(404).json({
                success: false,
                error: `Agent not found: ${req.params.id}`
            });
            return;
        }
        res.json({
            success: true,
            data: agent
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
 * POST /api/v1/agents
 * Register a new agent
 */
router.post('/', async (req, res) => {
    try {
        const agent = await controller.registerAgent(req.body);
        res.status(201).json({
            success: true,
            data: agent,
            message: 'Agent registered successfully'
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
 * PUT /api/v1/agents/:id
 * Update an agent
 */
router.put('/:id', async (req, res) => {
    try {
        const agent = await controller.updateAgent(req.params.id, req.body);
        if (!agent) {
            res.status(404).json({
                success: false,
                error: `Agent not found: ${req.params.id}`
            });
            return;
        }
        res.json({
            success: true,
            data: agent,
            message: 'Agent updated successfully'
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
 * DELETE /api/v1/agents/:id
 * Unregister an agent
 */
router.delete('/:id', async (req, res) => {
    try {
        const success = await controller.deleteAgent(req.params.id);
        if (!success) {
            res.status(404).json({
                success: false,
                error: `Agent not found: ${req.params.id}`
            });
            return;
        }
        res.json({
            success: true,
            message: 'Agent unregistered successfully'
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
 * POST /api/v1/agents/:id/suspend
 * Suspend an agent
 */
router.post('/:id/suspend', async (req, res) => {
    try {
        const { reason } = req.body;
        const success = await controller.suspendAgent(req.params.id, reason);
        if (!success) {
            res.status(404).json({
                success: false,
                error: `Agent not found: ${req.params.id}`
            });
            return;
        }
        res.json({
            success: true,
            message: `Agent suspended: ${reason || 'No reason provided'}`
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
 * POST /api/v1/agents/:id/activate
 * Activate an agent
 */
router.post('/:id/activate', async (req, res) => {
    try {
        const success = await controller.activateAgent(req.params.id);
        if (!success) {
            res.status(404).json({
                success: false,
                error: `Agent not found: ${req.params.id}`
            });
            return;
        }
        res.json({
            success: true,
            message: 'Agent activated successfully'
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
 * GET /api/v1/agents/:id/card
 * Get agent card (markdown format)
 */
router.get('/:id/card', async (req, res) => {
    try {
        const card = await controller.getAgentCard(req.params.id);
        if (!card) {
            res.status(404).json({
                success: false,
                error: `Agent not found: ${req.params.id}`
            });
            return;
        }
        if (req.query.format === 'markdown') {
            res.type('text/markdown').send(card);
        }
        else {
            res.json({
                success: true,
                data: { markdown: card }
            });
        }
    }
    catch (error) {
        res.status(500).json({
            success: false,
            error: error.message
        });
    }
});
exports.default = router;
//# sourceMappingURL=agents.js.map