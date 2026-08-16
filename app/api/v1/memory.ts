/**
 * Memory Routes
 *
 * Vault operations backed by Python memory bridge commands.
 */

import { Router, Request, Response } from 'express';
import { MemoryController } from '../controllers/memoryController';
import { asyncHandler, Errors } from '../middleware/errorHandler';

const router = Router();
const controller = new MemoryController();

function requestBody(req: Request): Record<string, unknown> {
  return (req.body ?? {}) as Record<string, unknown>;
}

function requireString(payload: Record<string, unknown>, field: string): string {
  const value = payload[field];
  if (typeof value !== 'string' || value.length === 0) {
    throw Errors.BadRequest(`${field} is required`);
  }
  return value;
}

function optionalString(payload: Record<string, unknown>, field: string, fallback = ''): string {
  const value = payload[field];
  if (value === undefined || value === null) {
    return fallback;
  }
  if (typeof value !== 'string') {
    throw Errors.BadRequest(`${field} must be a string`);
  }
  return value;
}

function optionalNonEmptyString(
  payload: Record<string, unknown>,
  field: string
): string | undefined {
  const value = payload[field];
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw Errors.BadRequest(`${field} must be a nonempty string`);
  }
  return value;
}

function optionalBoolean(
  payload: Record<string, unknown>,
  field: string
): boolean | undefined {
  const value = payload[field];
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== 'boolean') {
    throw Errors.BadRequest(`${field} must be a boolean`);
  }
  return value;
}

function optionalLimit(payload: Record<string, unknown>, fallback = 10): number {
  const raw = payload.limit ?? fallback;
  const limit = Number(raw);
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw Errors.BadRequest('limit must be an integer between 1 and 100');
  }
  return limit;
}

function optionalTags(payload: Record<string, unknown>): string[] | undefined {
  const tags = payload.tags;
  if (tags === undefined || tags === null) {
    return undefined;
  }
  if (!Array.isArray(tags) || !tags.every((tag) => typeof tag === 'string')) {
    throw Errors.BadRequest('tags must be an array of strings');
  }
  return tags;
}

router.get(
  '/stats',
  asyncHandler(async (_req: Request, res: Response) => {
    const data = await controller.getStats();
    res.json({ success: true, data });
  })
);

router.post(
  '/read',
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const path = requireString(payload, 'path');
    const data = await controller.readFile(path);
    res.json({ success: true, data });
  })
);

router.post(
  '/write',
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const path = requireString(payload, 'path');
    const content = payload.content;
    if (typeof content !== 'string') {
      throw Errors.BadRequest('content is required');
    }
    const metadata = payload.metadata;
    if (
      metadata !== undefined &&
      metadata !== null &&
      (typeof metadata !== 'object' || Array.isArray(metadata))
    ) {
      throw Errors.BadRequest('metadata must be an object');
    }

    const data = await controller.writeFile(
      path,
      content,
      {
        metadata: metadata as Record<string, unknown> | undefined,
        embed: optionalBoolean(payload, 'embed'),
        idempotencyKey: optionalNonEmptyString(payload, 'idempotency_key'),
        provenanceId: optionalNonEmptyString(payload, 'provenance_id'),
        sourceAgent: optionalNonEmptyString(payload, 'source_agent'),
      }
    );
    const syncPending =
      typeof data === 'object' &&
      data !== null &&
      (data as Record<string, unknown>).sync_pending === true;
    res.status(syncPending ? 202 : 200).json({
      success: true,
      data,
      message: syncPending
        ? 'Memory write accepted; projection pending'
        : 'Memory write synchronized',
    });
  })
);

router.post(
  '/search',
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const query = requireString(payload, 'query');
    const path = optionalString(payload, 'path');
    const limit = optionalLimit(payload);
    const tags = optionalTags(payload);

    const data = await controller.search(query, { path, tags, limit });
    res.json({ success: true, data });
  })
);

router.post(
  '/list',
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const path = optionalString(payload, 'path');
    const data = await controller.listFiles(path);
    res.json({ success: true, data });
  })
);

router.post(
  '/delete',
  asyncHandler(async (req: Request, res: Response) => {
    const payload = requestBody(req);
    const path = requireString(payload, 'path');
    const data = await controller.deleteFile(path);
    res.json({ success: true, data });
  })
);

export default router;
