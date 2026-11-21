/**
 * Single typed HTTP client for the VeriQ backend.
 *
 * Dashboard/control reads are currently unauthenticated on the backend; only
 * SDK/runner ingestion endpoints require `X-API-Key`. API keys are never
 * persisted in this dashboard — they are displayed once after creation or
 * rotation and must be copied by the developer.
 */
import type {
  AdapterType,
  ApplicationAdapter,
  CancelRunResponse,
  CompatibilityEvaluation,
  ExecutionEvent,
  Experiment,
  PaginatedResponse,
  ReliabilityVerdict,
  RunnerCapabilities,
  RunnerEnvironment,
  RunnerWorker,
  RuntimeEvent,
  RuntimeProfile,
  ScenarioCatalog,
  ScenarioDefinition,
  StartRunResponse,
  TargetApplication,
  TargetApplicationWithKey,
  TaskCatalogItem,
  TaskExecution,
  TaskExecutionDetail,
  TaskObservationStatus,
  TaskReliabilityOverview,
  TaskScenarioItem,
  TaskTestContract,
  TestCaseRun,
  TestCaseRunDetail,
  TestPlan,
  TestPlanDetail,
  TestPlanGenerateResponse,
  TestPlanRevision,
  TestPlanTestCase,
  TestPlanValidation,
  TestContractPayload,
  FaultEvent,
  RecoveryObservation,
  RunVerdict,
  Worker,
  Checkpoint,
  CheckpointWithScenarios,
  CheckpointScenarioItem,
  ContractIssue,
} from './types';

const configuredBaseUrl = (import.meta.env.VITE_API_URL as string | undefined)?.trim();

/** Backend root, e.g. `http://localhost:8000` (no trailing slash). */
export const API_BASE_URL = (configuredBaseUrl || 'http://localhost:8000').replace(/\/+$/, '');
export const API_ROOT = `${API_BASE_URL}/api/v1`;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

type QueryValue = string | number | boolean | null | undefined;

function buildQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `?${query}` : '';
}

