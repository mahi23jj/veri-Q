import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, API_ROOT } from './client';

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api service', () => {
  it('reads the runtime profile from the application endpoint', async () => {
    const fetchMock = stubFetch({ target_app_id: 'app-1', runtime_config: null });
    const result = await api.getRuntimeProfile('app-1');

    expect(result.target_app_id).toBe('app-1');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_ROOT}/applications/app-1/runtime-profile`);
    expect(init.method).toBeUndefined();
  });

  it('starts a test run with a POST body carrying only the case id', async () => {
    const fetchMock = stubFetch({ run: { id: 'run-1' }, scheduled: true, next: 'poll' }, 202);
    await api.startTestRun('app-1', 'plan-1', 'case-1');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_ROOT}/applications/app-1/test-plans/plan-1/runs`);
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' });
    expect(JSON.parse(String(init.body))).toEqual({ case_id: 'case-1' });
  });

  it('approves an explicit plan revision', async () => {
    const fetchMock = stubFetch({ id: 'plan-1', status: 'APPROVED' });
    await api.approveTestPlan('app-1', 'plan-1', 3);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_ROOT}/applications/app-1/test-plans/plan-1/approve`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ revision: 3 });
  });

  it('encodes run filters into the query string', async () => {
    const fetchMock = stubFetch([]);
    await api.listTestRuns('app-1', { verdict: 'PASS', lifecycle_state: 'COMPLETED', limit: 50 });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      `${API_ROOT}/applications/app-1/test-runs?lifecycle_state=COMPLETED&verdict=PASS&limit=50`,
    );
  });

  it('resolves 204 responses as undefined', async () => {
    stubFetch(null, 204);
    await expect(api.deleteApplication('app-1')).resolves.toBeUndefined();
  });

  it('flattens structured validation errors into a readable detail', async () => {
    stubFetch(
      {
        detail: {
          message: 'the test case cannot be executed',
          issues: [
            { code: 'PLAN_NOT_APPROVED', message: 'only an approved plan revision can be executed' },
            { code: 'CASE_BLOCKED', message: 'the test case is BLOCKED' },
          ],
        },
      },
      422,
    );

    await expect(api.startTestRun('app-1', 'plan-1', 'case-1')).rejects.toMatchObject({
      status: 422,
      detail:
        'the test case cannot be executed; only an approved plan revision can be executed; the test case is BLOCKED',
    });
  });

  it('reports an unreachable backend as a status 0 ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network down')));

    await expect(api.health()).rejects.toBeInstanceOf(ApiError);
    await expect(api.health()).rejects.toMatchObject({ status: 0 });
  });
});
