/**
 * Canonical LLM routes.
 *
 * Every supported inference call crosses the JSON bridge into the Python
 * LLMAgent. Unsupported demo-era operations fail explicitly; this module
 * never generates model text, embeddings, usage, or provider state locally.
 */

import { Request, Response, Router } from "express";

import { callBridge } from "../lib/pythonBridge";

const router = Router();

type LLMBridgeResult = {
  status: "success" | "failed";
  summary: string;
  raw: string | null;
  provider: string | null;
  model: string | null;
  error: string | null;
  exo_request: Record<string, unknown> | null;
  bridge_code?: string;
  upstream_status_code?: number | null;
  retry_after_seconds?: number | null;
  [key: string]: unknown;
};

type LLMBridgeConfig = {
  source: "configured";
  default_model: string;
  models: Array<Record<string, unknown>>;
  providers: Array<Record<string, unknown>>;
};

const PROVIDER_STATUS_BY_CODE: Record<string, number> = {
  RATE_LIMITED: 429,
  TIMEOUT: 504,
  SERVICE_UNAVAILABLE: 503,
  PROVIDER_ERROR: 502,
};

function sendBridgeFailure(res: Response, result: LLMBridgeResult): void {
  const code = result.bridge_code || "PROVIDER_ERROR";
  const statusCode = PROVIDER_STATUS_BY_CODE[code] || 502;
  const retryAfter = Number(result.retry_after_seconds);
  if (
    code === "RATE_LIMITED" &&
    Number.isFinite(retryAfter) &&
    retryAfter > 0
  ) {
    res.setHeader(
      "Retry-After",
      String(Math.min(86_400, Math.ceil(retryAfter))),
    );
  }
  res.status(statusCode).json({
    success: false,
    error: result.error || result.summary,
    code,
    data: result,
  });
}

function sendRouteError(res: Response, error: unknown): void {
  const candidate = error as {
    statusCode?: unknown;
    code?: unknown;
    message?: unknown;
  };
  const statusCode = Number.isInteger(candidate?.statusCode)
    ? Number(candidate.statusCode)
    : 500;
  const code =
    typeof candidate?.code === "string" ? candidate.code : "INTERNAL_ERROR";
  const message =
    typeof candidate?.message === "string"
      ? candidate.message
      : "LLM request failed";
  res.status(statusCode).json({ success: false, error: message, code });
}

function notImplemented(
  res: Response,
  operation: string,
  replacement: string,
): void {
  res.status(501).json({
    success: false,
    error: `${operation} is not implemented by the production Exo bridge.`,
    code: "NOT_IMPLEMENTED",
    replacement,
  });
}

router.post("/chat", async (req: Request, res: Response) => {
  try {
    const { messages, model, options } = req.body;
    if (!Array.isArray(messages) || messages.length === 0) {
      res.status(400).json({
        success: false,
        error: "messages must be a non-empty array",
        code: "INVALID_REQUEST",
      });
      return;
    }

    const result = (await callBridge("llm.chat", {
      messages,
      model,
      options,
    })) as LLMBridgeResult;
    if (result.status === "failed") {
      sendBridgeFailure(res, result);
      return;
    }
    res.json({ success: true, data: result });
  } catch (error: unknown) {
    sendRouteError(res, error);
  }
});

router.post("/complete", async (req: Request, res: Response) => {
  try {
    const { prompt, model, options } = req.body;
    if (typeof prompt !== "string" || !prompt.trim()) {
      res.status(400).json({
        success: false,
        error: "prompt must be a non-empty string",
        code: "INVALID_REQUEST",
      });
      return;
    }

    const result = (await callBridge("llm.complete", {
      prompt,
      model,
      options,
    })) as LLMBridgeResult;
    if (result.status === "failed") {
      sendBridgeFailure(res, result);
      return;
    }
    res.json({ success: true, data: result });
  } catch (error: unknown) {
    sendRouteError(res, error);
  }
});

router.post("/embed", (_req: Request, res: Response) => {
  notImplemented(res, "Embedding generation", "/api/v1/memory/write");
});

router.post("/stream", (_req: Request, res: Response) => {
  notImplemented(res, "Express LLM streaming", "/api/cli/execute/stream");
});

router.get("/models", async (_req: Request, res: Response) => {
  try {
    const config = (await callBridge("llm.config")) as LLMBridgeConfig;
    res.json({
      success: true,
      data: config.models,
      source: config.source,
      default_model: config.default_model,
    });
  } catch (error: unknown) {
    sendRouteError(res, error);
  }
});

router.get("/providers", async (_req: Request, res: Response) => {
  try {
    const config = (await callBridge("llm.config")) as LLMBridgeConfig;
    res.json({ success: true, data: config.providers, source: config.source });
  } catch (error: unknown) {
    sendRouteError(res, error);
  }
});

router.post("/provider", (_req: Request, res: Response) => {
  notImplemented(
    res,
    "Runtime provider mutation",
    "EXO_* environment settings",
  );
});

router.post("/atp", (_req: Request, res: Response) => {
  notImplemented(res, "Direct LLM ATP processing", "/api/v1/atp/route");
});

router.get("/usage", (_req: Request, res: Response) => {
  notImplemented(res, "In-memory usage estimates", "/api/db/runs");
});

export default router;
