/**
 * Agent Routes
 *
 * Read-only registry facade backed by the Python bridge.
 */

import { Router, Request, Response } from 'express';
import { AgentController } from '../controllers/agentController';
import { asyncHandler } from '../middleware/errorHandler';

const router = Router();
const controller = new AgentController();
const escapeHtml = (value: string): string =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

router.get(
  '/',
  asyncHandler(async (_req: Request, res: Response) => {
    const agents = await controller.getAllAgents();
    res.json({
      success: true,
      data: agents,
      count: agents.length,
    });
  })
);

router.get(
  '/:id/card',
  asyncHandler(async (req: Request, res: Response) => {
    const card = await controller.getAgentCard(req.params.id);
    if (req.query.format === 'markdown') {
      res
        .type('text/plain')
        .set('X-Content-Type-Options', 'nosniff')
        .send(escapeHtml(card.markdown));
      return;
    }
    res.json({
      success: true,
      data: card,
    });
  })
);

router.get(
  '/:id',
  asyncHandler(async (req: Request, res: Response) => {
    const agent = await controller.getAgent(req.params.id);
    res.json({
      success: true,
      data: agent,
    });
  })
);

router.post(
  '/',
  asyncHandler(async (req: Request, res: Response) => {
    const agent = await controller.registerAgent(req.body ?? {});
    res.json({ success: true, data: agent });
  })
);

router.put(
  '/:id',
  asyncHandler(async (req: Request, res: Response) => {
    const agent = await controller.updateAgent(req.params.id, req.body ?? {});
    res.json({ success: true, data: agent });
  })
);

router.delete(
  '/:id',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.deleteAgent(req.params.id);
    res.json({ success: true, data });
  })
);

router.post(
  '/:id/suspend',
  asyncHandler(async (req: Request, res: Response) => {
    const reason = typeof req.body?.reason === 'string' ? req.body.reason : undefined;
    const data = await controller.suspendAgent(req.params.id, reason);
    res.json({ success: true, data });
  })
);

router.post(
  '/:id/activate',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.activateAgent(req.params.id);
    res.json({ success: true, data });
  })
);

export default router;
