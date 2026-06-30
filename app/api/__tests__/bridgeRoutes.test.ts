import { Server } from 'http';
import request from 'supertest';
import { z } from 'zod';

import { app } from '../index';
import { callBridge } from '../lib/pythonBridge';

jest.mock('../lib/pythonBridge', () => ({
  callBridge: jest.fn(),
}));

const mockedCallBridge = callBridge as jest.MockedFunction<typeof callBridge>;

const agentRecord = z
  .object({
    name: z.string(),
    capabilities: z.array(z.string()).optional(),
    status: z.string().optional(),
  })
  .passthrough();

const successEnvelope = <T extends z.ZodTypeAny>(data: T) => {
    return z
        .object({
            success: z.literal(true),
            data,
        })
        .passthrough();
};
export default successEnvelope;

const routeSchemas = {
  agent: successEnvelope(agentRecord),
  agentList: successEnvelope(z.array(agentRecord)),
  deleteResult: successEnvelope(
    z.object({ name: z.string(), deleted: z.boolean() }).passthrough()
  ),
  memoryStats: successEnvelope(
    z
      .object({
        status: z.string(),
        note_count: z.number(),
        vector_count: z.number(),
      })
      .passthrough()
  ),
  memoryDelete: successEnvelope(
    z.object({ status: z.string(), path: z.string(), deleted: z.boolean() })
  ),
  stringList: (key: string) =>
    successEnvelope(z.object({ [key]: z.array(z.string()) })),
  atpTemplate: successEnvelope(z.object({ template: z.string() })),
  atpQueued: successEnvelope(
    z.object({ message_id: z.string(), status: z.string() }).passthrough()
  ),
  atpRoute: successEnvelope(
    z
      .object({
        route: z.object({ agent_name: z.string().nullable() }).passthrough(),
      })
      .passthrough()
  ),
  atpRecord: successEnvelope(
    z.object({ message_id: z.string(), status: z.string() }).passthrough()
  ),
  atpQueue: successEnvelope(
    z.object({ total: z.number(), messages: z.array(z.unknown()) }).passthrough()
  ),
  trustScore: successEnvelope(
    z
      .object({
        entity_id: z.string(),
        score: z.number(),
        level: z.string(),
      })
      .passthrough()
  ),
  trustPermissions: successEnvelope(
    z
      .object({
        entity_id: z.string(),
        permissions: z.array(z.string()),
      })
      .passthrough()
  ),
  trustAllowed: successEnvelope(
    z.object({ entity_id: z.string(), operation: z.string(), allowed: z.boolean() })
  ),
  trustLevels: successEnvelope(
    z.object({ levels: z.array(z.object({ level: z.string() }).passthrough()) })
  ),
  trustReport: successEnvelope(
    z.object({ total_entities: z.number(), by_level: z.record(z.string(), z.array(z.unknown())) })
  ),
  hebbian: successEnvelope(
    z
      .object({
        summary: z.object({ total_connections: z.number() }).passthrough(),
        connections: z.array(z.object({ origin_node: z.string() }).passthrough()),
      })
      .passthrough()
  ),
  hebbianUpdate: successEnvelope(
    z.object({ origin_node: z.string(), target_node: z.string(), weight: z.number() }).passthrough()
  ),
};

