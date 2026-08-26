/**
 * Governance Routes
 *
 * Trust scoring and self-update approval endpoints, backed by the Python
 * governance engine via the bridge. Mirrors docs/GOVERNANCE.md.
 */

import { Router, Request, Response } from "express";

import { GovernanceController } from "../controllers/governanceController";
import { asyncHandler, Errors } from "../middleware/errorHandler";

const router = Router();
const controller = new GovernanceController();

router.get(
  "/checkpoints",
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.listCheckpoints();
    res.json({ success: true, data });
  }),
);

router.get(
  "/checkpoints/:checkpointId",
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.getCheckpoint(req.params.checkpointId);
    res.json({ success: true, data });
  }),
);

router.post(
  "/checkpoints",
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.createCheckpoint(req.body ?? {});
    res.status(201).json({ success: true, data });
  }),
);

router.post(
  "/checkpoints/:checkpointId/rollback",
  asyncHandler(async (req: Request, res: Response) => {
    const body = req.body ?? {};
    if (body.confirmed !== true || typeof body.initiated_by !== "string") {
      throw Errors.BadRequest("confirmed=true and initiated_by are required");
    }
    const data = await controller.rollbackCheckpoint(
      req.params.checkpointId,
      body,
    );
    res.json({ success: true, data });
  }),
);

/**
 * POST /api/v1/governance/agents/:agentId/trust
 * Compute (and persist unless persist=false) an agent's trust score.
 * Body: { metrics?: {...}, persist?: boolean }
 */
router.post(
  "/agents/:agentId/trust",
  asyncHandler(async (req: Request, res: Response) => {
    const body = req.body ?? {};
    const metrics = body.metrics ?? {};
    if (typeof metrics !== "object" || Array.isArray(metrics)) {
      throw Errors.BadRequest("metrics must be an object");
    }
    const persist = body.persist !== false; // default true
    const data = await controller.computeTrust(
      req.params.agentId,
      metrics,
      persist,
    );
    res.json({ success: true, data });
  }),
);

/**
 * POST /api/v1/governance/updates
 * Evaluate a proposed self-update and return its approval tier decision.
 * Body: {
 *   agent_id: string,
 *   trust_score?: number, metrics?: {...}, has_history?: boolean,
 *   code_change_ratio?: number, breaking_changes?: boolean,
 *   new_dependencies?: boolean, policy_change?: boolean,
 *   affects_governance?: boolean
 * }
 */
router.post(
  "/updates",
  asyncHandler(async (req: Request, res: Response) => {
    const body = req.body ?? {};
    const agentId = body.agent_id ?? body.agentId;
    if (!agentId || typeof agentId !== "string") {
      throw Errors.BadRequest("agent_id is required");
    }
    const { agent_id, agentId: _a, ...proposal } = body;
    const data = await controller.evaluateUpdate(agentId, proposal);
    res.json({ success: true, data });
  }),
);

export default router;
