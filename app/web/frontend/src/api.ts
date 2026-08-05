/**
 * API Client for MCP Dashboard
 *
 * Provides functions to interact with the MCP backend API.
 * All endpoints are proxied through Vite dev server during development.
 *
 * @module api
 */

/** Base URL for API endpoints (proxied by Vite in development) */
const API_BASE_URL = '/api';

/**
 * Resolved API key for `X-API-Key`. Reads `FASTAPI_API_KEY` first (the
 * canonical name `setup_secrets.sh` writes into the root `.env` that
 * vite.config.ts exposes via `envDir`/`envPrefix`), falling back to
 * `MCP_API_KEY` for shared-key setups. The `VITE_*` aliases let projects
 * keep dashboard-only overrides in `app/web/frontend/.env` without
 * touching the root .env. Empty in local dev with no `.env` configured
 * is fine — the FastAPI auth dependency is permissive in that case
 * (see `_require_api_key` in app/api/main.py).
 */
const runtimeEnv = (import.meta as ImportMeta & {
  env?: Record<string, string | undefined>;
}).env ?? {};

const API_KEY =
  runtimeEnv.FASTAPI_API_KEY ||
  runtimeEnv.MCP_API_KEY ||
  runtimeEnv.VITE_FASTAPI_API_KEY ||
  runtimeEnv.VITE_MCP_API_KEY ||
  '';

export type ApiRequestOptions = Pick<RequestInit, 'signal' | 'headers'>;

export interface AgentSummary {
  name: string;
  capabilities: string[];
}

export interface TaskRecord {
  relative_path: string;
  task_id: string;
  agent: string;
  status: string;
  title: string;
  required_capability?: string;
  context?: string;
  keywords?: string;
  target?: string;
  subtasks?: Array<{ text: string; completed: boolean }> | null;
}

export interface ReportSummary {
  filename: string;
  agent: string;
  task_id: string;
  timestamp: string;
}

export interface ReportContent {
  filename: string;
  content: string;
}

export interface RunSummary {
  run_id: string;
  start_time: string;
  end_time: string;
  total_events: number;
}

export interface RunEvent {
  run_id?: string;
  timestamp: string;
  event_type: string;
  component: string;
  message: string;
  metadata: Record<string, unknown>;
  duration_ms: number | null;
  prov_id: string | null;
  parent_prov_id: string | null;
}

export interface AgentScore {
  name: string;
  capabilities: string[];
  alignment: number;
  accuracy: number;
  efficiency: number;
  composite_score: number;
  [key: string]: unknown;
}

export interface HebbianStats {
  total_connections: number;
  avg_weight: number;
  max_weight: number;
  total_activations: number;
  total_successes: number;
  success_rate: number;
}

export interface HebbianConnection {
  origin_node: string;
  target_node: string;
  weight: number;
  activation_count: number;
  success_count: number;
  failure_count: number;
  success_rate: number;
}

export interface VectorStoreStats {
  total_docs: number;
  avg_content_length: number;
}

export interface VectorRecord {
  doc_id?: string;
  metadata?: unknown;
  content?: string | null;
  [key: string]: unknown;
}

export interface TaskActivity {
  task_id: string;
  task: TaskRecord | null;
  status: string | null;
  provenance_id: string | null;
  agent_name: string | null;
  capability: string | null;
  routing: Record<string, unknown> | null;
  provider: string | null;
  outcome_class: string | null;
  learning_eligible: boolean | null;
  reports: ReportSummary[];
  events: RunEvent[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly retryable: boolean;

  constructor(status: number, message: string, retryable = status >= 500 || status === 429) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryable = retryable;
  }
}

export const apiErrorMessageForStatus = (status: number): string => {
  if (status === 401) return 'You are not authorized to access this dashboard resource.';
  if (status === 403) return 'You do not have permission to access this dashboard resource.';
  if (status === 404) return 'The requested dashboard resource was not found.';
  if (status === 409) return 'The resource changed before the request completed. Refresh and try again.';
  if (status === 429) return 'The dashboard is temporarily busy. Try again shortly.';
  if (status >= 500) return 'The dashboard service could not complete the request. Try again.';
  return 'The dashboard request could not be completed.';
};