async function parseDetail(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`.trim();
  const text = await response.text().catch(() => '');
  if (!text) return fallback;
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (body.detail && typeof body.detail === 'object' && !Array.isArray(body.detail)) {
      const structured = body.detail as { message?: unknown; issues?: unknown };
      const message = typeof structured.message === 'string' ? structured.message : null;
      if (Array.isArray(structured.issues) && structured.issues.length > 0) {
        const issues = structured.issues
          .map((issue) => {
            if (issue && typeof issue === 'object' && 'message' in issue) {
              return String((issue as { message: unknown }).message);
            }
            return String(issue);
          })
          .filter(Boolean);
        return [message, ...issues].filter(Boolean).join('; ');
      }
      if (message) return message;
    }
    if (Array.isArray(body.detail)) {
      const messages = body.detail
        .map((entry) => {
          if (entry && typeof entry === 'object' && 'msg' in entry) {
            return String((entry as { msg: unknown }).msg);
          }
          return String(entry);
        })
        .filter(Boolean);
      if (messages.length > 0) return messages.join('; ');
    }
  } catch {
    // Non-JSON error body: return the raw text below.
  }
  return text;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      0,
      `Could not reach the VeriQ backend at ${API_BASE_URL}. Check that the API is running and VITE_API_URL is correct.`,
    );
  }

  if (!response.ok) {
    throw new ApiError(response.status, await parseDetail(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  // ---------------------------------------------------------------------- health
  health() {
    return request<{ status: string; database: string }>('/health');
  },

  // ---------------------------------------------------------------- applications
  listApplications(params: { skip?: number; limit?: number } = {}) {
    return request<PaginatedResponse<TargetApplication>>(
      `/applications${buildQuery({ skip: params.skip, limit: params.limit })}`,
    );
  },

  getApplication(applicationId: string) {
    return request<TargetApplication>(`/applications/${applicationId}`);
  },

  createApplication(payload: {
    name: string;
    description?: string | null;
    environment: 'development' | 'test';
  }) {
    return request<TargetApplicationWithKey>('/applications', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  rotateApiKey(applicationId: string) {
    return request<TargetApplicationWithKey>(`/applications/${applicationId}/api-key`, {
      method: 'POST',
    });
  },

  deleteApplication(applicationId: string) {
    return request<void>(`/applications/${applicationId}`, { method: 'DELETE' });
  },

  // ---------------------------------------------------------------- discovery
  listApplicationTasks(
    applicationId: string,
    params: { status?: TaskObservationStatus; skip?: number; limit?: number } = {},
  ) {
    return request<PaginatedResponse<TaskCatalogItem>>(
      `/applications/${applicationId}/registered-tasks${buildQuery({
        status: params.status,
        skip: params.skip,
        limit: params.limit,
      })}`,
    );
  },

  listRegisteredTasks(
    params: { target_app_id?: string; status?: TaskObservationStatus; skip?: number; limit?: number } = {},
  ) {
    return request<PaginatedResponse<TaskCatalogItem>>(
      `/registered-tasks${buildQuery({
        target_app_id: params.target_app_id,
        status: params.status,
        skip: params.skip,
        limit: params.limit,
      })}`,
    );
  },

  getRegisteredTask(taskId: string) {
    return request<TaskCatalogItem>(`/registered-tasks/${taskId}`);
  },

  setTaskObservation(taskId: string, status: TaskObservationStatus) {
    return request<TaskCatalogItem>(`/registered-tasks/${taskId}/observation`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  },

  listTaskExecutions(taskId: string, params: { skip?: number; limit?: number } = {}) {
    return request<PaginatedResponse<TaskExecution>>(
      `/registered-tasks/${taskId}/executions${buildQuery({
        skip: params.skip,
        limit: params.limit,
      })}`,
    );
  },

  // ---------------------------------------------------------------- workers
  listWorkers(
    params: { target_app_id?: string; status?: string; skip?: number; limit?: number } = {},
  ) {
    return request<PaginatedResponse<Worker>>(
      `/workers${buildQuery({
        target_app_id: params.target_app_id,
        status: params.status,
        skip: params.skip,
        limit: params.limit,
      })}`,
    );
  },

  getWorker(workerId: string) {
    return request<Worker>(`/workers/${workerId}`);
  },

  // ---------------------------------------------------------------- executions
  listExecutions(
    params: {
      target_app_id?: string;
      task_name?: string;
      status?: string;
      celery_task_id?: string;
      skip?: number;
      limit?: number;
    } = {},
  ) {
    return request<PaginatedResponse<TaskExecution>>(
      `/task-executions${buildQuery({
        target_app_id: params.target_app_id,
        task_name: params.task_name,
        status: params.status,
        celery_task_id: params.celery_task_id,
        skip: params.skip,
        limit: params.limit,
      })}`,
    );
  },

  getExecution(executionId: string) {
    return request<TaskExecutionDetail>(`/task-executions/${executionId}`);
  },

  listExecutionEvents(executionId: string) {
    return request<ExecutionEvent[]>(`/task-executions/${executionId}/events`);
  },

  // ---------------------------------------------------------------- experiments
  listExperiments(
    params: { target_app_id?: string; skip?: number; limit?: number } = {},
  ) {
    return request<PaginatedResponse<Experiment>>(
      `/experiments${buildQuery({
        target_app_id: params.target_app_id,
        skip: params.skip,
        limit: params.limit,
      })}`,
    );
  },

  getExperiment(experimentId: string) {
    return request<Experiment>(`/experiments/${experimentId}`);
  },

  createExperiment(payload: {
    target_app_id: string;
    name: string;
    description?: string | null;
    task_name: string;
    scenario?: 'crash_after_commit';
    checkpoint_name?: string | null;
    timeout_seconds?: number;
  }) {
    return request<Experiment>('/experiments', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  updateExperiment(
    experimentId: string,
    payload: {
      name?: string;
      description?: string | null;
      task_name?: string;
      scenario?: 'crash_after_commit';
      checkpoint_name?: string | null;
      timeout_seconds?: number;
    },
  ) {
    return request<Experiment>(`/experiments/${experimentId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  deleteExperiment(experimentId: string) {
    return request<void>(`/experiments/${experimentId}`, { method: 'DELETE' });
  },

  // ------------------------------------------------------------ reliability planning
  listScenarios(params: { category?: string; trigger_type?: string } = {}) {
    return request<ScenarioCatalog>(
      `/scenarios${buildQuery({ category: params.category, trigger_type: params.trigger_type })}`,
    );
  },

  getScenario(scenarioId: string) {
    return request<ScenarioDefinition>(`/scenarios/${scenarioId}`);
  },

  listAdapterTypes() {
    return request<AdapterType[]>('/adapter-types');
  },

  listApplicationAdapterTypes(applicationId: string) {
    return request<AdapterType[]>(`/applications/${applicationId}/adapter-types`);
  },

  listAdapters(applicationId: string) {
    return request<ApplicationAdapter[]>(`/applications/${applicationId}/adapters`);
  },

  createAdapter(
    applicationId: string,
    payload: {
      name: string;
      adapter_type: string;
      enabled_triggers?: string[];
      configuration_ref?: string | null;
    },
  ) {
    return request<ApplicationAdapter>(`/applications/${applicationId}/adapters`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  updateAdapter(
    applicationId: string,
    adapterId: string,
    payload: { enabled_triggers?: string[]; configuration_ref?: string | null },
  ) {
    return request<ApplicationAdapter>(`/applications/${applicationId}/adapters/${adapterId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  validateAdapter(applicationId: string, adapterId: string) {
    return request<ApplicationAdapter>(
      `/applications/${applicationId}/adapters/${adapterId}/validate`,
      { method: 'POST' },
    );
  },

  deleteAdapter(applicationId: string, adapterId: string) {
    return request<void>(`/applications/${applicationId}/adapters/${adapterId}`, {
      method: 'DELETE',
    });
  },

  listContracts(applicationId: string) {
    return request<TaskTestContract[]>(`/applications/${applicationId}/contracts`);
  },

  getTaskContract(applicationId: string, taskId: string) {
    return request<TaskTestContract>(
      `/applications/${applicationId}/registered-tasks/${taskId}/contract`,
    );
  },

  createContract(applicationId: string, taskId: string, payload: TestContractPayload) {
    return request<TaskTestContract>(
      `/applications/${applicationId}/registered-tasks/${taskId}/contract`,
      { method: 'POST', body: JSON.stringify(payload) },
    );
  },

  updateContract(applicationId: string, contractId: string, payload: TestContractPayload) {
    return request<TaskTestContract>(`/applications/${applicationId}/contracts/${contractId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  validateContract(applicationId: string, contractId: string) {
    return request<{ valid: boolean; issues: ContractIssue[] }>(
      `/applications/${applicationId}/contracts/${contractId}/validate`,
      { method: 'POST' },
    );
  },

  listTaskScenarios(applicationId: string, taskId: string) {
    return request<TaskScenarioItem[]>(
      `/applications/${applicationId}/registered-tasks/${taskId}/scenarios`,
    );
  },

  selectTaskScenario(
    applicationId: string,
    taskId: string,
    scenarioId: string,
    payload: { enabled: boolean; config?: Record<string, unknown> | null },
  ) {
    return request<TaskScenarioItem>(
      `/applications/${applicationId}/registered-tasks/${taskId}/scenarios/${scenarioId}`,
      { method: 'PUT', body: JSON.stringify(payload) },
    );
  },

  taskReliability(applicationId: string, taskId: string) {
    return request<TaskReliabilityOverview>(
      `/applications/${applicationId}/registered-tasks/${taskId}/reliability`,
    );
  },

  listCheckpoints(applicationId: string, taskId?: string) {
    return request<Checkpoint[]>(
      `/applications/${applicationId}/checkpoints${buildQuery({ task_id: taskId })}`,
    );
  },

  getCheckpoint(applicationId: string, checkpointId: string) {
    return request<CheckpointWithScenarios>(
      `/applications/${applicationId}/checkpoints/${checkpointId}`,
    );
  },

  updateCheckpointReliability(applicationId: string, checkpointId: string, enabled: boolean) {
    return request<Checkpoint>(`/applications/${applicationId}/checkpoints/${checkpointId}`, {
      method: 'PATCH',
      body: JSON.stringify({ reliability_enabled: enabled }),
    });
  },

  selectCheckpointScenario(
    applicationId: string,
    checkpointId: string,
    scenarioId: string,
    payload: { enabled: boolean; config?: Record<string, unknown> | null },
  ) {
    return request<CheckpointScenarioItem>(
      `/applications/${applicationId}/checkpoints/${checkpointId}/scenarios/${scenarioId}`,
      { method: 'PUT', body: JSON.stringify(payload) },
    );
  },

  evaluateCompatibility(
    applicationId: string,
    selections: {
      task_id: string;
      scenario_id: string;
      trigger_type?: 'automatic' | 'checkpoint';
      checkpoint_id?: string | null;
    }[],
  ) {
    return request<{ results: CompatibilityEvaluation[] }>(
      `/applications/${applicationId}/compatibility/evaluate`,
      { method: 'POST', body: JSON.stringify({ selections }) },
    );
  },

  createTestPlan(
    applicationId: string,
    payload: { name: string; description?: string | null; task_ids: string[] },
  ) {
    return request<TestPlan>(`/applications/${applicationId}/test-plans`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  listTestPlans(applicationId: string) {
    return request<TestPlan[]>(`/applications/${applicationId}/test-plans`);
  },

  getTestPlan(applicationId: string, planId: string) {
    return request<TestPlanDetail>(`/applications/${applicationId}/test-plans/${planId}`);
  },

  updateTestPlan(
    applicationId: string,
    planId: string,
    payload: { name?: string; description?: string | null; task_ids?: string[] },
  ) {
    return request<TestPlan>(`/applications/${applicationId}/test-plans/${planId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  generateTestPlan(applicationId: string, planId: string) {
    return request<TestPlanGenerateResponse>(
      `/applications/${applicationId}/test-plans/${planId}/generate`,
      { method: 'POST' },
    );
  },

  validateTestPlan(applicationId: string, planId: string) {
    return request<TestPlanValidation>(
      `/applications/${applicationId}/test-plans/${planId}/validate`,
      { method: 'POST' },
    );
  },

  submitTestPlan(applicationId: string, planId: string) {
    return request<TestPlan>(`/applications/${applicationId}/test-plans/${planId}/submit`, {
      method: 'POST',
    });
  },

  approveTestPlan(applicationId: string, planId: string, revision: number) {
    return request<TestPlan>(`/applications/${applicationId}/test-plans/${planId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ revision }),
    });
  },

  revokeTestPlan(applicationId: string, planId: string) {
    return request<TestPlan>(`/applications/${applicationId}/test-plans/${planId}/revoke`, {
      method: 'POST',
    });
  },

  getPlanRevision(applicationId: string, planId: string, revision: number) {
    return request<TestPlanRevision>(
      `/applications/${applicationId}/test-plans/${planId}/revisions/${revision}`,
    );
  },

  listPlanTestCases(
    applicationId: string,
    planId: string,
    revision: number,
    params: { skip?: number; limit?: number } = {},
  ) {
    return request<TestPlanTestCase[]>(
      `/applications/${applicationId}/test-plans/${planId}/revisions/${revision}/test-cases${buildQuery(
        { skip: params.skip, limit: params.limit },
      )}`,
    );
  },

  // ------------------------------------------------------------ reliability runtime
  getRuntimeProfile(applicationId: string) {
    return request<{ target_app_id: string; runtime_config: RuntimeProfile | null }>(
      `/applications/${applicationId}/runtime-profile`,
    );
  },

  putRuntimeProfile(applicationId: string, payload: RuntimeProfile) {
    return request<{ target_app_id: string; runtime_config: RuntimeProfile | null }>(
      `/applications/${applicationId}/runtime-profile`,
      { method: 'PUT', body: JSON.stringify(payload) },
    );
  },

  runnerCapabilities(applicationId: string) {
    return request<RunnerCapabilities>(
      `/applications/${applicationId}/runner/capabilities`,
    );
  },

  startTestRun(applicationId: string, planId: string, caseId: string) {
    return request<StartRunResponse>(
      `/applications/${applicationId}/test-plans/${planId}/runs`,
      { method: 'POST', body: JSON.stringify({ case_id: caseId }) },
    );
  },

  listTestRuns(
    applicationId: string,
    params: {
      lifecycle_state?: string;
      verdict?: ReliabilityVerdict | string;
      plan_id?: string;
      limit?: number;
    } = {},
  ) {
    return request<TestCaseRun[]>(
      `/applications/${applicationId}/test-runs${buildQuery({
        lifecycle_state: params.lifecycle_state,
        verdict: params.verdict,
        plan_id: params.plan_id,
        limit: params.limit,
      })}`,
    );
  },

  getTestRun(applicationId: string, runId: string) {
    return request<TestCaseRunDetail>(
      `/applications/${applicationId}/test-runs/${runId}`,
    );
  },

  getRunEnvironment(applicationId: string, runId: string) {
    return request<RunnerEnvironment>(
      `/applications/${applicationId}/test-runs/${runId}/environment`,
    );
  },

  getRunWorkers(applicationId: string, runId: string) {
    return request<RunnerWorker[]>(`/applications/${applicationId}/test-runs/${runId}/workers`);
  },

  getRunFaults(applicationId: string, runId: string) {
    return request<FaultEvent[]>(`/applications/${applicationId}/test-runs/${runId}/faults`);
  },

  getRunRecovery(applicationId: string, runId: string) {
    return request<RecoveryObservation>(
      `/applications/${applicationId}/test-runs/${runId}/recovery`,
    );
  },

  getRunVerdict(applicationId: string, runId: string) {
    return request<RunVerdict>(`/applications/${applicationId}/test-runs/${runId}/verdict`);
  },

  getRunEvents(applicationId: string, runId: string) {
    return request<RuntimeEvent[]>(`/applications/${applicationId}/test-runs/${runId}/events`);
  },

  cancelTestRun(applicationId: string, runId: string) {
    return request<CancelRunResponse>(
      `/applications/${applicationId}/test-runs/${runId}/cancel`,
      { method: 'POST' },
    );
  },

  recoverInterruptedRuns(applicationId: string) {
    return request<{ recovered: Record<string, unknown>[] }>(
      `/applications/${applicationId}/test-runs/recover-interrupted`,
      { method: 'POST' },
    );
  },

};

