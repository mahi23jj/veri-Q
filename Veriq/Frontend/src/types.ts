export type Environment = 'production' | 'staging' | 'development' | 'canary';

export type ApplicationStatus = 'healthy' | 'idle' | 'degraded' | 'offline';

export type ExperimentStatus = 'draft' | 'active' | 'paused' | 'completed';

export type Verdict = 'passed' | 'failed' | 'inconclusive' | 'error' | 'cancelled';

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type TimelineEventType =
  | 'setup'
  | 'submission'
  | 'execution'
  | 'checkpoint'
  | 'failure_injection'
  | 'redelivery'
  | 'verification';

export type TimelineEventOutcome = 'ok' | 'warning' | 'failure' | 'injected_fault';

export interface Application {
  id: string;
  name: string;
  description: string;
  environment: Environment;
  framework: string;
  importPath: string;
  defaultTask?: string;
  experimentCount: number;
  createdAt: string;
  status: ApplicationStatus;
}

export interface ExperimentLastRun {
  date: string;
  verdict: Verdict;
  runId: string;
}

export interface Experiment {
  id: string;
  name: string;
  applicationId: string;
  applicationName: string;
  task: string;
  status: ExperimentStatus;
  failureScenario: string;
  checkpoint: string;
  logicalOperationIdTemplate: string;
  timeoutSeconds: number;
  environment: Environment;
  description: string;
  lastRun?: ExperimentLastRun;
  totalRuns: number;
  createdAt: string;
}

export interface TimelineEvent {
  id: string;
  timestamp: string;
  type: TimelineEventType;
  source: string;
  title: string;
  description: string;
  outcome: TimelineEventOutcome;
  payload?: unknown;
}

export interface InvariantResult {
  id: string;
  name: string;
  description: string;
  expected: string;
  actual: string;
  passed: boolean;
  explanation: string;
}

export interface ExperimentRun {
  id: string;
  experimentId: string;
  experimentName: string;
  applicationId: string;
  applicationName: string;
  runNumber: number;
  startTime: string;
  duration: string;
  status: RunStatus;
  verdict: Verdict;
  workerNode: string;
  attemptNumber: number;
  maxAttempts: number;
  logicalOperationId: string;
  events: TimelineEvent[];
  invariants: InvariantResult[];
}

export type ActivityType = 'run_completed' | 'draft_saved' | 'application_added';

export interface ActivityItem {
  id: string;
  timestamp: string;
  title: string;
  description: string;
  type: ActivityType;
  entityId: string;
  badge?: {
    label: string;
    verdict: Verdict;
  };
}