import express, {NextFunction, Request, Response} from 'express';
import request from 'supertest';

import {callBridge} from '../lib/pythonBridge';
import llmRoutes from '../v1/llm';

jest.mock('../lib/pythonBridge', () => ({
  callBridge: jest.fn(),
}));

jest.mock('../middleware/auth', () => ({
  authMiddleware: (_req: Request, _res: Response, next: NextFunction) => next(),
}));

const mockedCallBridge = callBridge as jest.MockedFunction<typeof callBridge>;

const successResult = {
  status: 'success',
  summary: 'Real Exo output',
  raw: 'Real Exo output',
  raw_output: 'Real Exo output',
  provider: 'exo',
  model: 'exo-model',
  error: null,
  exo_request: {
    request_id: 'req-1',
    http_status: 200,
    endpoint: 'http://exo.test:52415/v1/chat/completions',
  },
};

const configResult = {
  source: 'configured',
  default_model: 'exo-model',
  models: [
    {
      id: 'exo-model',
      name: 'exo-model',
      provider: 'exo',
      source: 'configured',
      running: null,
    },
  ],
  providers: [
    {
      id: 'exo',
      name: 'Exo',
      enabled: true,
      base_url: 'http://exo.test:52415/v1',
      api_key_configured: false,
      source: 'environment',
    },
  ],
};

const app = express();
app.use(express.json());
app.use('/api/v1/llm', llmRoutes);

beforeEach(() => {
  mockedCallBridge.mockReset();
});

describe('canonical bridge-backed LLM routes', () => {
  it('sends chat to the real Python LLM command', async () => {
    mockedCallBridge.mockResolvedValue(successResult);

    const response = await request(app)
      .post('/api/v1/llm/chat')
      .send({
        messages: [{role: 'user', content: 'Hello'}],
        model: 'exo-model',
        options: {temperature: 0.2, maxTokens: 64},
      })
      .expect(200);

    expect(mockedCallBridge).toHaveBeenCalledWith('llm.chat', {
      messages: [{role: 'user', content: 'Hello'}],
      model: 'exo-model',
      options: {temperature: 0.2, maxTokens: 64},
    });
    expect(response.body).toEqual({success: true, data: successResult});
  });

  it('sends completion prompts to the real Python LLM command', async () => {
    mockedCallBridge.mockResolvedValue(successResult);

    const response = await request(app)
      .post('/api/v1/llm/complete')
      .send({prompt: 'Complete this', options: {maxTokens: 32}})
      .expect(200);

    expect(mockedCallBridge).toHaveBeenCalledWith('llm.complete', {
      prompt: 'Complete this',
      model: undefined,
      options: {maxTokens: 32},
    });
    expect(response.body.data.exo_request.request_id).toBe('req-1');
    expect(response.body.data.raw).toBe('Real Exo output');
  });

  it.each([
    ['RATE_LIMITED', 429],
    ['TIMEOUT', 504],
    ['SERVICE_UNAVAILABLE', 503],
    ['PROVIDER_ERROR', 502],
  ])('maps %s provider evidence to HTTP %i', async (bridgeCode, httpStatus) => {
    const failureResult = {
      ...successResult,
      status: 'failed',
      summary: 'Exo is unavailable',
      raw: null,
      provider: 'exo',
      fallback_used: false,
      error: 'Exo is unavailable',
      bridge_code: bridgeCode,
      retry_after_seconds: bridgeCode === 'RATE_LIMITED' ? 7 : null,
    };
    mockedCallBridge.mockResolvedValue(failureResult);

    const response = await request(app)
      .post('/api/v1/llm/chat')
      .send({messages: [{role: 'user', content: 'Hello'}]})
      .expect(httpStatus);

    expect(response.body).toEqual({
      success: false,
      error: 'Exo is unavailable',
      code: bridgeCode,
      data: failureResult,
    });
    if (bridgeCode === 'RATE_LIMITED') {
      expect(response.headers['retry-after']).toBe('7');
    }
  });

  it('preserves bridge validation status and code', async () => {
    mockedCallBridge.mockRejectedValue(
      Object.assign(new Error('temperature must be between 0.0 and 2.0'), {
        statusCode: 400,
        code: 'INVALID_REQUEST',
      })
    );

    const response = await request(app)
      .post('/api/v1/llm/chat')
      .send({messages: [{role: 'user', content: 'Hello'}]})
      .expect(400);

    expect(response.body).toEqual({
      success: false,
      error: 'temperature must be between 0.0 and 2.0',
      code: 'INVALID_REQUEST',
    });
  });

  it('does not synthesize a stream and directs callers to FastAPI', async () => {
    const response = await request(app)
      .post('/api/v1/llm/stream')
      .send({messages: [{role: 'user', content: 'Hello'}]})
      .expect(501);

    expect(response.body).toEqual({
      success: false,
      error: 'Express LLM streaming is not implemented by the production Exo bridge.',
      code: 'NOT_IMPLEMENTED',
      replacement: '/api/cli/execute/stream',
    });
    expect(mockedCallBridge).not.toHaveBeenCalled();
  });

  it('lists configured models from Python rather than demo constants', async () => {
    mockedCallBridge.mockResolvedValue(configResult);

    const response = await request(app).get('/api/v1/llm/models').expect(200);

    expect(mockedCallBridge).toHaveBeenCalledWith('llm.config');
    expect(response.body).toEqual({
      success: true,
      data: configResult.models,
      source: 'configured',
      default_model: 'exo-model',
    });
  });

  it('lists environment-backed Exo provider state', async () => {
    mockedCallBridge.mockResolvedValue(configResult);

    const response = await request(app).get('/api/v1/llm/providers').expect(200);

    expect(mockedCallBridge).toHaveBeenCalledWith('llm.config');
    expect(response.body).toEqual({
      success: true,
      data: configResult.providers,
      source: 'configured',
    });
  });

  it('rejects whitespace-only completion prompts before spawning the bridge', async () => {
    const response = await request(app)
      .post('/api/v1/llm/complete')
      .send({prompt: '   '})
      .expect(400);

    expect(response.body).toEqual({
      success: false,
      error: 'prompt must be a non-empty string',
      code: 'INVALID_REQUEST',
    });
    expect(mockedCallBridge).not.toHaveBeenCalled();
  });

  it.each([
    ['post', '/api/v1/llm/embed'],
    ['post', '/api/v1/llm/provider'],
    ['post', '/api/v1/llm/atp'],
    ['get', '/api/v1/llm/usage'],
  ])('fails closed for unsupported demo operation %s %s', async (method, path) => {
    const response = await (method === 'get' ? request(app).get(path) : request(app).post(path));

    expect(response.status).toBe(501);
    expect(response.body.code).toBe('NOT_IMPLEMENTED');
    expect(mockedCallBridge).not.toHaveBeenCalled();
  });
});
