/**
 * Compatibility LLM controller backed by the authoritative Python bridge.
 *
 * The canonical public routes live in `app/api/v1/llm.ts`, but older route
 * modules still import this controller. Keeping the compatibility surface
 * bridge-backed prevents those modules from ever returning simulated model
 * text or random embeddings if they are accidentally mounted again.
 */

import { callBridge } from '../lib/pythonBridge';

export interface Message {
  role: 'system' | 'user' | 'assistant';
  content: string;
  name?: string;
}

export interface ChatOptions {
  temperature?: number;
  maxTokens?: number;
  topP?: number;
  stopSequences?: string[];
  systemPrompt?: string;
}

export interface LLMBridgeResult {
  status: 'success' | 'failed';
  summary: string;
  raw: string | null;
  provider: string | null;
  model: string | null;
  error: string | null;
  response_id?: string | null;
  usage?: Record<string, unknown>;
  exo_request: Record<string, unknown> | null;
  bridge_code?: string;
  [key: string]: unknown;
}

export interface StreamChunk {
  id: string;
  delta: string;
  finishReason?: string;
}

export interface ProviderConfig {
  name: string;
  enabled: boolean;
  apiKey?: string;
  baseUrl: string;
  defaultModel: string;
  apiKeyConfigured: boolean;
  source: 'environment';
  options?: Record<string, unknown>;
}

type LLMBridgeConfig = {
  source: 'configured';
  default_model: string;
  models: Array<Record<string, unknown>>;
  providers: Array<Record<string, unknown>>;
};

function unsupported(operation: string, replacement: string): never {
  throw new Error(
    `${operation} is not implemented by the production Exo bridge. Use ${replacement}.`
  );
}

/**
 * Backward-compatible controller that never synthesizes provider output.
 */
export class LLMController {
  async chat(
    messages: Message[],
    model?: string,
    options: ChatOptions = {}
  ): Promise<LLMBridgeResult> {
    const result = (await callBridge('llm.chat', {
      messages,
      model,
      options,
    })) as LLMBridgeResult;
    if (result.status === 'failed') {
      throw new Error(result.error || result.summary);
    }
    return result;
  }

  async complete(
    prompt: string,
    model?: string,
    options: ChatOptions = {}
  ): Promise<LLMBridgeResult> {
    const result = (await callBridge('llm.complete', {
      prompt,
      model,
      options,
    })) as LLMBridgeResult;
    if (result.status === 'failed') {
      throw new Error(result.error || result.summary);
    }
    return result;
  }

  async embed(_text: string | string[], _model?: string): Promise<never> {
    return unsupported('Embedding generation', 'the Python memory/vector API');
  }

  /**
   * Compatibility-only one-frame delivery of a real bridge result.
   * Canonical token streaming is `/api/cli/execute/stream` in FastAPI.
   */
  async streamChat(
    messages: Message[],
    model?: string,
    options: ChatOptions = {},
    onChunk: (chunk: StreamChunk) => void = () => {}
  ): Promise<void> {
    const result = await this.chat(messages, model, options);
    if (result.status === 'failed') {
      throw new Error(result.error || result.summary);
    }
    const requestId = String(
      result.response_id || result.exo_request?.request_id || 'exo-response'
    );
    onChunk({ id: requestId, delta: result.summary, finishReason: 'stop' });
  }

  async listModels(): Promise<Array<Record<string, unknown>>> {
    const config = (await callBridge('llm.config', {})) as LLMBridgeConfig;
    return config.models;
  }

  /** Return only environment-backed Exo configuration; never expose secrets. */
  getProviders(): ProviderConfig[] {
    const baseUrl =
      process.env.EXO_MODEL_URL ||
      process.env.EXO_BASE_URL ||
      'http://localhost:52415/v1';
    const normalizedBaseUrl = baseUrl.includes('/v1')
      ? `${baseUrl.split('/v1')[0]}/v1`
      : `${baseUrl.replace(/\/$/, '')}/v1`;
    return [
      {
        name: 'Exo',
        enabled: true,
        baseUrl: normalizedBaseUrl,
        defaultModel:
          process.env.EXO_MODEL_ID || 'mlx-community/Qwen3-0.6B-4bit',
        apiKeyConfigured: Boolean(process.env.EXO_API_KEY?.trim()),
        source: 'environment',
      },
    ];
  }

  async configureProvider(
    _providerName: string,
    _config: Partial<ProviderConfig>
  ): Promise<never> {
    return unsupported('Runtime provider mutation', 'EXO_* environment settings');
  }

  async processATP(
    _atpMessage: unknown,
    _model?: string,
    _agentId?: string
  ): Promise<never> {
    return unsupported('Direct LLM ATP processing', 'the governed ATP executor');
  }

  async getUsage(_filters: Record<string, unknown> = {}): Promise<never> {
    return unsupported('In-memory usage estimates', 'run-log metrics');
  }
}
