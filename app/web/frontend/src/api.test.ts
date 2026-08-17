import {
  ApiError,
  apiErrorMessageForStatus,
  fetchBudgetReservations,
  fetchDelegationGrants,
  fetchRoutingConfig,
  fetchSentinelAlerts,
  fetchSentinelSignals,
  fetchTasks,
  fetchTrustScores,
  fetchViolations,
  getUserFacingErrorMessage,
  isAbortError,
} from './api.ts';

const assert = (condition: unknown, message: string): void => {
  if (!condition) throw new Error(message);
};

const originalFetch = globalThis.fetch;

try {
  for (const status of [401, 403, 404, 409, 500]) {
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: 'internal diagnostic must stay server-side' }), {
        status,
        headers: { 'Content-Type': 'application/json' },
      });

    try {
      await fetchTasks();
      throw new Error(`Expected HTTP ${status} to reject`);
    } catch (error: unknown) {
      assert(error instanceof ApiError, `HTTP ${status} should produce ApiError`);
      assert((error as ApiError).status === status, `ApiError should retain ${status}`);
      assert(
        !(error as Error).message.includes('internal diagnostic'),
        'server response detail must not be rendered as client error copy'
      );
      assert(
        getUserFacingErrorMessage(error).length > 0,
        `HTTP ${status} should have safe user-facing copy`
      );
    }
  }

  assert(
    apiErrorMessageForStatus(401).toLowerCase().includes('authorized'),
    '401 should explain authorization failure'
  );
  assert(
    getUserFacingErrorMessage(new Error('private stack trace'), 'safe fallback') === 'safe fallback',
    'unknown errors should use the caller-provided safe fallback'
  );

  let receivedSignal: AbortSignal | null | undefined;
  const signalController = new AbortController();
  globalThis.fetch = async (_input, init) => {
    receivedSignal = init?.signal;
    return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  await fetchTasks({ signal: signalController.signal });
  assert(receivedSignal === signalController.signal, 'request signal should reach fetch');

  const abortController = new AbortController();
  globalThis.fetch = (_input, init) =>
    new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => {
        reject(new DOMException('request aborted', 'AbortError'));
      });
    });
  const pending = fetchTasks({ signal: abortController.signal });
  abortController.abort();
  try {
    await pending;
    throw new Error('Expected an aborted request to reject');
  } catch (error: unknown) {
    assert(isAbortError(error), 'aborted request should remain distinguishable');
  }

  // Governance read clients must target the documented dashboard paths and
  // encode their filters as query parameters. A drifting path here is silent
  // in the UI (the page just renders empty), so pin it in a test.
  const requestedPaths: string[] = [];
  globalThis.fetch = async (input) => {
    requestedPaths.push(String(input));
    return new Response('[]', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  await fetchTrustScores('agent', 25);
  await fetchViolations(true, 10);
  await fetchDelegationGrants(5);
  await fetchBudgetReservations(5);
  await fetchRoutingConfig();

  const expectedPaths = [
    '/api/db/trust?limit=25&entity_type=agent',
    '/api/db/violations?limit=10&open_only=true',
    '/api/db/delegation/grants?limit=5',
    '/api/db/delegation/reservations?limit=5',
    '/api/routing/config',
  ];
  for (const [index, expected] of expectedPaths.entries()) {
    assert(
      requestedPaths[index] === expected,
      `governance client ${index} should request ${expected}, got ${requestedPaths[index]}`
    );
  }

  // The sentinel endpoints return envelopes, not bare arrays.
  globalThis.fetch = async (input) => {
    requestedPaths.push(String(input));
    return new Response(JSON.stringify({ signals: [], alerts: [], total: 0 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  const signals = await fetchSentinelSignals(7);
  const alerts = await fetchSentinelAlerts(true, 7);
  assert(Array.isArray(signals.signals), 'sentinel signals should unwrap an envelope');
  assert(Array.isArray(alerts.alerts), 'sentinel alerts should unwrap an envelope');
  assert(
    requestedPaths.at(-2) === '/api/db/hebbian/sentinel?limit=7',
    'sentinel signal path should carry the limit'
  );
  assert(
    requestedPaths.at(-1) === '/api/db/hebbian/sentinel/alerts?limit=7&open_only=true',
    'sentinel alert path should carry the open-only filter'
  );

  console.log('API contract checks passed');
} finally {
  globalThis.fetch = originalFetch;
}