function bridgeResponse(command: string): unknown {
  switch (command) {
    case 'registry.list_agents':
      return {
        agents: [{ name: 'Alpha', capabilities: ['llm_chat'], status: 'active' }],
        total: 1,
      };
    case 'registry.get_agent':
    case 'registry.register_agent':
    case 'registry.update_agent':
    case 'registry.set_agent_status':
      return { name: 'Alpha', capabilities: ['llm_chat'], status: 'active' };
    case 'registry.delete_agent':
      return { name: 'Alpha', deleted: true };
    case 'memory.stats':
      return { status: 'success', path: '', note_count: 1, total_bytes: 10, vector_count: 1 };
    case 'memory.delete':
      return { status: 'success', path: 'notes/a.md', deleted: true };
    case 'atp.send':
      return { message_id: 'msg-1', status: 'queued' };
    case 'atp.route':
      return { route: { agent_name: 'Alpha' } };
    case 'atp.modes':
      return { modes: ['Build', 'Review'] };
    case 'atp.priorities':
      return { priorities: ['Normal', 'High'] };
    case 'atp.action_types':
      return { action_types: ['Execute', 'Summarize'] };
    case 'atp.template':
      return { template: '#Mode: Build\n#Priority: Normal\n' };
    case 'atp.format':
      return { formatted: '#Mode: Build\n', parsed: { mode: 'Build' } };
    case 'atp.get_message':
      return { message_id: 'msg-1', status: 'queued' };
    case 'atp.get_response':
      return { message_id: 'msg-1', status: 'routed', response: null, route: null };
    case 'atp.queue':
      return { total: 1, counts: { queued: 1 }, messages: [{ message_id: 'msg-1' }] };
    case 'trust.get_score':
    case 'trust.set_score':
    case 'trust.record_success':
    case 'trust.record_failure':
      return { entity_id: 'Alpha', entity_type: 'agent', score: 0.9, level: 'full' };
    case 'trust.permissions':
      return { entity_id: 'Alpha', permissions: ['read', 'write'] };
    case 'trust.can_perform':
      return { entity_id: 'Alpha', operation: 'read', allowed: true };
    case 'trust.levels':
      return { levels: [{ level: 'full', threshold: 0.9 }] };
    case 'trust.report':
      return { total_entities: 1, by_level: { full: [] }, timestamp: '2026-06-17T00:00:00Z' };
    case 'hebbian.weights':
      return {
        summary: { total_connections: 1 },
        connections: [{ origin_node: 'Alpha', target_node: 'task', weight: 1 }],
      };
    case 'hebbian.update':
      return { origin_node: 'Alpha', target_node: 'task', weight: 2 };
    default:
      throw new Error(`Unhandled bridge command in test: ${command}`);
  }
}

beforeEach(() => {
  mockedCallBridge.mockImplementation(async (command) => bridgeResponse(command));
});

let server: Server;
let logSpy: jest.SpiedFunction<typeof console.log>;
let warnSpy: jest.SpiedFunction<typeof console.warn>;

beforeAll((done) => {
  logSpy = jest.spyOn(console, 'log').mockImplementation(() => undefined);
  warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
  server = app.listen(0, '127.0.0.1', done);
});

afterAll((done) => {
  server.close(() => {
    logSpy.mockRestore();
    warnSpy.mockRestore();
    done();
  });
});

type RouteCase = {
  name: string;
  method: 'get' | 'post' | 'put' | 'delete';
  path: string;
  command: string;
  body?: Record<string, unknown>;
  schema: z.ZodTypeAny;
};