export const isAbortError = (error: unknown): boolean =>
  error instanceof DOMException
    ? error.name === 'AbortError'
    : typeof error === 'object' && error !== null && 'name' in error
      ? (error as { name?: unknown }).name === 'AbortError'
      : false;

/** Convert transport failures into copy that is safe to render in the UI. */
export const getUserFacingErrorMessage = (
  error: unknown,
  fallback = 'The dashboard could not load this data. Try again.'
): string => {
  if (isAbortError(error)) return '';
  if (error instanceof ApiError) return error.message;
  return fallback;
};

/**
 * Internal fetch wrapper that:
 *  - prepends `API_BASE_URL` to the path,
 *  - injects the `X-API-Key` header when configured,
 *  - throws on non-2xx, and
 *  - returns the parsed JSON response.
 *
 * @param path - Path under `/api` (must start with `/`)
 * @param init - Optional fetch init (method, headers, body)
 * @returns Parsed JSON response
 */
const apiFetch = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  const headers = new Headers(init.headers);
  if (API_KEY && !headers.has('X-API-Key')) {
    headers.set('X-API-Key', API_KEY);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new ApiError(response.status, apiErrorMessageForStatus(response.status));
  }
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(502, 'The dashboard returned an invalid response.', true);
  }
};

const jsonPost = <T>(
  path: string,
  body?: unknown,
  options: ApiRequestOptions = {}
): Promise<T> => {
  const headers = new Headers(options.headers);
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  return apiFetch<T>(path, {
    ...options,
    method: 'POST',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
};

/**
 * Fetch all registered agents from the MCP server.
 *
 * @returns Promise resolving to an array of agent objects
 * @throws Error if the request fails
 */
export const fetchAgents = (options?: ApiRequestOptions) =>
  apiFetch<AgentSummary[]>('/agents', options);

/**
 * Fetch all tasks from the Obsidian vault.
 *
 * @returns Promise resolving to an array of task objects
 * @throws Error if the request fails
 */
export const fetchTasks = (options?: ApiRequestOptions) =>
  apiFetch<TaskRecord[]>('/tasks', options);

/**
 * Fetch one task by its server-issued identifier.
 *
 * The backend resolves the identifier against parsed task metadata so this
 * call remains valid after a task leaves the pending execution queue.
 */
export const fetchTask = (taskId: string, options?: ApiRequestOptions) =>
  apiFetch<TaskRecord>(`/tasks/${encodeURIComponent(taskId)}`, options);

/**
 * Create a new task in the Obsidian vault.
 *
 * @param taskData - Task data including agent, title, context, and keywords
 * @returns Promise resolving to the created task object
 * @throws Error if the request fails
 */
export const createNewTask = (taskData: unknown, options?: ApiRequestOptions) =>
  jsonPost<{ task_id?: string }>('/tasks', taskData, options);

/**
 * Fetch all available reports from the MCP server.
 *
 * @returns Promise resolving to an array of report summary objects
 * @throws Error if the request fails
 */
export const fetchReports = (options?: ApiRequestOptions) =>
  apiFetch<ReportSummary[]>('/reports', options);

/**
 * Fetch the content of a specific report.
 *
 * @param filename - Name of the report file to fetch
 * @returns Promise resolving to the report content object
 * @throws Error if the request fails
 */
export const fetchReportContent = (filename: string, options?: ApiRequestOptions) =>
  apiFetch<ReportContent>(`/reports/${encodeURIComponent(filename)}`, options);

/**
 * Execute a single pending task by its relative path.
 *
 * @param relativePath - Path to the task file in the Obsidian vault
 * @returns Promise resolving to the execution result
 * @throws Error if the request fails
 */
export const executePendingTask = (relativePath: string, options?: ApiRequestOptions) =>
  jsonPost<{ message: string; results?: Record<string, unknown> }>(
    '/execute-task',
    { relative_path: relativePath },
    options
  );

/**
 * Execute all pending tasks in batch.
 *
 * @returns Promise resolving to a summary with completed, failed, and skipped counts
 * @throws Error if the request fails
 */
export const executeAllPendingTasks = (options?: ApiRequestOptions) =>
  jsonPost<Record<string, unknown>>('/execute-all-pending', undefined, options);

/**
 * Fetch all agent scores with performance metrics.
 *
 * @returns Promise resolving to an array of agent score objects
 * @throws Error if the request fails
 */
export const fetchAgentScores = (options?: ApiRequestOptions) =>
  apiFetch<AgentScore[]>('/db/agents', options);

/**
 * Fetch Hebbian network statistics.
 *
 * @returns Promise resolving to network stats (connections, weights, activation counts)
 * @throws Error if the request fails
 */
export const fetchHebbianStats = (options?: ApiRequestOptions) =>
  apiFetch<HebbianStats>('/db/hebbian/stats', options);

/**
 * Fetch top Hebbian network connections.
 *
 * @param limit - Maximum number of connections to return (default: 50)
 * @returns Promise resolving to an array of connection objects
 * @throws Error if the request fails
 */
export const fetchHebbianConnections = (limit: number = 50, options?: ApiRequestOptions) =>
  apiFetch<HebbianConnection[]>(`/db/hebbian/connections?limit=${limit}`, options);

/**
 * Fetch Hebbian statistics for a specific agent.
 *
 * @param agentName - Name of the agent to query
 * @returns Promise resolving to agent-specific Hebbian stats
 * @throws Error if the request fails
 */
export const fetchAgentHebbianStats = (agentName: string, options?: ApiRequestOptions) =>
  apiFetch<Record<string, unknown>>(
    `/db/hebbian/agent/${encodeURIComponent(agentName)}`,
    options
  );

/**
 * Fetch vector store statistics.
 *
 * @returns Promise resolving to vector stats (total Documents, avg length)
 * @throws Error if the request fails
 */
export const fetchVectorStats = (options?: ApiRequestOptions) =>
  apiFetch<VectorStoreStats>('/db/vectors/stats', options);

/**
 * Fetch paginated vectors from the vector store.
 *
 * @param limit - Maximum number of vectors to return (default: 100)
 * @param offset - Number of vectors to skip (default: 0)
 * @returns Promise resolving to an array of vector objects
 * @throws Error if the request fails
 */
export const fetchVectors = (
  limit: number = 100,
  offset: number = 0,
  options?: ApiRequestOptions
) =>
  apiFetch<VectorRecord[]>(`/db/vectors/list?limit=${limit}&offset=${offset}`, options);

/**
 * Fetch recent run summaries from the run logs.
 *
 * @param limit - Maximum number of runs to return (default: 20)
 * @returns Promise resolving to an array of run summary objects
 * @throws Error if the request fails
 */
export const fetchRuns = (limit: number = 20, options?: ApiRequestOptions) =>
  apiFetch<RunSummary[]>(`/db/runs?limit=${limit}`, options);

/**
 * Fetch events for a specific run.
 *
 * @param runId - ID of the run to query
 * @param eventType - Optional event type filter
 * @returns Promise resolving to an array of event objects
 * @throws Error if the request fails
 */
export const fetchRunEvents = (
  runId: string,
  eventType?: string,
  options?: ApiRequestOptions
) => {
  const qs = eventType ? `?event_type=${encodeURIComponent(eventType)}` : '';
  return apiFetch<RunEvent[]>(`/db/runs/${encodeURIComponent(runId)}/events${qs}`, options);
};

/** Fetch the governed, read-only activity trail for one server-issued task ID. */
export const fetchTaskActivity = (
  taskId: string,
  limit = 200,
  options?: ApiRequestOptions
) =>
  apiFetch<TaskActivity>(
    `/tasks/${encodeURIComponent(taskId)}/activity?limit=${limit}`,
    options
  );

/**
 * Execute a CLI-style instruction through the executor.
 *
 * @param data - Execution request data (instruction, optional agent, capability, title)
 * @returns Promise resolving to execution result (task_id, status, summary, note_path, error)
 * @throws Error if the request fails
 */
export const executeInstruction = (data: {
  instruction: string;
  capability?: string;
  agent?: string;
  title?: string;
  atp_strict?: boolean;
}, options?: ApiRequestOptions) =>
  jsonPost<ExecuteInstructionResult>('/cli/execute', data, options);

export interface ExecuteInstructionResult {
  task_id: string;
  status: string;
  summary: string;
  note_path: string | null;
  error: string | null;
  agent_name: string | null;
  routing: Record<string, any> | null;
  atp: Record<string, unknown> | null;
  provenance_id: string | null;
  provider: string | null;
  fallback_used: boolean | null;
  model: string | null;
  outcome_class: string | null;
  learning_eligible: boolean | null;
  exo_request: Record<string, unknown> | null;
  compressed_context: string | null;
  output_compression: Record<string, unknown> | null;
}

/**
 * Handlers invoked as the streaming executor emits SSE events. Each is
 * optional so callers only wire up what they care about. ``abort`` lets
 * the consumer cancel the in-flight stream mid-flight.
 */
export interface ExecuteStreamHandlers {
  onRouting?: (data: {
    decision: unknown;
    agent_name: string;
    task_id: string;
    atp: Record<string, unknown> | null;
    provenance_id: string | null;
  }) => void;
  onToken?: (text: string) => void;
  onComplete?: (data: {
    task_id: string;
    agent_name: string;
    status: string;
    summary: string;
    note_path: string | null;
    error: string | null;
    atp: Record<string, unknown> | null;
    provenance_id: string | null;
    provider: string | null;
    fallback_used: boolean | null;
    model: string | null;
    outcome_class: string | null;
    learning_eligible: boolean | null;
    exo_request: Record<string, unknown> | null;
    compressed_context: string | null;
    output_compression: Record<string, unknown> | null;
  }) => void;
  onError?: (message: string) => void;
}

/**
 * Execute a CLI-style instruction and stream the response over SSE.
 *
 * The fetch-based SSE consumer is preferred over EventSource because we
 * need to POST the request body (EventSource is GET-only) and inject
 * ``X-API-Key`` for the FastAPI auth dependency.
 *
 * Returns an abort controller — call ``.abort()`` to cancel the stream
 * delivery. The FastAPI worker still finalizes persistence and learning for
 * an already-dispatched task, while discarding further client frames.
 */
export const executeInstructionStream = (
  data: {
    instruction: string;
    capability?: string;
    agent?: string;
    title?: string;
    atp_strict?: boolean;
  },
  handlers: ExecuteStreamHandlers
): AbortController => {
  const controller = new AbortController();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  if (API_KEY) headers['X-API-Key'] = API_KEY;

  (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/cli/execute/stream`, {
        method: 'POST',
        headers,
        body: JSON.stringify(data),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        handlers.onError?.(
          apiErrorMessageForStatus(response.status || 502)
        );
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let terminalSeen = false;

      // Parse SSE: events are separated by a blank line; each frame may
      // contain "event: <name>" and one or more "data: <line>" lines.
      const flush = (raw: string) => {
        const lines = raw.split('\n');
        let event = 'message';
        const dataLines: string[] = [];
        for (const line of lines) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
        }
        if (dataLines.length === 0) return;
        let payload: any = dataLines.join('\n');
        try {
          payload = JSON.parse(payload);
        } catch {
          // leave as string
        }
        if (event === 'routing') handlers.onRouting?.(payload);
        else if (event === 'token') handlers.onToken?.(payload.text ?? '');
        else if (event === 'complete') {
          terminalSeen = true;
          handlers.onComplete?.(payload);
        } else if (event === 'error') {
          terminalSeen = true;
          handlers.onError?.('The dashboard could not complete the execution.');
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are terminated by "\n\n".
        let idx;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (frame.trim()) flush(frame);
        }
      }
      if (buffer.trim()) flush(buffer);
      if (!terminalSeen && !controller.signal.aborted) {
        handlers.onError?.('The execution stream ended before completion. Try again.');
      }
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      handlers.onError?.(
        getUserFacingErrorMessage(err, 'The dashboard could not complete the execution. Try again.')
      );
    }
  })();

  return controller;
};
