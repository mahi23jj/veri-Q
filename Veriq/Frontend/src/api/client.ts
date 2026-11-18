/**
 * Single typed HTTP client for the VeriQ backend.
 *
 * Dashboard/control reads are currently unauthenticated on the backend; only
 * SDK/runner ingestion endpoints require `X-API-Key`. API keys are never
 * persisted in this dashboard — they are displayed once after creation or
 * rotation and must be copied by the developer.
 */
import type {
  ExecutionEvent,
  Experiment,
  PaginatedResponse,
  TargetApplication,
  TargetApplicationWithKey,
  TaskCatalogItem,
  TaskExecution,
  TaskExecutionDetail,
  TaskObservationStatus,
  Worker,
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
};

