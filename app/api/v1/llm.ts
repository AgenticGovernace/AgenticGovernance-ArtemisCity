/**
 * LLM API Routes
 *
 * Endpoints for interacting with LLM providers (Claude, OpenAI, etc.)
 */

import {Request, Response, Router} from 'express';
import {LLMController} from '../controllers';
import {authMiddleware} from '../middleware/auth';

const router = Router();
const controller = new LLMController();
router.use(authMiddleware);

// Explicit allowlist of providers the controller actually knows about.
// The env-var name is derived from the provider string, so anything
// outside this list must be rejected before the process.env lookup --
// otherwise a request-controlled provider name could probe arbitrary
// `<NAME>_API_KEY` environment variables (js/remote-property-injection).
export const ALLOWED_PROVIDERS = new Set(['anthropic', 'openai', 'local']);

function resolveProviderApiKey(provider: string): string | undefined {
  const normalized = provider.trim().toLowerCase();
  if (!ALLOWED_PROVIDERS.has(normalized)) {
    return undefined;
  }
  const providerUpper = normalized.toUpperCase().replace(/[^A-Z0-9]/g, '_');

  const candidatesByProvider: Record<string, string[]> = {
    anthropic: ['ANTHROPIC_API_KEY', 'ARTEMIS_ANTHROPIC_API_KEY', 'CLAUDE_API_KEY'],
    openai: ['OPENAI_API_KEY', 'ARTEMIS_OPENAI_API_KEY'],
    local: [],
  };

  const providerCandidates = candidatesByProvider[normalized] ?? [];
  const genericCandidates = [
    `${providerUpper}_API_KEY`,
    `ARTEMIS_${providerUpper}_API_KEY`,
    'ARTEMIS_LLM_API_KEY',
  ];

  for (const keyName of [...providerCandidates, ...genericCandidates]) {
    const value = process.env[keyName];
    if (value && value.trim()) {
      return value.trim();
    }
  }

  return undefined;
}

/**
 * Strip `apiKey` from a provider config before serialization.
 *
 * `POST /provider` resolves the upstream LLM key from the server
 * environment (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...), then stores it
 * inside the LLMController's in-memory provider map so the chat path
 * can reuse it. Returning that full config to the caller -- whether via
 * the POST response or a later `GET /providers` -- would leak the
 * server-side env secret to anyone holding the dashboard's
 * X-API-Key. Replace the key with a sentinel and signal whether one is
 * configured upstream.
 */
type SerializableProvider = Record<string, unknown> & {
  apiKey?: undefined;
  apiKeyConfigured?: boolean;
};
function redactProvider<T extends { apiKey?: string }>(
  provider: T
): SerializableProvider {
  const { apiKey, ...rest } = provider;
  return {
    ...rest,
    apiKeyConfigured: typeof apiKey === 'string' && apiKey.length > 0,
  };
}

/**
 * POST /api/v1/llm/chat
 * Send a chat completion request
 */
router.post('/chat', async (req: Request, res: Response) => {
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
  } catch (error: any) {
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
router.post('/complete', async (req: Request, res: Response) => {
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
  } catch (error: any) {
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
router.post('/embed', async (req: Request, res: Response) => {
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
  } catch (error: any) {
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
router.post('/stream', async (req: Request, res: Response) => {
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
  } catch (error: any) {
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
router.get('/models', async (req: Request, res: Response) => {
  try {
    const models = await controller.listModels();
    res.json({
      success: true,
      data: models
    });
  } catch (error: any) {
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
router.get('/providers', (req: Request, res: Response) => {
  try {
    const providers = controller.getProviders().map(redactProvider);
    res.json({
      success: true,
      data: providers
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * POST /api/v1/llm/provider
 * Configure a provider using API keys loaded from environment variables
 */
router.post('/provider', async (req: Request, res: Response) => {
  try {
    const { provider, baseUrl, options } = req.body;

    if (!provider) {
      res.status(400).json({
        success: false,
        error: 'provider is required'
      });
      return;
    }

    const providerName = String(provider).trim().toLowerCase();
    if (!ALLOWED_PROVIDERS.has(providerName)) {
      res.status(400).json({
        success: false,
        error: `Unsupported provider. Allowed: ${[...ALLOWED_PROVIDERS].join(', ')}`
      });
      return;
    }
    const apiKeyFromEnv = resolveProviderApiKey(providerName);
    const isLocalProvider = providerName === 'local';

    if (!isLocalProvider && !apiKeyFromEnv) {
      res.status(400).json({
        success: false,
        error: `No API key configured in environment for provider '${providerName}'`
      });
      return;
    }

    // Strip any client-supplied apiKey so it cannot override the
    // env-resolved key after the spread. Same for baseUrl, which is
    // already taken from the top-level body field. Guard that `options`
    // is a plain object first -- req.body comes from arbitrary JSON, so
    // a client could send a string/number/array and the destructure
    // would otherwise iterate string indices or array elements.
    const optionsObj: Record<string, unknown> =
      options && typeof options === 'object' && !Array.isArray(options)
        ? (options as Record<string, unknown>)
        : {};
    const { apiKey: _strippedApiKey, baseUrl: _strippedBaseUrl, ...safeOptions } = optionsObj;
    void _strippedApiKey;
    void _strippedBaseUrl;
    const result = await controller.configureProvider(providerName, {
      ...safeOptions,
      apiKey: apiKeyFromEnv,
      baseUrl
    });
    res.json({
      success: true,
      data: redactProvider(result),
      message: `Provider ${providerName} configured successfully`
    });
  } catch (error: any) {
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
router.post('/atp', async (req: Request, res: Response) => {
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
  } catch (error: any) {
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
router.get('/usage', async (req: Request, res: Response) => {
  try {
    const { startDate, endDate, provider } = req.query;
    const usage = await controller.getUsage({
      startDate: startDate as string,
      endDate: endDate as string,
      provider: provider as string
    });
    res.json({
      success: true,
      data: usage
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

export default router;
