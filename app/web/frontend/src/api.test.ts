import {
  ApiError,
  apiErrorMessageForStatus,
  fetchTasks,
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

  console.log('API contract checks passed');
} finally {
  globalThis.fetch = originalFetch;
}
