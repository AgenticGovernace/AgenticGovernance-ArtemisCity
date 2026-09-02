/**
 * Trust Routes
 *
 * Bridge-backed trust and Hebbian reads/mutations.
 */

import { Router, Request, Response } from "express";
import { TrustController } from "../controllers/trustController";
import { asyncHandler, Errors } from "../middleware/errorHandler";

const router = Router();
const controller = new TrustController();

function requestBody(req: Request): Record<string, unknown> {
  return (req.body ?? {}) as Record<string, unknown>;
}

router.get(
  "/hebbian/weights",
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getHebbianWeights();
    res.json({ success: true, data });
  }),
);

router.get(
  "/hebbian/sentinel",
  asyncHandler(async (req: Request, res: Response) => {
    const agentName =
      typeof req.query.agent_name === "string"
        ? req.query.agent_name
        : undefined;
    const taskType =
      typeof req.query.task_type === "string" ? req.query.task_type : undefined;
    const limit =
      typeof req.query.limit === "string" ? Number(req.query.limit) : 100;
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
      throw Errors.BadRequest("limit must be an integer between 1 and 500");
    }
    const data = await controller.getHebbianSentinelStatus(
      agentName,
      taskType,
      limit,
    );
    res.json({ success: true, data });
  }),
);

router.get(
  "/hebbian/sentinel/alerts",
  asyncHandler(async (req: Request, res: Response) => {
    const openOnly = req.query.open_only === "true";
    const limit =
      typeof req.query.limit === "string" ? Number(req.query.limit) : 100;
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
      throw Errors.BadRequest("limit must be an integer between 1 and 500");
    }
    const data = await controller.getHebbianSentinelAlerts(openOnly, limit);
    res.json({ success: true, data });
  }),
);

router.put(
  "/hebbian/weights",
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const { agent1, agent2, delta } = payload;
    if (typeof agent1 !== "string" || typeof agent2 !== "string") {
      throw Errors.BadRequest("agent1 and agent2 are required");
    }
    if (typeof delta !== "number") {
      throw Errors.BadRequest("delta must be a number");
    }
    const data = await controller.updateHebbianWeight(agent1, agent2, delta);
    res.json({ success: true, data });
  }),
);

router.get(
  "/levels",
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getTrustLevels();
    res.json({ success: true, data });
  }),
);

router.get(
  "/report",
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getTrustReport();
    res.json({ success: true, data });
  }),
);

router.get(
  "/:entityId",
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.getTrustScore(req.params.entityId);
    res.json({ success: true, data });
  }),
);

router.put(
  "/:entityId",
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const score = payload.score;
    if (typeof score !== "number") {
      throw Errors.BadRequest("score must be a number");
    }
    const entityType =
      typeof payload.entityType === "string" ? payload.entityType : "agent";
    const data = await controller.setTrustScore(
      req.params.entityId,
      score,
      entityType,
    );
    res.json({ success: true, data });
  }),
);

router.post(
  "/:entityId/success",
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const amount = payload.amount ?? 0.02;
    if (typeof amount !== "number" || amount < 0) {
      throw Errors.BadRequest("amount must be a non-negative number");
    }
    const data = await controller.recordSuccess(req.params.entityId, amount);
    res.json({ success: true, data });
  }),
);

router.post(
  "/:entityId/failure",
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const amount = payload.amount ?? 0.05;
    if (typeof amount !== "number" || amount < 0) {
      throw Errors.BadRequest("amount must be a non-negative number");
    }
    const data = await controller.recordFailure(req.params.entityId, amount);
    res.json({
      success: true,
      data,
      message:
        "Trust failure recorded and synchronized with the agent registry",
    });
  }),
);

router.get(
  "/:entityId/permissions",
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.getPermissions(req.params.entityId);
    res.json({ success: true, data });
  }),
);

router.post(
  "/:entityId/can-perform",
  asyncHandler(async (req: Request, res: Response) => {
    const operation = requestBody(req).operation;
    if (typeof operation !== "string" || operation.length === 0) {
      throw Errors.BadRequest("operation is required");
    }
    const data = await controller.canPerformOperation(
      req.params.entityId,
      operation,
    );
    res.json({ success: true, data });
  }),
);

export default router;
