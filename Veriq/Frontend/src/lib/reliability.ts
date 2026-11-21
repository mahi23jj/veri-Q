import type { RunLifecycleState } from '../api/types';

/** Backend lifecycle progression, in execution order. */
export const LIFECYCLE_STEPS: RunLifecycleState[] = [
  'PENDING',
  'VALIDATING',
  'PROVISIONING',
  'PREPARING_FAULT',
  'STARTING',
  'RUNNING',
  'INJECTING',
  'OBSERVING_RECOVERY',
  'EVALUATING',
  'FINALIZING',
  'COMPLETED',
];

export const TERMINAL_LIFECYCLE_STATES = ['COMPLETED', 'FAILED', 'CANCELLED'];

/**
 * Verdict category explanations. These describe what the backend's verdict
 * means; the authoritative reasons are always rendered from the API payload.
 */
export function verdictExplanation(verdict: string | null): string {
  switch (verdict) {
    case 'PASS':
      return 'The fault was activated and the observed execution recovered within the configured policy. This proves execution-level recovery only.';
    case 'FAIL':
      return 'The fault was activated, but the observed attempts did not satisfy the recovery policy.';
    case 'INCONCLUSIVE':
      return 'VeriQ could not collect sufficient evidence to determine whether recovery occurred.';
    case 'INVALID_RUN':
      return 'The configured failure was never activated, so the intended test did not occur.';
    case 'ERROR':
      return 'VeriQ encountered an infrastructure error that prevented a reliable evaluation.';
    default:
      return 'The run has not produced a reliability verdict yet.';
  }
}
