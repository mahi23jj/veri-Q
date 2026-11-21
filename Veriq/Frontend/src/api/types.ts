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

/* ------------------------------------------------------------------ planning */

export interface ScenarioAdapterRequirement {
  category: string;
  capability: string;
  trigger: string | null;
  description: string;
}

export interface ScenarioDefinition {
  id: string;
  name: string;
  description: string;
  category: string;
  version: number;
  default_trigger_type: 'automatic' | 'checkpoint' | string;
  supported_trigger_modes: string[];
  adapter_requirements: ScenarioAdapterRequirement[];
  preconditions: string[];
  configuration_schema: Record<string, unknown>;
  applicable_task_conditions: string[];
  measurement_requirements: string[];
  expected_recovery: string[];
  requires: {
    safe_input: boolean;
    assertions: boolean;
    effect_measurement: boolean;
    authoritative_measurement: boolean;
    checkpoint: boolean;
  };
  supported_status: string;
  implementation_status: string;
  warnings: string[];
}

export interface ScenarioCatalog {
  catalog_version: string;
  implementation_status: string;
  note: string;
  items: ScenarioDefinition[];
}

export interface AdapterType {
  slug: string;
  name: string;
  category: string;
  description: string;
  capabilities: string[];
  supported_triggers: string[];
  version: string;
  builtin: boolean;
}