const bridgeRouteCases: RouteCase[] = [
  {
    name: 'lists agents',
    method: 'get',
    path: '/api/v1/agents',
    command: 'registry.list_agents',
    schema: routeSchemas.agentList,
  },
  {
    name: 'registers agents',
    method: 'post',
    path: '/api/v1/agents',
    body: { name: 'Alpha', capabilities: ['llm_chat'] },
    command: 'registry.register_agent',
    schema: routeSchemas.agent,
  },
  {
    name: 'updates agents',
    method: 'put',
    path: '/api/v1/agents/Alpha',
    body: { capabilities: ['reasoning'] },
    command: 'registry.update_agent',
    schema: routeSchemas.agent,
  },
  {
    name: 'deletes agents',
    method: 'delete',
    path: '/api/v1/agents/Alpha',
    command: 'registry.delete_agent',
    schema: routeSchemas.deleteResult,
  },
  {
    name: 'suspends agents',
    method: 'post',
    path: '/api/v1/agents/Alpha/suspend',
    body: { reason: 'test' },
    command: 'registry.set_agent_status',
    schema: routeSchemas.agent,
  },
  {
    name: 'activates agents',
    method: 'post',
    path: '/api/v1/agents/Alpha/activate',
    command: 'registry.set_agent_status',
    schema: routeSchemas.agent,
  },
  {
    name: 'returns memory stats',
    method: 'get',
    path: '/api/v1/memory/stats',
    command: 'memory.stats',
    schema: routeSchemas.memoryStats,
  },
  {
    name: 'deletes memory notes',
    method: 'post',
    path: '/api/v1/memory/delete',
    body: { path: 'notes/a.md' },
    command: 'memory.delete',
    schema: routeSchemas.memoryDelete,
  },
  {
    name: 'queues ATP messages',
    method: 'post',
    path: '/api/v1/atp/send',
    body: { message: '#Mode: Build\nBuild it.' },
    command: 'atp.send',
    schema: routeSchemas.atpQueued,
  },
  {
    name: 'routes ATP messages',
    method: 'post',
    path: '/api/v1/atp/route',
    body: { message: '#Mode: Build\nBuild it.' },
    command: 'atp.route',
    schema: routeSchemas.atpRoute,
  },
  {
    name: 'lists ATP modes',
    method: 'get',
    path: '/api/v1/atp/modes',
    command: 'atp.modes',
    schema: routeSchemas.stringList('modes'),
  },
  {
    name: 'lists ATP priorities',
    method: 'get',
    path: '/api/v1/atp/priorities',
    command: 'atp.priorities',
    schema: routeSchemas.stringList('priorities'),
  },
  {
    name: 'lists ATP action types',
    method: 'get',
    path: '/api/v1/atp/action-types',
    command: 'atp.action_types',
    schema: routeSchemas.stringList('action_types'),
  },
  {
    name: 'returns ATP template',
    method: 'get',
    path: '/api/v1/atp/template',
    command: 'atp.template',
    schema: routeSchemas.atpTemplate,
  },
  {
    name: 'formats ATP messages',
    method: 'post',
    path: '/api/v1/atp/format',
    body: { mode: 'Build', content: 'Build it.' },
    command: 'atp.format',
    schema: successEnvelope(z.object({ formatted: z.string() }).passthrough()),
  },
  {
    name: 'gets ATP messages',
    method: 'get',
    path: '/api/v1/atp/message/msg-1',
    command: 'atp.get_message',
    schema: routeSchemas.atpRecord,
  },
  {
    name: 'gets ATP responses',
    method: 'get',
    path: '/api/v1/atp/response/msg-1',
    command: 'atp.get_response',
    schema: routeSchemas.atpRecord,
  },
  {
    name: 'gets ATP queue',
    method: 'get',
    path: '/api/v1/atp/queue',
    command: 'atp.queue',
    schema: routeSchemas.atpQueue,
  },
  {
    name: 'reads Hebbian weights before parameter routes',
    method: 'get',
    path: '/api/v1/trust/hebbian/weights',
    command: 'hebbian.weights',
    schema: routeSchemas.hebbian,
  },
  {
    name: 'updates Hebbian weights',
    method: 'put',
    path: '/api/v1/trust/hebbian/weights',
    body: { agent1: 'Alpha', agent2: 'task', delta: 1 },
    command: 'hebbian.update',
    schema: routeSchemas.hebbianUpdate,
  },
  {
    name: 'lists trust levels',
    method: 'get',
    path: '/api/v1/trust/levels',
    command: 'trust.levels',
    schema: routeSchemas.trustLevels,
  },
  {
    name: 'returns trust report',
    method: 'get',
    path: '/api/v1/trust/report',
    command: 'trust.report',
    schema: routeSchemas.trustReport,
  },
  {
    name: 'reads trust score',
    method: 'get',
    path: '/api/v1/trust/Alpha',
    command: 'trust.get_score',
    schema: routeSchemas.trustScore,
  },
  {
    name: 'sets trust score',
    method: 'put',
    path: '/api/v1/trust/Alpha',
    body: { score: 0.9 },
    command: 'trust.set_score',
    schema: routeSchemas.trustScore,
  },
  {
    name: 'records trust success',
    method: 'post',
    path: '/api/v1/trust/Alpha/success',
    body: { amount: 0.02 },
    command: 'trust.record_success',
    schema: routeSchemas.trustScore,
  },
  {
    name: 'records trust failure',
    method: 'post',
    path: '/api/v1/trust/Alpha/failure',
    body: { amount: 0.02 },
    command: 'trust.record_failure',
    schema: routeSchemas.trustScore,
  },
  {
    name: 'gets trust permissions',
    method: 'get',
    path: '/api/v1/trust/Alpha/permissions',
    command: 'trust.permissions',
    schema: routeSchemas.trustPermissions,
  },
  {
    name: 'checks trust operation permission',
    method: 'post',
    path: '/api/v1/trust/Alpha/can-perform',
    body: { operation: 'read' },
    command: 'trust.can_perform',
    schema: routeSchemas.trustAllowed,
  },
];

describe('bridge-backed Express routes', () => {
  it.each(bridgeRouteCases)('$name via $command', async (testCase) => {
    let req = request(server)[testCase.method](testCase.path);
    if (testCase.body) {
      req = req.send(testCase.body);
    }

    const res = await req.expect(200);

    testCase.schema.parse(res.body);
    expect(mockedCallBridge.mock.calls.some(([command]) => command === testCase.command)).toBe(true);
  });
});
