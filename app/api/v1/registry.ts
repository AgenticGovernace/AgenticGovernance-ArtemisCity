/**
 * Registry Routes
 *
 * Agent registry + governance endpoints, backed by the Python core via the
 * bridge. Mirrors the registry/governance surface in docs/API_REFERENCE.md.
 */

import { Router, Request, Response } from 'express';

import { RegistryController } from '../controllers/registryController';
import { asyncHandler, Errors } from '../middleware/errorHandler';

const router = Router();
const controller = new RegistryController();

/**
 * GET /api/v1/registry/agents
 * List all registered agents with scores and governance state.
 */
router.get(
  '/agents',
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.listAgents();
    res.json({ success: true, data });
  })
);

/**
 * GET /api/v1/registry/agents/:agentId
 * Get a single agent's full record.
 */
router.get(
  '/agents/:agentId',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.getAgent(req.params.agentId);
    res.json({ success: true, data });
  })
);

/**
 * GET /api/v1/registry/agents/:agentId/violations
 * List an agent's violations and quarantine state.
 * Query: include_cleared=true|false, limit=N
 */
router.get(
  '/agents/:agentId/violations',
  asyncHandler(async (req: Request, res: Response) => {
    const includeCleared = req.query.include_cleared === 'true';
    const limit = req.query.limit ? parseInt(String(req.query.limit), 10) : 100;
    if (Number.isNaN(limit) || limit < 1) {
      throw Errors.BadRequest('limit must be a positive integer');
    }
    const data = await controller.getViolations(req.params.agentId, includeCleared, limit);
    res.json({ success: true, data });
  })
);

/**
 * POST /api/v1/registry/agents/:agentId/clear-violations
 * Clear violations and release quarantine.
 * Body: { rationale: string, override_tier?: "auto"|"monitored"|"human" }
 */
router.post(
  '/agents/:agentId/clear-violations',
  asyncHandler(async (req: Request, res: Response) => {
    const { rationale, override_tier: overrideTier } = req.body ?? {};
    if (!rationale || typeof rationale !== 'string') {
      throw Errors.BadRequest('rationale is required');
    }
    const data = await controller.clearViolations(req.params.agentId, rationale, overrideTier);
    res.json({ success: true, data });
  })
);

/**
 * PATCH /api/v1/registry/agents/:agentId/trust-tier
 * Set an agent's trust tier.
 * Body: { trust_tier: "auto"|"monitored"|"human" }
 */
router.patch(
  '/agents/:agentId/trust-tier',
  asyncHandler(async (req: Request, res: Response) => {
    const tier = (req.body ?? {}).trust_tier;
    if (!tier || typeof tier !== 'string') {
      throw Errors.BadRequest('trust_tier is required');
    }
    const data = await controller.setTrustTier(req.params.agentId, tier);
    res.json({ success: true, data });
  })
);

export default router;
