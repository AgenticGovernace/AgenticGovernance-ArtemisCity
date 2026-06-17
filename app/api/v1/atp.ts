/**
 * ATP (Artemis Transmission Protocol) Routes
 *
 * Parse and validate through the Python bridge.
 */

import { Router, Request, Response } from 'express';
import { ATPController } from '../controllers/atpController';
import { asyncHandler, Errors } from '../middleware/errorHandler';

const router = Router();
const controller = new ATPController();

function requestBody(req: Request): Record<string, unknown> {
  return (req.body ?? {}) as Record<string, unknown>;
}

function requireMessage(req: Request): string {
  const payload = requestBody(req);
  const message = payload.message ?? payload.text;
  if (typeof message !== 'string' || message.length === 0) {
    throw Errors.BadRequest('message is required');
  }
  return message;
}

router.post(
  '/parse',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.parseMessage(requireMessage(req));
    res.json({ success: true, data });
  })
);

router.post(
  '/validate',
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const strict = payload.strict === true;
    const data = await controller.validateMessage(requireMessage(req), strict);
    res.json({ success: true, data });
  })
);

router.post(
  '/send',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.sendMessage(requestBody(req));
    res.json({ success: true, data });
  })
);

router.post(
  '/route',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.routeMessage(requestBody(req));
    res.json({ success: true, data });
  })
);

router.get(
  '/modes',
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getModes();
    res.json({ success: true, data });
  })
);

router.get(
  '/priorities',
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getPriorities();
    res.json({ success: true, data });
  })
);

router.get(
  '/action-types',
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getActionTypes();
    res.json({ success: true, data });
  })
);

router.get(
  '/template',
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getTemplate();
    res.json({ success: true, data });
  })
);

router.post(
  '/format',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.formatMessage(requestBody(req));
    res.json({ success: true, data });
  })
);

router.get(
  '/message/:id',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.getMessage(req.params.id);
    res.json({ success: true, data });
  })
);

router.get(
  '/response/:id',
  asyncHandler(async (req: Request, res: Response) => {
    const data = await controller.getResponse(req.params.id);
    res.json({ success: true, data });
  })
);

router.get(
  '/queue',
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getQueueStatus();
    res.json({ success: true, data });
  })
);

export default router;
