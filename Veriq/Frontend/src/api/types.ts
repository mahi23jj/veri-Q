/**
 * Response types aligned with the VeriQ backend Pydantic schemas.
 * Keep these in sync with `backend/app/schemas/*.py`.
 */

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

/** Backend `TargetAppCreate.environment` accepts only these values. */
export type TargetEnvironment = 'development' | 'test';

export type ApplicationEnvironment = TargetEnvironment | string;

export interface TargetApplication {
  id: string;
  name: string;
  description: string | null;
  environment: ApplicationEnvironment;
  created_at: string;
  updated_at: string;
}

/** Returned by POST /applications and POST /applications/{id}/api-key. */
export interface TargetApplicationWithKey extends TargetApplication {
  api_key: string;
}

export type TaskObservationStatus = 'DISCOVERED' | 'OBSERVING' | 'DISABLED';

export interface RegisteredTask {
  id: string;
  target_app_id: string;
  task_name: string;
  status: TaskObservationStatus | string;
  discovery_source: string;
  first_seen_at: string;
  last_seen_at: string;
  discovered_at: string;
  task_metadata: Record<string, unknown> | null;
}

/** Registered task plus cheap aggregates computed by the catalog endpoint. */
export interface TaskCatalogItem extends RegisteredTask {
  execution_count: number;
  last_execution_at: string | null;
  last_outcome: string | null;
  queue_names: string[];
}

export type WorkerStatus = 'ONLINE' | 'OFFLINE' | 'UNKNOWN';

export interface WorkerQueue {
  id: string;
  queue_name: string;
  exchange: string | null;
  routing_key: string | null;
  is_configured: boolean;
  is_consumed: boolean;
  last_seen_at: string;
}

export interface Worker {
  id: string;
  target_app_id: string;
  worker_instance_id: string;
  hostname: string | null;
  worker_hostname: string | null;
  pid: number | null;
  process_start_identity: string | null;
  status: WorkerStatus | string;
  registered_task_names: string[] | null;
  first_seen_at: string;
  last_seen_at: string;
  queues: WorkerQueue[];
}

export type ExecutionStatus = 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'RETRYING';

export interface TaskExecution {
  id: string;
  target_app_id: string;
  registered_task_id: string | null;
  execution_id: string;
  celery_task_id: string | null;
  task_name: string;
  worker_id: string | null;
  worker_instance_id: string | null;
  worker_hostname: string | null;
  pid: number | null;
  process_start_identity: string | null;
  queue_name: string | null;
  experiment_run_id: string | null;
  veriq_operation_id: string | null;
  status: ExecutionStatus | string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
}

export type TaskEventType =
  | 'TASK_STARTED'
  | 'TASK_SUCCEEDED'
  | 'TASK_FAILED'
  | 'TASK_RETRY_REQUESTED'
  | 'TASK_CHECKPOINT';

export interface ExecutionEvent {
  id: string;
  task_execution_id: string;
  event_type: TaskEventType | string;
  source: string;
  payload: Record<string, unknown> | null;
  occurred_at: string;
}

export interface TaskExecutionDetail extends TaskExecution {
  events: ExecutionEvent[];
}

/** The only scenario the backend currently implements. */
export type ExperimentScenario = 'crash_after_commit';

/** Experiment statuses currently produced by the backend. */
export type ExperimentStatus = 'DRAFT' | 'ACTIVE' | string;

export interface Experiment {
  id: string;
  target_app_id: string;
  name: string;
  description: string | null;
  task_name: string;
  scenario: ExperimentScenario | string;
  checkpoint_name: string | null;
  timeout_seconds: number;
  status: ExperimentStatus;
  config_snapshot: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ExperimentRun {
  id: string;
  experiment_id: string;
  run_number: number;
  status: string;
  verdict: string | null;
  operation_id: string | null;
  config_snapshot: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ExperimentEvent {
  id: string;
  experiment_run_id: string;
  event_type: string;
  source: string;
  payload: Record<string, unknown> | null;
  occurred_at: string;
}