export interface ApplicationAdapter {
  id: string;
  target_app_id: string;
  name: string;
  adapter_type: string;
  category: string;
  capabilities: string[];
  enabled_triggers: string[];
  configuration_ref: string | null;
  status: string;
  validation: Record<string, unknown> | null;
  validated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContractIssue {
  code: string;
  severity: 'error' | 'warning' | string;
  message: string;
  field?: string | null;
}

export interface RecoveryPolicy {
  max_attempts: number;
  per_attempt_timeout_seconds: number;
  recovery_deadline_seconds: number;
  expected_terminal_state: 'SUCCEEDED' | 'FAILED' | 'ANY' | string;
  expect_retry: boolean | null;
  expect_redelivery: boolean | null;
  settle_seconds: number;
}

export interface TaskTestContract {
  id: string;
  target_app_id: string;
  registered_task_id: string;
  version: number;
  payload: Record<string, unknown> & { recovery?: Partial<RecoveryPolicy> };
  validation: { valid?: boolean; issues?: ContractIssue[] } | null;
  last_validated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TestContractPayload {
  safe_input: Record<string, unknown>;
  input_fixture_ref: string | null;
  effect_measurements: unknown[];
  assertions: unknown[];
  cleanup: { mode: string; adapter_id?: string | null; description?: string | null };
  recovery: RecoveryPolicy;
  notes: string | null;
}

export interface CompatibilityReason {
  code: string;
  severity: 'configuration' | 'unsupported' | 'warning' | string;
  message: string;
  field?: string | null;
}

export interface SelectedAdapterRef {
  capability?: string;
  category?: string;
  adapter_id?: string;
  adapter_name?: string;
  [key: string]: unknown;
}

export interface CompatibilityEvaluation {
  task_id: string;
  task_name: string;
  scenario_id: string;
  scenario_version: number;
  trigger_type: string;
  checkpoint_id: string | null;
  checkpoint_name: string | null;
  status: 'COMPATIBLE' | 'NEEDS_CONFIGURATION' | 'UNSUPPORTED' | string;
  reasons: CompatibilityReason[];
  warnings: CompatibilityReason[];
  selected_adapters: SelectedAdapterRef[];
  execution_available: boolean;
  execution_note: string;
}

export interface TaskScenarioItem {
  scenario_id: string;
  scenario_version: number;
  name: string;
  category: string;
  description: string;
  default_trigger_type: string;
  supported_status: string;
  implementation_status: string;
  enabled: boolean;
  selected_by_default: boolean;
  config: Record<string, unknown> | null;
  compatibility: CompatibilityEvaluation;
}

export interface Checkpoint {
  id: string;
  target_app_id: string;
  registered_task_id: string;
  name: string;
  discovery_source: string;
  first_seen_at: string;
  last_seen_at: string;
  report_count: number;
  checkpoint_metadata: Record<string, unknown> | null;
  reliability_enabled: boolean;
}

export interface CheckpointScenarioItem {
  scenario_id: string;
  scenario_version: number;
  name: string;
  category: string;
  enabled: boolean;
  config: Record<string, unknown> | null;
  assertion_overrides: unknown[] | null;
  compatibility: CompatibilityEvaluation;
}

export interface CheckpointWithScenarios extends Checkpoint {
  scenarios: CheckpointScenarioItem[];
}

export interface TaskReliabilityOverview {
  registered_task: RegisteredTask;
  automatic_scenarios: TaskScenarioItem[];
  checkpoints: CheckpointWithScenarios[];
  contract: TaskTestContract | null;
  contract_issues: ContractIssue[];
}

/* ---------------------------------------------------------------- test plans */

export interface TestPlan {
  id: string;
  target_app_id: string;
  name: string;
  description: string | null;
  status: 'DRAFT' | 'VALIDATING' | 'NEEDS_CHANGES' | 'READY_FOR_REVIEW' | 'APPROVED' | string;
  task_ids: string[];
  current_revision: number;
  approved_revision: number | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  ready_for_execution: boolean;
  execution_available: boolean;
}

export interface TestPlanRevision {
  id: string;
  test_plan_id: string;
  revision: number;
  status: string;
  snapshot: Record<string, unknown>;
  summary: Record<string, unknown> | null;
  created_at: string;
  approved_at: string | null;
  invalidated_at: string | null;
}

export interface TestPlanDetail extends TestPlan {
  latest_revision: TestPlanRevision | null;
  duplicates: Record<string, unknown>[];
}

export interface TestPlanTestCase {
  id: string;
  case_key: string;
  status: 'READY' | 'BLOCKED' | string;
  task_name: string;
  scenario_id: string;
  scenario_version: number;
  trigger_type: string;
  checkpoint_name: string | null;
  contract_version: number | null;
  adapter_refs: Record<string, unknown>[];
  test_input: Record<string, unknown> | null;
  input_fixture_ref: string | null;
  assertions: Record<string, unknown>[];
  cleanup: Record<string, unknown> | null;
  scenario_config: Record<string, unknown> | null;
  recovery_policy: Record<string, unknown> | null;
  compatibility: CompatibilityEvaluation;
  configuration_fingerprint: string;
}

export interface TestPlanGenerateResponse {
  plan: TestPlan;
  revision: TestPlanRevision;
  summary: Record<string, unknown>;
  duplicates: Record<string, unknown>[];
}

export interface TestPlanValidation {
  plan: TestPlan;
  revision: number;
  ok: boolean;
  blocking_issues: Record<string, unknown>[];
  drift: Record<string, unknown>[];
  warnings: Record<string, unknown>[];
  total_cases: number;
  ready_cases: number;
  blocked_cases: number;
}

/* ------------------------------------------------------------------- runtime */

export interface RuntimeProfile {
  runtime_type?: 'docker' | 'simulated';
  image?: string | null;
  worker_command?: string[] | null;
  queue: string;
  concurrency?: number;
  broker_image?: string | null;
  database_image?: string | null;
  env?: Record<string, string>;
  http?: {
    input_field?: string | null;
    url_env?: string | null;
    upstream_url?: string | null;
    advertised_host?: string;
  } | null;
  database?: { url_env?: string | null } | null;
}

export interface RunnerCapabilities {
  runner_enabled: boolean;
  runtime_types: Record<string, unknown>;
  supported_scenarios: Record<string, unknown>[];
  limits: Record<string, unknown>;
  isolation: string;
}

export type RunLifecycleState =
  | 'PENDING'
  | 'VALIDATING'
  | 'PROVISIONING'
  | 'PREPARING_FAULT'
  | 'STARTING'
  | 'RUNNING'
  | 'INJECTING'
  | 'OBSERVING_RECOVERY'
  | 'EVALUATING'
  | 'FINALIZING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export type ReliabilityVerdict = 'PASS' | 'FAIL' | 'INCONCLUSIVE' | 'INVALID_RUN' | 'ERROR';

export interface TestCaseRun {
  id: string;
  target_app_id: string;
  test_plan_id: string;
  test_plan_revision_id: string;
  test_plan_test_case_id: string;
  registered_task_id: string;
  case_key: string;
  scenario_id: string;
  scenario_version: number;
  trigger_type: string;
  checkpoint_name: string | null;
  lifecycle_state: RunLifecycleState | string;
  verdict: ReliabilityVerdict | string | null;
  logical_job_id: string;
  celery_task_ids: string[];
  environment_id: string | null;
  error_message: string | null;
  cancel_requested_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  recovery_policy: RecoveryPolicy | Record<string, never>;
}

export interface RunnerEnvironment {
  id: string;
  test_case_run_id: string;
  runtime_type: string;
  namespace: string;
  network_ref: string | null;
  container_refs: Record<string, unknown>[];
  broker_ref: string | null;
  database_ref: string | null;
  proxy_refs: Record<string, unknown>;
  runtime_config_version: string;
  provisioning_state: string;
  readiness: Record<string, unknown> | null;
  error: string | null;
  cleanup_state: string;
  cleanup_error: string | null;
  ready_at: string | null;
  stopped_at: string | null;
  cleaned_at: string | null;
}

export interface RunnerWorker {
  id: string;
  test_case_run_id: string;
  worker_key: string;
  queue_name: string;
  concurrency: number;
  lifecycle_state: string;
  container_ref: string | null;
  hostname: string | null;
  worker_instance_id: string | null;
  started_at: string | null;
  ready_at: string | null;
  terminated_at: string | null;
  termination_reason: string | null;
  exit_info: Record<string, unknown> | null;
  error: string | null;
}

export interface FaultEvent {
  id: string;
  test_case_run_id: string;
  scenario_id: string;
  injector_type: string;
  trigger_type: string;
  trigger_ref: string | null;
  state: 'PREPARING' | 'ARMED' | 'TRIGGERED' | 'ACTIVE' | 'RELEASED' | 'FAILED' | 'SKIPPED' | string;
  detail: Record<string, unknown> | null;
  error: string | null;
  occurred_at: string;
  activation_at: string | null;
  deactivation_at: string | null;
}

export interface RecoveryObservation {
  test_case_run_id: string;
  attempt_count: number;
  retry_request_count: number;
  subsequent_attempt_count: number;
  fault_activated: boolean;
  recovery_duration_ms: number | null;
  final_execution_state: string | null;
  evidence_complete: boolean;
  missing_evidence: string[];
  observation: Record<string, unknown>;
  error: string | null;
}

export interface RuntimeEvent {
  id: string;
  test_case_run_id: string;
  source: string;
  event_type: string;
  payload: Record<string, unknown> | null;
  occurred_at: string;
}

export interface RunVerdict {
  run_id: string;
  lifecycle_state: string;
  verdict: ReliabilityVerdict | string | null;
  detail: Record<string, unknown> | null;
  attempts: number;
  retries: number;
  final_execution_state: string | null;
  evidence_complete: boolean;
  scope: string;
}

export interface ObservedAttempt {
  execution_id: string;
  celery_task_id: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  worker_instance_id: string | null;
  duration_ms: number | null;
}

export interface TestCaseRunDetail {
  run: TestCaseRun;
  configuration: Record<string, unknown>;
  environment: RunnerEnvironment | null;
  workers: RunnerWorker[];
  fault_events: FaultEvent[];
  recovery: RecoveryObservation | null;
  runtime_events: RuntimeEvent[];
  observed_attempts: ObservedAttempt[];
  next: string;
}

export interface StartRunResponse {
  run: TestCaseRun;
  scheduled: boolean;
  next: string;
}

export interface CancelRunResponse {
  run: TestCaseRun;
  message: string;
}
