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

/**
 * A persisted registry row from `/api/db/agents`.
 *
 * Carries the governance and learning columns the registry migration added
 * (trust tier, quarantine status, violation count, Hebbian/Sentinel state) in
 * addition to the original scoring fields. The index signature is retained so
 * a column added server-side does not break the client before it is typed.
 */
export interface AgentScore {
  name: string;
  capabilities: string[];
  alignment: number;
  accuracy: number;
  efficiency: number;
  composite_score: number;
  trust_tier: string;
  status: string;
  violation_count: number;
  trust_score: number | null;
  execution_count: number;
  successful_executions: number;
  failed_executions: number;
  hebbian_weight: number | null;
  hebbian_delta: number;
  hebbian_activations: number;
  hebbian_success_rate: number;
  hebbian_task_type: string | null;
  hebbian_pair_bonus: number;
  hebbian_timing_score: number | null;
  routing_intelligence: number;
  hebbian_oscillation_rate: number;
  hebbian_sentinel_alert: boolean;
  hebbian_sentinel_samples: number;
  learning_updated_at: string | null;
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

/**
 * One persisted trust score from the governance trust store
 * (`data/trust_scores.db`). Written for every completed outcome even when
 * `beta == 0` and trust is not part of the routing blend.
 */
export interface TrustScoreRecord {
  entity_type: string;
  entity_id: string;
  score: number;
  level: string;
  decay_rate: number;
  reinforcement_events: number;
  penalty_events: number;
  last_updated: string;
}

/** One sandbox / governance violation recorded against an agent. */
export interface ViolationRecord {
  violation_id: string;
  agent_name: string;
  timestamp: string;
  violation_type: string;
  details: string;
  action_taken: string;
  cleared: boolean;
}

/**
 * Rolling Hebbian stability state for one (agent, task type) pair. These
 * signals are observational: they never change routing rank, weights, trust,
 * or quarantine state on their own.
 */
export interface SentinelSignal {
  agent_name: string;
  task_type: string;
  sample_count: number;
  sign_changes: number;
  oscillation_rate: number;
  alert_active: boolean;
  threshold: number;
  window_size: number;
  updated_at: string;
}

/** A persisted Sentinel alert transition, for operator review. */
export interface SentinelAlert {
  id: number;
  agent_name: string;
  task_type: string;
  oscillation_rate: number;
  sample_count: number;
  threshold: number;
  status: string;
  created_at: string;
  resolved_at: string | null;
}

/** Delegation-grant ledger metadata. Signed payloads are never exposed here. */
export interface DelegationGrant {
  grant_id: string;
  root_task_id: string;
  parent_task_id: string;
  budget_reservation_id: string;
  expires_at: string;
  created_at: string;
}

/** A budget reservation backing delegated routing. */
export interface BudgetReservation {
  reservation_id: string;
  state: string;
  remaining_units: number | null;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * A capability the deployment can route, labelled by whether the Routing
 * Kernel's reviewed ATP execution domain authorizes it. `kernel_reviewed:
 * false` means tasks using it are served by the legacy compatibility path
 * without kernel authorization.
 */
export interface RoutingCapabilityInfo {
  name: string;
  kernel_reviewed: boolean;
  agents: string[];
}

/** Hebbian Sentinel observation settings reported by the backend. */
export interface RoutingSentinelConfig {
  window: number;
  threshold: number;
  warmup: number;
}

/**
 * Live routing configuration. The UI reads this to name the routing path an
 * execution took and to offer only capabilities that can actually be routed.
 *
 * `source` is `'orchestrator'` when the values came from the live
 * orchestrator, `'environment'` when the orchestrator was unavailable and
 * only configuration could be reported.
 */
export interface RoutingConfig {
  source: 'orchestrator' | 'environment' | string;
  kernel_enabled: boolean;
  kernel_active: boolean;
  hebbian_enabled: boolean;
  trust_signal_active: boolean;
  alpha: number;
  beta: number;
  trust_floor: number;
  fallback_capability: string | null;
  atp_strict: boolean;
  reviewed_capabilities: string[];
  capabilities: RoutingCapabilityInfo[];
  sentinel: RoutingSentinelConfig;
  routing_paths: string[];
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

/* -------------------------------------------------------------------------- */
/* Governance read models                                                     */
/*                                                                            */
/* All read-only. The dashboard never mutates trust, violations, quarantine,  */
/* or delegation state — those stay owned by the Python core and the          */
/* authenticated Express boundary.                                            */
/* -------------------------------------------------------------------------- */

/**
 * Fetch persisted trust scores.
 *
 * @param entityType - Optional entity-family filter (e.g. `agent`)
 * @param limit - Maximum records to return (1-500, default 200)
 */
export const fetchTrustScores = (
  entityType?: string,
  limit: number = 200,
  options?: ApiRequestOptions
) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (entityType) params.set('entity_type', entityType);
  return apiFetch<TrustScoreRecord[]>(`/db/trust?${params.toString()}`, options);
};

/**
 * Fetch recorded sandbox and governance violations.
 *
 * @param openOnly - Exclude violations an operator has cleared
 * @param limit - Maximum records to return (1-500, default 200)
 */
export const fetchViolations = (
  openOnly: boolean = false,
  limit: number = 200,
  options?: ApiRequestOptions
) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (openOnly) params.set('open_only', 'true');
  return apiFetch<ViolationRecord[]>(`/db/violations?${params.toString()}`, options);
};

/**
 * Fetch current Hebbian Sentinel stability signals.
 *
 * @param limit - Maximum records to return (1-500, default 100)
 */
export const fetchSentinelSignals = (
  limit: number = 100,
  options?: ApiRequestOptions
) =>
  apiFetch<{ signals: SentinelSignal[]; total: number }>(
    `/db/hebbian/sentinel?limit=${limit}`,
    options
  );

/**
 * Fetch persisted Sentinel alert transitions.
 *
 * @param openOnly - Return only alerts still in the `open` state
 * @param limit - Maximum records to return (1-500, default 100)
 */
export const fetchSentinelAlerts = (
  openOnly: boolean = false,
  limit: number = 100,
  options?: ApiRequestOptions
) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (openOnly) params.set('open_only', 'true');
  return apiFetch<{ alerts: SentinelAlert[]; total: number }>(
    `/db/hebbian/sentinel/alerts?${params.toString()}`,
    options
  );
};

/** Fetch delegation-grant ledger metadata (signed payloads are not exposed). */
export const fetchDelegationGrants = (
  limit: number = 100,
  options?: ApiRequestOptions
) => apiFetch<DelegationGrant[]>(`/db/delegation/grants?limit=${limit}`, options);

/** Fetch budget reservations backing delegated routing. */
export const fetchBudgetReservations = (
  limit: number = 100,
  options?: ApiRequestOptions
) =>
  apiFetch<BudgetReservation[]>(
    `/db/delegation/reservations?limit=${limit}`,
    options
  );

/**
 * Fetch the live routing configuration used to label decisions in the UI.
 *
 * Callers should treat a failure here as non-fatal: pages fall back to their
 * static defaults rather than blocking on the label.
 */
export const fetchRoutingConfig = (options?: ApiRequestOptions) =>
  apiFetch<RoutingConfig>('/routing/config', options);

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
  /**
   * Which routing implementation served the task: `kernel` for an authorized
   * Routing Kernel route, `pinned` when the caller named the agent, or a
   * `legacy_*` value when the kernel could not serve it.
   */
  routing_path: string | null;
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
    routing_path: string | null;
  }) => void;
  onToken?: (text: string) => void;
  onComplete?: (data: {
    task_id: string;
    agent_name: string;
    status: string;
    summary: string;
    note_path: string | null;
    error: string | null;
    routing_path: string | null;
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

export interface GovernanceAgentRow {
  name: string;
  tier: string;
  status: string;
  violations: number;
  trust_score: number | null;
}

export interface SentinelScope {
  agent: string;
  task_type: string;
  alert_active: boolean;
  oscillation_rate: number;
  sample_count: number;
  threshold: number;
}

export interface GovernanceSnapshot {
  agents: GovernanceAgentRow[];
  status_counts: Record<string, number>;
  sentinel: SentinelScope[];
  stores: Record<string, boolean>;
}

export interface PrometheusAlert {
  name: string;
  state: string;
  severity: string | null;
  active: Array<{
    labels: Record<string, string>;
    state: string;
    active_at: string | null;
  }>;
}

export interface PrometheusTarget {
  job: string | null;
  health: string;
  scrape_url: string;
  last_error: string | null;
}

export interface PrometheusStatus {
  available: boolean;
  url: string;
  targets: PrometheusTarget[];
  alerts: PrometheusAlert[];
}

/** Durable governance snapshot read straight from the SQLite stores. */
export const fetchGovernanceSnapshot = (
  options: ApiRequestOptions = {}
): Promise<GovernanceSnapshot> =>
  apiFetch<GovernanceSnapshot>('/monitoring/governance', options);

/** Prometheus targets and alert-rule states, proxied by the kernel. */
export const fetchPrometheusStatus = (
  options: ApiRequestOptions = {}
): Promise<PrometheusStatus> =>
  apiFetch<PrometheusStatus>('/monitoring/prometheus', options);
