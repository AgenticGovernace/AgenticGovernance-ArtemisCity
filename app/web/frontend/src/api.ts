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
const API_KEY =
  import.meta.env.FASTAPI_API_KEY ||
  import.meta.env.MCP_API_KEY ||
  import.meta.env.VITE_FASTAPI_API_KEY ||
  import.meta.env.VITE_MCP_API_KEY ||
  '';

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
const apiFetch = async (path: string, init: RequestInit = {}): Promise<any> => {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (API_KEY && !('X-API-Key' in headers)) {
    headers['X-API-Key'] = API_KEY;
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
};

const jsonPost = (path: string, body?: unknown): Promise<any> =>
  apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

/**
 * Fetch all registered agents from the MCP server.
 *
 * @returns Promise resolving to an array of agent objects
 * @throws Error if the request fails
 */
export const fetchAgents = () => apiFetch('/agents');

/**
 * Fetch all tasks from the Obsidian vault.
 *
 * @returns Promise resolving to an array of task objects
 * @throws Error if the request fails
 */
export const fetchTasks = () => apiFetch('/tasks');

/**
 * Create a new task in the Obsidian vault.
 *
 * @param taskData - Task data including agent, title, context, and keywords
 * @returns Promise resolving to the created task object
 * @throws Error if the request fails
 */
export const createNewTask = (taskData: any) => jsonPost('/tasks', taskData);

/**
 * Fetch all available reports from the MCP server.
 *
 * @returns Promise resolving to an array of report summary objects
 * @throws Error if the request fails
 */
export const fetchReports = () => apiFetch('/reports');

/**
 * Fetch the content of a specific report.
 *
 * @param filename - Name of the report file to fetch
 * @returns Promise resolving to the report content object
 * @throws Error if the request fails
 */
export const fetchReportContent = (filename: string) =>
  apiFetch(`/reports/${encodeURIComponent(filename)}`);

/**
 * Execute a single pending task by its relative path.
 *
 * @param relativePath - Path to the task file in the Obsidian vault
 * @returns Promise resolving to the execution result
 * @throws Error if the request fails
 */
export const executePendingTask = (relativePath: string) =>
  jsonPost('/execute-task', { relative_path: relativePath });

/**
 * Execute all pending tasks in batch.
 *
 * @returns Promise resolving to a summary with completed, failed, and skipped counts
 * @throws Error if the request fails
 */
export const executeAllPendingTasks = () => jsonPost('/execute-all-pending');

/**
 * Fetch all agent scores with performance metrics.
 *
 * @returns Promise resolving to an array of agent score objects
 * @throws Error if the request fails
 */
export const fetchAgentScores = () => apiFetch('/db/agents');

/**
 * Fetch Hebbian network statistics.
 *
 * @returns Promise resolving to network stats (connections, weights, activation counts)
 * @throws Error if the request fails
 */
export const fetchHebbianStats = () => apiFetch('/db/hebbian/stats');

/**
 * Fetch top Hebbian network connections.
 *
 * @param limit - Maximum number of connections to return (default: 50)
 * @returns Promise resolving to an array of connection objects
 * @throws Error if the request fails
 */
export const fetchHebbianConnections = (limit: number = 50) =>
  apiFetch(`/db/hebbian/connections?limit=${limit}`);

/**
 * Fetch Hebbian statistics for a specific agent.
 *
 * @param agentName - Name of the agent to query
 * @returns Promise resolving to agent-specific Hebbian stats
 * @throws Error if the request fails
 */
export const fetchAgentHebbianStats = (agentName: string) =>
  apiFetch(`/db/hebbian/agent/${encodeURIComponent(agentName)}`);

/**
 * Fetch vector store statistics.
 *
 * @returns Promise resolving to vector stats (total Documents, avg length)
 * @throws Error if the request fails
 */
export const fetchVectorStats = () => apiFetch('/db/vectors/stats');

/**
 * Fetch paginated vectors from the vector store.
 *
 * @param limit - Maximum number of vectors to return (default: 100)
 * @param offset - Number of vectors to skip (default: 0)
 * @returns Promise resolving to an array of vector objects
 * @throws Error if the request fails
 */
export const fetchVectors = (limit: number = 100, offset: number = 0) =>
  apiFetch(`/db/vectors/list?limit=${limit}&offset=${offset}`);

/**
 * Fetch recent run summaries from the run logs.
 *
 * @param limit - Maximum number of runs to return (default: 20)
 * @returns Promise resolving to an array of run summary objects
 * @throws Error if the request fails
 */
export const fetchRuns = (limit: number = 20) =>
  apiFetch(`/db/runs?limit=${limit}`);

/**
 * Fetch events for a specific run.
 *
 * @param runId - ID of the run to query
 * @param eventType - Optional event type filter
 * @returns Promise resolving to an array of event objects
 * @throws Error if the request fails
 */
export const fetchRunEvents = (runId: string, eventType?: string) => {
  const qs = eventType ? `?event_type=${encodeURIComponent(eventType)}` : '';
  return apiFetch(`/db/runs/${encodeURIComponent(runId)}/events${qs}`);
};

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
}) => jsonPost('/cli/execute', data);

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
 * (the FastAPI side will see the client disconnect and stop emitting).
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
        const text = await response.text().catch(() => '');
        handlers.onError?.(text || `HTTP ${response.status}`);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

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
        else if (event === 'complete') handlers.onComplete?.(payload);
        else if (event === 'error') handlers.onError?.(payload.error ?? String(payload));
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
    } catch (err: any) {
      if (err?.name === 'AbortError') return;
      handlers.onError?.(err?.message || String(err));
    }
  })();

  return controller;
};
