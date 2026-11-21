import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  Activity,
  ArrowLeft,
  Boxes,
  Clock,
  FileJson,
  FlaskConical,
  Gauge,
  RefreshCw,
  Server,
  ShieldAlert,
  StopCircle,
  TriangleAlert,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import type {
  FaultEvent,
  ObservedAttempt,
  RecoveryObservation,
  RecoveryPolicy,
  RunVerdict,
  TestCaseRunDetail,
} from '../api/types';
import {
  DetailRow,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pill,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { FaultStateBadge, LifecycleProgress, VerdictBadge } from '../components/reliability';
import { TERMINAL_LIFECYCLE_STATES, verdictExplanation } from '../lib/reliability';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import {
  formatDateTime,
  formatDuration,
  formatTime,
  shortId,
} from '../lib/format';
import { prettyJson } from '../lib/json';

interface VerdictReason {
  code?: string;
  message?: string;
}

interface VerdictCheck {
  check?: string;
  ok?: boolean;
  detail?: string;
}

function verdictReasons(verdict: RunVerdict | null): VerdictReason[] {
  const detail = verdict?.detail;
  if (!detail || typeof detail !== 'object') return [];
  const reasons = (detail as { reasons?: unknown }).reasons;
  if (!Array.isArray(reasons)) return [];
  return reasons
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === 'object')
    .map((entry) => ({
      code: typeof entry.code === 'string' ? entry.code : undefined,
      message: typeof entry.message === 'string' ? entry.message : undefined,
    }));
}

function verdictChecks(verdict: RunVerdict | null): VerdictCheck[] {
  const detail = verdict?.detail;
  if (!detail || typeof detail !== 'object') return [];
  const checks = (detail as { checks?: unknown }).checks;
  if (!Array.isArray(checks)) return [];
  return checks
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === 'object')
    .map((entry) => ({
      check: typeof entry.check === 'string' ? entry.check : undefined,
      ok: typeof entry.ok === 'boolean' ? entry.ok : undefined,
      detail: typeof entry.detail === 'string' ? entry.detail : undefined,
    }));
}

function readinessChecks(value: Record<string, unknown> | null): VerdictCheck[] {
  if (!value) return [];
  const checks = value.checks;
  if (!Array.isArray(checks)) return [];
  return checks
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === 'object')
    .map((entry) => ({
      check: typeof entry.name === 'string' ? entry.name : undefined,
      ok: typeof entry.ok === 'boolean' ? entry.ok : undefined,
      detail: typeof entry.detail === 'string' ? entry.detail : undefined,
    }));
}

function attemptDuration(attempt: ObservedAttempt): string {
  if (attempt.duration_ms !== null && attempt.duration_ms !== undefined) {
    return formatDuration(attempt.duration_ms);
  }
  if (!attempt.started_at) return '—';
  const start = new Date(attempt.started_at).getTime();
  const end = attempt.finished_at ? new Date(attempt.finished_at).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return '—';
  return formatDuration(Math.max(0, end - start));
}

export const TestRunDetail: React.FC = () => {
  const { appId, runId } = useParams<{ appId: string; runId: string }>();
  const { application } = useScopedApplication(appId);

  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    if (!appId || !runId) throw new Error('No test run selected');
    const [detail, verdict] = await Promise.all([
      api.getTestRun(appId, runId),
      api.getRunVerdict(appId, runId),
    ]);
    return { detail, verdict };
  }, [appId, runId]);

  const { data, loading, error, reload } = useApiResource(load);
  const run = data?.detail.run;
  const lifecycle = run?.lifecycle_state;
  const active = lifecycle ? !TERMINAL_LIFECYCLE_STATES.includes(lifecycle) : false;

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => reload(), 3000);
    return () => window.clearInterval(timer);
  }, [active, reload]);

  const timeline = useMemo(() => {
    if (!data) return [];
    const events = data.detail.runtime_events.map((event) => ({
      key: `runtime-${event.id}`,
      at: event.occurred_at,
      source: event.source,
      label: event.event_type,
      payload: event.payload,
    }));
    const faults = data.detail.fault_events.map((event: FaultEvent) => ({
      key: `fault-${event.id}`,
      at: event.occurred_at,
      source: 'INJECTOR',
      label: `fault_${event.state.toLowerCase()}`,
      payload: {
        scenario_id: event.scenario_id,
        injector_type: event.injector_type,
        trigger_type: event.trigger_type,
        trigger_ref: event.trigger_ref,
        state: event.state,
        activation_at: event.activation_at,
        deactivation_at: event.deactivation_at,
        error: event.error,
        ...(event.detail ?? {}),
      },
    }));
    return [...events, ...faults].sort(
      (left, right) => new Date(left.at).getTime() - new Date(right.at).getTime(),
    );
  }, [data]);

  const cancel = async () => {
    if (!appId || !runId) return;
    setCancelling(true);
    try {
      const result = await api.cancelTestRun(appId, runId);
      toast.info(result.message);
      setCancelOpen(false);
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not request cancellation');
    } finally {
      setCancelling(false);
    }
  };

  if (!appId || !runId) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <EmptyState title="No test run selected" description="Choose a run from test run history." />
        </div>
      </Layout>
    );
  }

  const detail: TestCaseRunDetail | undefined = data?.detail;
  const verdict = data?.verdict ?? null;
  const environment = detail?.environment ?? null;
  const recovery: RecoveryObservation | null = detail?.recovery ?? null;
  const reasons = verdictReasons(verdict);
  const checks = verdictChecks(verdict);
  const readiness = readinessChecks(environment?.readiness ?? null);
  const configuration = detail?.configuration ?? {};
  const recoveryPolicy = (run?.recovery_policy ?? {}) as Partial<RecoveryPolicy>;
  const caseTaskName =
    typeof configuration.task_name === 'string' ? configuration.task_name : null;

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        <PageHeader
          title={run ? `Run ${shortId(run.id, 12)}` : 'Test run'}
          description={`${run?.case_key ?? 'Test case'} · ${run?.scenario_id ?? 'scenario'} · ${
            application?.name ?? 'application'
          }`}
          eyebrow={
            <Link
              to={`/applications/${appId}/reliability/runs`}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-[#5f745b] hover:text-[#343832]"
            >
              <ArrowLeft className="w-3.5 h-3.5" /> Back to test runs
            </Link>
          }
          actions={
            <>
              {active && (
                <span className="inline-flex items-center gap-1.5 text-[11px] text-[#777A72] font-mono">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#8297AC] animate-pulse" />
                  polling every 3s
                </span>
              )}
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#EFEEE7]"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              {run && !TERMINAL_LIFECYCLE_STATES.includes(run.lifecycle_state) && (
                <button
                  onClick={() => setCancelOpen(true)}
                  disabled={!!run.cancel_requested_at || cancelling}
                  className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-white bg-[#A46F70] hover:bg-[#8f5d5e] rounded-lg disabled:opacity-50"
                  title={
                    run.cancel_requested_at
                      ? 'Cancellation already requested'
                      : 'Request cancellation of this isolated run'
                  }
                >
                  <StopCircle className="w-3.5 h-3.5" />
                  {run.cancel_requested_at ? 'Cancellation requested' : 'Cancel run'}
                </button>
              )}
            </>
          }
        />

        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && !data ? (
          <LoadingState label="Loading run evidence…" />
        ) : (
          <>
            {run && (
              <div className="flex flex-wrap items-center gap-3 p-4 rounded-xl border border-[#E5E1D7] bg-[#FDFCFA]">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-[#777A72] font-semibold">
                    Lifecycle
                  </span>
                  <StatusBadge status={run.lifecycle_state} />
                </div>
                <div className="h-5 w-px bg-[#E5E1D7]" />
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-[#777A72] font-semibold">
                    Reliability verdict
                  </span>
                  <VerdictBadge verdict={run.verdict} large />
                </div>
                <div className="h-5 w-px bg-[#E5E1D7] hidden sm:block" />
                <span className="text-[11px] text-[#777A72] font-mono">
                  trigger {run.trigger_type}
                  {run.checkpoint_name ? ` · ${run.checkpoint_name}` : ''}
                </span>
                {run.cancel_requested_at && (
                  <Pill tone="rose">cancel requested {formatTime(run.cancel_requested_at)}</Pill>
                )}
              </div>
            )}

            {run?.error_message && (
              <div className="p-4 rounded-xl border border-[#A46F70]/30 bg-[#A46F70]/10 flex items-start gap-2.5">
                <TriangleAlert className="w-4 h-4 text-[#A46F70] mt-0.5 shrink-0" />
                <div>
                  <p className="text-xs font-semibold text-[#733e3f]">Runner reported an error</p>
                  <p className="text-[11px] text-[#733e3f]/90 mt-0.5 break-words">
                    {run.error_message}
                  </p>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="space-y-6">
                <SectionCard
                  title="Lifecycle"
                  description="Backend state progression"
                  icon={<Activity className="w-4 h-4 text-[#8297AC]" />}
                >
                  <LifecycleProgress state={run?.lifecycle_state ?? 'PENDING'} />
                  <div className="mt-4 grid grid-cols-1 gap-2">
                    <DetailRow label="Started" mono>
                      {formatDateTime(run?.started_at ?? run?.created_at)}
                    </DetailRow>
                    <DetailRow label="Finished" mono>
                      {formatDateTime(run?.finished_at)}
                    </DetailRow>
                    <DetailRow label="Celery task ids" mono>
                      {run?.celery_task_ids.length
                        ? run.celery_task_ids.join(', ')
                        : 'none observed yet'}
                    </DetailRow>
                  </div>
                </SectionCard>

                <SectionCard
                  title="Verdict"
                  description="Recorded by the backend evaluator"
                  icon={<Gauge className="w-4 h-4 text-[#879B83]" />}
                >
                  <div className="flex items-center gap-2">
                    <VerdictBadge verdict={run?.verdict ?? null} large />
                  </div>
                  <p className="mt-3 text-[11px] text-[#52564e] leading-relaxed">
                    {verdictExplanation(run?.verdict ?? null)}
                  </p>
                  {reasons.length > 0 ? (
                    <ul className="mt-3 space-y-1.5">
                      {reasons.map((reason, index) => (
                        <li key={`${reason.code ?? 'reason'}-${index}`} className="text-[11px] text-[#733e3f] leading-relaxed">
                          <span className="font-mono text-[10px]">{reason.code ?? 'reason'}: </span>
                          {reason.message ?? ''}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-[11px] text-[#777A72]">
                      {run?.verdict ? 'The backend returned no additional reasons.' : 'No verdict yet.'}
                    </p>
                  )}
                  {checks.length > 0 && (
                    <div className="mt-3 space-y-1">
                      {checks.map((check, index) => (
                        <div
                          key={`${check.check ?? 'check'}-${index}`}
                          className={`text-[11px] ${check.ok ? 'text-[#3e563a]' : 'text-[#733e3f]'}`}
                        >
                          {check.ok ? '✓' : '✕'} {check.check ?? 'check'}
                          {check.detail ? ` — ${check.detail}` : ''}
                        </div>
                      ))}
                    </div>
                  )}
                  <p className="mt-3 pt-3 border-t border-[#E5E1D7] text-[10px] text-[#777A72] leading-relaxed">
                    Scope: execution-level recovery only. A PASS does not prove payment correctness,
                    exactly-once delivery, absence of duplicate business effects or overall business-data
                    correctness.
                  </p>
                </SectionCard>

                <SectionCard
                  title="Environment"
                  description="Isolated runner resources and cleanup"
                  icon={<Boxes className="w-4 h-4 text-[#8297AC]" />}
                >
                  {!environment ? (
                    <p className="text-[11px] text-[#777A72]">
                      No environment has been provisioned for this run yet.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-2">
                        <DetailRow label="Runtime" mono>
                          {environment.runtime_type}
                        </DetailRow>
                        <DetailRow label="Provisioning">{environment.provisioning_state}</DetailRow>
                        <DetailRow label="Cleanup">{environment.cleanup_state}</DetailRow>
                        <DetailRow label="Ready at" mono>
                          {formatDateTime(environment.ready_at)}
                        </DetailRow>
                      </div>
                      {environment.error && (
                        <p className="text-[11px] text-[#733e3f]">{environment.error}</p>
                      )}
                      {environment.cleanup_error && (
                        <p className="text-[11px] text-[#733e3f]">
                          Cleanup error: {environment.cleanup_error}
                        </p>
                      )}
                      {readiness.length > 0 ? (
                        <div className="pt-2">
                          <span className="text-[10px] uppercase tracking-wider text-[#777A72] font-semibold">
                            Readiness checks
                          </span>
                          <div className="mt-1 space-y-1">
                            {readiness.map((check, index) => (
                              <div
                                key={`${check.check ?? 'check'}-${index}`}
                                className={`text-[11px] ${check.ok ? 'text-[#3e563a]' : 'text-[#733e3f]'}`}
                              >
                                {check.ok ? '✓' : '✕'} {check.check ?? 'check'}
                                {check.detail ? ` — ${check.detail}` : ''}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        environment.readiness && (
                          <pre className="p-2.5 rounded-lg bg-[#FAF8F3] border border-[#E5E1D7] text-[10px] font-mono overflow-x-auto">
                            {prettyJson(environment.readiness)}
                          </pre>
                        )
                      )}
                      <p className="text-[10px] text-[#777A72]">
                        Cleaned at {formatDateTime(environment.cleaned_at)} · stopped at{' '}
                        {formatDateTime(environment.stopped_at)}
                      </p>
                    </div>
                  )}
                </SectionCard>
              </div>

              <div className="lg:col-span-2 space-y-6">
                <SectionCard
                  title="Failure injection"
                  description="Configured is not activated: ARMED means prepared, ACTIVE means the trigger matched"
                  icon={<ShieldAlert className="w-4 h-4 text-[#A46F70]" />}
                  bodyClassName="p-0"
                >
                  {(detail?.fault_events.length ?? 0) === 0 ? (
                    <div className="p-5">
                      <EmptyState
                        icon={<ShieldAlert className="w-5 h-5" />}
                        title="No fault events yet"
                        description="Fault preparation and activation are recorded as the runner reaches each stage."
                      />
                    </div>
                  ) : (
                    <div className="divide-y divide-[#E5E1D7]">
                      {detail?.fault_events.map((fault) => (
                        <div key={fault.id} className="px-5 py-3 space-y-1.5">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs font-semibold text-[#343832] font-mono">
                                {fault.scenario_id}
                              </span>
                              <FaultStateBadge state={fault.state} />
                              <Pill tone="muted">{fault.injector_type}</Pill>
                              <Pill tone="muted">trigger {fault.trigger_type}</Pill>
                            </div>
                            <span className="text-[10px] text-[#777A72] font-mono">
                              {formatDateTime(fault.occurred_at)}
                            </span>
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-[10px] text-[#777A72]">
                            <span>
                              activation: <span className="font-mono">{formatTime(fault.activation_at)}</span>
                            </span>
                            <span>
                              deactivation: <span className="font-mono">{formatTime(fault.deactivation_at)}</span>
                            </span>
                            <span>
                              trigger ref: <span className="font-mono">{fault.trigger_ref ?? '—'}</span>
                            </span>
                          </div>
                          {fault.error && (
                            <p className="text-[11px] text-[#733e3f]">Injector error: {fault.error}</p>
                          )}
                          {fault.detail && (
                            <details>
                              <summary className="text-[10px] text-[#777A72] cursor-pointer">
                                Injector detail
                              </summary>
                              <pre className="mt-1 p-2 rounded bg-[#FAF8F3] border border-[#E5E1D7] text-[10px] font-mono overflow-x-auto">
                                {prettyJson(fault.detail)}
                              </pre>
                            </details>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </SectionCard>

                <SectionCard
                  title="Execution attempts"
                  description="Correlated ordinary task executions reported by the SDK"
                  icon={<Activity className="w-4 h-4 text-[#8297AC]" />}
                  bodyClassName="p-0"
                >
                  {(detail?.observed_attempts.length ?? 0) === 0 ? (
                    <div className="p-5">
                      <EmptyState
                        icon={<Activity className="w-5 h-5" />}
                        title="No observed attempts"
                        description="Attempts appear once the isolated worker reports task execution events through the SDK."
                      />
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-[#FAF8F3] text-[10px] uppercase tracking-wider text-[#777A72]">
                          <tr>
                            <th className="px-5 py-2 font-semibold">Observed order</th>
                            <th className="px-3 py-2 font-semibold">status</th>
                            <th className="px-3 py-2 font-semibold">Celery task</th>
                            <th className="px-3 py-2 font-semibold">Execution</th>
                            <th className="px-3 py-2 font-semibold">Worker</th>
                            <th className="px-3 py-2 font-semibold">Started</th>
                            <th className="px-3 py-2 font-semibold">Duration</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#E5E1D7]">
                          {detail?.observed_attempts.map((attempt, index) => (
                            <tr key={attempt.execution_id} className="hover:bg-[#FAF8F3]">
                              <td className="px-5 py-2.5 font-mono text-[11px] text-[#52564e]">
                                #{index + 1}
                              </td>
                              <td className="px-3 py-2.5">
                                <StatusBadge status={attempt.status} />
                              </td>
                              <td className="px-3 py-2.5 font-mono text-[10.5px] text-[#52564e] max-w-[160px] truncate">
                                {attempt.celery_task_id ?? '—'}
                              </td>
                              <td className="px-3 py-2.5">
                                <Link
                                  to={`/applications/${appId}/executions/${attempt.execution_id}`}
                                  className="font-mono text-[10.5px] text-[#5f745b] hover:text-[#343832]"
                                >
                                  {shortId(attempt.execution_id, 10)}
                                </Link>
                              </td>
                              <td className="px-3 py-2.5 font-mono text-[10.5px] text-[#52564e] max-w-[140px] truncate">
                                {attempt.worker_instance_id ?? '—'}
                              </td>
                              <td className="px-3 py-2.5 text-[11px] text-[#777A72] whitespace-nowrap">
                                {formatDateTime(attempt.started_at)}
                              </td>
                              <td className="px-3 py-2.5 font-mono text-[11px] text-[#52564e]">
                                {attemptDuration(attempt)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <p className="px-5 py-2.5 text-[10px] text-[#777A72] border-t border-[#E5E1D7]">
                    Order follows the backend's correlated attempt list. Retry requests are counted
                    separately from subsequent attempts below.
                  </p>
                </SectionCard>

                <SectionCard
                  title="Recovery observations"
                  description="Retry requests and later attempts are distinct measurements"
                  icon={<Clock className="w-4 h-4 text-[#8297AC]" />}
                >
                  {!recovery ? (
                    <p className="text-[11px] text-[#777A72]">
                      The evaluator has not recorded a recovery observation yet.
                    </p>
                  ) : (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      <DetailRow label="Attempts">{recovery.attempt_count}</DetailRow>
                      <DetailRow label="Retry requests">{recovery.retry_request_count}</DetailRow>
                      <DetailRow label="Subsequent attempts">
                        {recovery.subsequent_attempt_count}
                      </DetailRow>
                      <DetailRow label="Recovery duration" mono>
                        {formatDuration(recovery.recovery_duration_ms)}
                      </DetailRow>
                      <DetailRow label="Recovery deadline" mono>
                        {recoveryPolicy.recovery_deadline_seconds
                          ? `${recoveryPolicy.recovery_deadline_seconds}s`
                          : '—'}
                      </DetailRow>
                      <DetailRow label="Fault activated">
                        {recovery.fault_activated ? 'Yes' : 'No'}
                      </DetailRow>
                      <DetailRow label="Final task state">
                        {recovery.final_execution_state ?? '—'}
                      </DetailRow>
                      <DetailRow label="Evidence complete">
                        {recovery.evidence_complete ? 'Yes' : 'No'}
                      </DetailRow>
                      <DetailRow label="Missing evidence">
                        {recovery.missing_evidence.length > 0
                          ? recovery.missing_evidence.join(', ')
                          : 'none'}
                      </DetailRow>
                      {recovery.error && (
                        <div className="col-span-2 md:col-span-4">
                          <p className="text-[11px] text-[#733e3f]">Observation error: {recovery.error}</p>
                        </div>
                      )}
                      <div className="col-span-2 md:col-span-4">
                        <details>
                          <summary className="text-[10px] text-[#777A72] cursor-pointer">
                            Observation payload
                          </summary>
                          <pre className="mt-1 p-2.5 rounded-lg bg-[#FAF8F3] border border-[#E5E1D7] text-[10px] font-mono overflow-x-auto">
                            {prettyJson(recovery.observation)}
                          </pre>
                        </details>
                      </div>
                    </div>
                  )}
                </SectionCard>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SectionCard
                title="Timeline"
                description="Runtime and injector events ordered by their backend timestamps"
                icon={<Clock className="w-4 h-4 text-[#8297AC]" />}
                bodyClassName="p-0"
              >
                {timeline.length === 0 ? (
                  <div className="p-5">
                    <EmptyState
                      icon={<Clock className="w-5 h-5" />}
                      title="No timeline events"
                      description="The runner records events as it provisions, injects and observes."
                    />
                  </div>
                ) : (
                  <ol className="divide-y divide-[#E5E1D7]">
                    {timeline.map((event) => (
                      <li key={event.key} className="px-5 py-2.5">
                        <div className="flex items-start gap-3">
                          <span className="font-mono text-[10px] text-[#777A72] pt-0.5 w-16 shrink-0">
                            {formatTime(event.at)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-[11px] font-medium text-[#343832]">
                                {event.label.replace(/_/g, ' ')}
                              </span>
                              <Pill tone="muted">{event.source}</Pill>
                            </div>
                            {event.payload && Object.keys(event.payload).length > 0 && (
                              <details className="mt-0.5">
                                <summary className="text-[10px] text-[#777A72] cursor-pointer">
                                  payload
                                </summary>
                                <pre className="mt-1 p-2 rounded bg-[#FAF8F3] border border-[#E5E1D7] text-[10px] font-mono overflow-x-auto">
                                  {prettyJson(event.payload)}
                                </pre>
                              </details>
                            )}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </SectionCard>

              <SectionCard
                title="Configuration snapshot"
                description="Frozen at run creation from the approved revision"
                icon={<FileJson className="w-4 h-4 text-[#8297AC]" />}
              >
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <DetailRow label="Case" mono>
                    {run?.case_key ?? '—'}
                  </DetailRow>
                  <DetailRow label="Scenario" mono>
                    {run?.scenario_id ?? '—'}
                  </DetailRow>
                  <DetailRow label="Task" mono>
                    {caseTaskName ?? shortId(run?.registered_task_id, 12)}
                  </DetailRow>
                  <DetailRow label="Plan revision" mono>
                    {shortId(run?.test_plan_revision_id, 10)}
                  </DetailRow>
                </div>
                <pre className="p-3 rounded-lg bg-[#FAF8F3] border border-[#E5E1D7] text-[10px] font-mono overflow-x-auto max-h-72">
                  {prettyJson(configuration)}
                </pre>
              </SectionCard>
            </div>

            <SectionCard
              title="Dedicated workers"
              description="Runner-managed workers for this isolated environment"
              icon={<Server className="w-4 h-4 text-[#8297AC]" />}
              bodyClassName="p-0"
            >
              {(detail?.workers.length ?? 0) === 0 ? (
                <div className="p-5">
                  <EmptyState
                    icon={<Server className="w-5 h-5" />}
                    title="No dedicated worker yet"
                    description="A worker is created when the run reaches provisioning."
                  />
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-[#FAF8F3] text-[10px] uppercase tracking-wider text-[#777A72]">
                      <tr>
                        <th className="px-5 py-2 font-semibold">Worker</th>
                        <th className="px-3 py-2 font-semibold">Queue</th>
                        <th className="px-3 py-2 font-semibold">State</th>
                        <th className="px-3 py-2 font-semibold">Started</th>
                        <th className="px-3 py-2 font-semibold">Ready</th>
                        <th className="px-3 py-2 font-semibold">Terminated</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#E5E1D7]">
                      {detail?.workers.map((worker) => (
                        <tr key={worker.id}>
                          <td className="px-5 py-2.5 font-mono text-[11px] text-[#52564e]">
                            {worker.hostname ?? worker.worker_key}
                            {worker.error && (
                              <div className="text-[10px] text-[#733e3f]">{worker.error}</div>
                            )}
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[11px] text-[#52564e]">
                            {worker.queue_name}
                          </td>
                          <td className="px-3 py-2.5">
                            <StatusBadge status={worker.lifecycle_state} />
                          </td>
                          <td className="px-3 py-2.5 text-[11px] text-[#777A72]">
                            {formatDateTime(worker.started_at)}
                          </td>
                          <td className="px-3 py-2.5 text-[11px] text-[#777A72]">
                            {formatDateTime(worker.ready_at)}
                          </td>
                          <td className="px-3 py-2.5 text-[11px] text-[#777A72]">
                            {formatDateTime(worker.terminated_at)}
                            {worker.termination_reason && (
                              <div className="text-[10px]">{worker.termination_reason}</div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>

            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#777A72]">
              <Link
                to={`/applications/${appId}/executions`}
                className="inline-flex items-center gap-1.5 font-medium text-[#5f745b] hover:text-[#343832]"
              >
                <FlaskConical className="w-3.5 h-3.5" /> Ordinary execution telemetry
              </Link>
              <span className="font-mono">run {run?.id}</span>
            </div>
          </>
        )}
      </div>

      <ConfirmationDialog
        isOpen={cancelOpen}
        title="Cancel this isolated test run?"
        message="VeriQ will release the injected fault, stop the dedicated worker and remove the isolated environment. The run is not marked cancelled locally; the backend confirms the transition and cleanup is reported below."
        confirmLabel="Request cancellation"
        isDestructive
        isBusy={cancelling}
        onConfirm={cancel}
        onCancel={() => setCancelOpen(false)}
      />
    </Layout>
  );
};

export default TestRunDetail;
