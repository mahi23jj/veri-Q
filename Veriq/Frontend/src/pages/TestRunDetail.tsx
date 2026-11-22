import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  ArrowLeft,
  Boxes,
  Bug,
  Clock,
  FileJson,
  FlaskConical,
  Gauge,
  ListTree,
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
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pill,
  StatusBadge,
} from '../components/ui';
import { LifecycleProgress } from '../components/reliability';
import { CollapsibleSection, InfoHint } from '../components/Collapsible';
import {
  TERMINAL_LIFECYCLE_STATES,
  verdictExplanation,
} from '../lib/reliability';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import { formatDateTime, formatDuration, formatTime, shortId } from '../lib/format';
import { prettyJson } from '../lib/json';

/* ------------------------------------------------------------------ verdict */

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

/* ------------------------------------------------------------------- tokens */

type Tone = 'green' | 'coral' | 'yellow' | 'blue' | 'gray';

const TONE_DOT: Record<Tone, string> = {
  green: 'bg-[#F0F6FC]',
  coral: 'bg-[#F0F6FC]',
  yellow: 'bg-[#F0F6FC]',
  blue: 'bg-[#F0F6FC]',
  gray: 'bg-[#F0F6FC]',
};

const TONE_TEXT: Record<Tone, string> = {
  green: 'text-[#F0F6FC]',
  coral: 'text-[#F0F6FC]',
  yellow: 'text-[#F0F6FC]',
  blue: 'text-[#F0F6FC]',
  gray: 'text-[#F0F6FC]',
};

const STATUS_BADGE: Record<Tone, string> = {
  green: 'bg-[#3FB950]/15 text-[#56D364] border-[#3FB950]/40',
  coral: 'bg-[#F85149]/15 text-[#FF7B72] border-[#F85149]/45',
  yellow: 'bg-[#D29922]/15 text-[#F0F6FC] border-[#D29922]/45',
  blue: 'bg-[#58A6FF]/15 text-[#F0F6FC] border-[#58A6FF]/40',
  gray: 'bg-[#6E7681]/15 text-[#F0F6FC] border-[#6E7681]/40',
};

function verdictTone(verdict: string | null): Tone {
  switch (verdict) {
    case 'PASS':
      return 'green';
    case 'FAIL':
    case 'ERROR':
      return 'coral';
    case 'INCONCLUSIVE':
    case 'INVALID_RUN':
      return 'yellow';
    default:
      return 'gray';
  }
}

function lifecycleTone(state: string | null | undefined): Tone {
  switch (state) {
    case 'COMPLETED':
      return 'green';
    case 'FAILED':
      return 'coral';
    case 'CANCELLED':
      return 'gray';
    case 'PENDING':
      return 'gray';
    default:
      return 'yellow';
  }
}

function statusHeadline(run: {
  verdict: string | null;
  lifecycle_state: string;
}): { label: string; tone: Tone } {
  if (run.verdict) {
    return { label: run.verdict.replace(/_/g, ' '), tone: verdictTone(run.verdict) };
  }
  return {
    label: run.lifecycle_state.replace(/_/g, ' '),
    tone: lifecycleTone(run.lifecycle_state),
  };
}

/* --------------------------------------------------------------- narratives */

interface NarrativeItem {
  key: string;
  at: string;
  title: string;
  tone: Tone;
  detail?: string;
  workerId?: string | null;
  executionId?: string;
}

const FAULT_LABEL: Record<string, string> = {
  PREPARING: 'Fault preparing',
  ARMED: 'Fault armed',
  TRIGGERED: 'Fault triggered',
  ACTIVE: 'Fault injected',
  RELEASED: 'Fault released',
  FAILED: 'Fault injection failed',
  SKIPPED: 'Fault not triggered',
};

const FAULT_TONE: Record<string, Tone> = {
  PREPARING: 'yellow',
  ARMED: 'yellow',
  TRIGGERED: 'yellow',
  ACTIVE: 'yellow',
  RELEASED: 'green',
  FAILED: 'coral',
  SKIPPED: 'gray',
};

const ATTEMPT_TONE: Record<string, Tone> = {
  SUCCEEDED: 'green',
  FAILED: 'coral',
  RETRYING: 'yellow',
  RUNNING: 'yellow',
};

function attemptDuration(attempt: ObservedAttempt): string {
  if (attempt.duration_ms !== null && attempt.duration_ms !== undefined) {
    return formatDuration(attempt.duration_ms);
  }
  if (!attempt.started_at) return '';
  const start = new Date(attempt.started_at).getTime();
  const end = attempt.finished_at ? new Date(attempt.finished_at).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return '';
  return formatDuration(Math.max(0, end - start));
}

function humanizeCheck(name: string | undefined): string {
  if (!name) return 'Check';
  if (name === 'RECOVERY_POLICY_SATISFIED') return 'Recovery policy met';
  const words = name.replace(/_/g, ' ').toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/* ------------------------------------------------------------------- pieces */

const Metric: React.FC<{
  label: string;
  value: React.ReactNode;
  muted?: boolean;
}> = ({ label, value, muted }) => (
  <div className="flex items-baseline gap-1.5 whitespace-nowrap">
    <span className="text-[11px] text-[#F0F6FC]">{label}</span>
    <span
      className={`text-sm font-semibold ${muted ? 'text-[#F0F6FC]' : 'text-[#F0F6FC]'}`}
    >
      {value}
    </span>
  </div>
);

const Stat: React.FC<{ label: string; value: React.ReactNode; tone?: Tone }> = ({
  label,
  value,
  tone,
}) => (
  <div>
    <dt className="text-[10px] font-semibold uppercase tracking-wider text-[#F0F6FC]">
      {label}
    </dt>
    <dd
      className={`mt-1 font-mono text-base font-semibold ${
        tone ? TONE_TEXT[tone] : 'text-[#F0F6FC]'
      }`}
    >
      {value}
    </dd>
  </div>
);

/* --------------------------------------------------------------------- page */

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

  const detail: TestCaseRunDetail | undefined = data?.detail;
  const verdict = data?.verdict ?? null;
  const environment = detail?.environment ?? null;
  const recovery: RecoveryObservation | null = detail?.recovery ?? null;
  const reasons = useMemo(() => verdictReasons(verdict), [verdict]);
  const checks = useMemo(() => verdictChecks(verdict), [verdict]);
  const readiness = useMemo(
    () => readinessChecks(environment?.readiness ?? null),
    [environment?.readiness],
  );
  const faults = useMemo(() => detail?.fault_events ?? [], [detail?.fault_events]);
  const attempts = useMemo(
    () => detail?.observed_attempts ?? [],
    [detail?.observed_attempts],
  );

  const recoveryPolicy = (run?.recovery_policy ?? {}) as Partial<RecoveryPolicy>;
  const configuration = detail?.configuration ?? {};
  const caseTaskName =
    typeof configuration.task_name === 'string' ? configuration.task_name : null;

  const faultActivated = useMemo(() => {
    if (recovery) return recovery.fault_activated;
    return faults.some((event) => ['ACTIVE', 'TRIGGERED', 'RELEASED'].includes(event.state));
  }, [faults, recovery]);

  const durationMs = useMemo(() => {
    const start = run?.started_at ?? run?.created_at;
    if (!start) return null;
    const started = new Date(start).getTime();
    const ended = run?.finished_at ? new Date(run.finished_at).getTime() : Date.now();
    if (Number.isNaN(started) || Number.isNaN(ended)) return null;
    return Math.max(0, ended - started);
  }, [run?.created_at, run?.finished_at, run?.started_at]);

  const narrative = useMemo<NarrativeItem[]>(() => {
    if (!run) return [];
    const items: NarrativeItem[] = [];
    const start = run.started_at ?? run.created_at;
    if (start) {
      items.push({
        key: 'run-started',
        at: start,
        title: 'Run started',
        tone: 'blue',
        detail: `${run.case_key} · ${run.scenario_id}`,
      });
    }
    if (environment?.ready_at) {
      items.push({
        key: 'environment-ready',
        at: environment.ready_at,
        title: 'Environment ready',
        tone: 'blue',
        detail: [environment.runtime_type, environment.provisioning_state]
          .filter(Boolean)
          .join(' · '),
      });
    }
    for (const fault of faults) {
      const at =
        fault.state === 'ACTIVE'
          ? fault.activation_at ?? fault.occurred_at
          : fault.occurred_at;
      if (!at) continue;
      items.push({
        key: `fault-${fault.id}`,
        at,
        title: FAULT_LABEL[fault.state] ?? `Fault ${fault.state.toLowerCase()}`,
        tone: FAULT_TONE[fault.state] ?? 'gray',
        detail: [fault.injector_type, fault.trigger_type ? `${fault.trigger_type} trigger` : null]
          .filter(Boolean)
          .join(' · '),
      });
    }
    attempts.forEach((attempt, index) => {
      const order = index + 1;
      if (attempt.started_at) {
        items.push({
          key: `attempt-${attempt.execution_id}-start`,
          at: attempt.started_at,
          title: `Attempt ${order} started`,
          tone: 'blue',
          detail: attempt.status,
          workerId: attempt.worker_instance_id,
          executionId: attempt.execution_id,
        });
      }
      if (attempt.finished_at) {
        const duration = attemptDuration(attempt);
        items.push({
          key: `attempt-${attempt.execution_id}-end`,
          at: attempt.finished_at,
          title: `Attempt ${order} ${attempt.status.toLowerCase()}`,
          tone: ATTEMPT_TONE[attempt.status] ?? 'gray',
          detail: duration ? `took ${duration}` : undefined,
          workerId: attempt.worker_instance_id,
          executionId: attempt.execution_id,
        });
      }
    });
    if (run.finished_at) {
      items.push({
        key: 'run-finished',
        at: run.finished_at,
        title: run.verdict ? `Finished · ${run.verdict.replace(/_/g, ' ')}` : 'Run finished',
        tone: run.verdict ? verdictTone(run.verdict) : lifecycleTone(run.lifecycle_state),
        detail: environment?.cleanup_state
          ? `environment ${environment.cleanup_state.toLowerCase()}`
          : undefined,
      });
    }
    return items
      .map((item, index) => ({ item, index }))
      .sort((left, right) => {
        const delta =
          new Date(left.item.at).getTime() - new Date(right.item.at).getTime();
        return delta !== 0 ? delta : left.index - right.index;
      })
      .map(({ item }) => item);
  }, [attempts, environment, faults, run]);

  const rawEvents = useMemo(() => {
    if (!detail) return [];
    return [...detail.runtime_events].sort(
      (left, right) =>
        new Date(left.occurred_at).getTime() - new Date(right.occurred_at).getTime(),
    );
  }, [detail]);

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

  const headline = run ? statusHeadline(run) : null;
  const attemptCount = recovery?.attempt_count ?? attempts.length;

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-5">
        <PageHeader
          title={run ? `Run ${shortId(run.id, 12)}` : 'Test run'}
          description={`${run?.case_key ?? 'Test case'} · ${run?.scenario_id ?? 'scenario'} · ${
            application?.name ?? 'application'
          }`}
          eyebrow={
            <Link
              to={`/applications/${appId}/reliability/runs`}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-[#F0F6FC] hover:text-[#F0F6FC]"
            >
              <ArrowLeft className="w-3.5 h-3.5" /> Back to test runs
            </Link>
          }
          actions={
            <>
              {active && (
                <span className="inline-flex items-center gap-1.5 text-[11px] text-[#B1BAC4] font-mono">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#3FB950] animate-pulse" />
                  polling every 3s
                </span>
              )}
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 rounded-lg border border-[#30363D] bg-[#000000] px-3.5 py-2 text-xs font-medium text-[#F0F6FC] hover:bg-[#000000]"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              {run && !TERMINAL_LIFECYCLE_STATES.includes(run.lifecycle_state) && (
                <button
                  onClick={() => setCancelOpen(true)}
                  disabled={!!run.cancel_requested_at || cancelling}
                  className="inline-flex items-center gap-2 rounded-lg bg-[#F85149] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#DA3633] disabled:opacity-50"
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
            {/* ---------------------------------------------------- TL;DR row */}
            {run && headline && (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border border-[#30363D] bg-[#000000] px-4 py-3">
                <div className="min-w-0">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-[#F0F6FC]">
                    Run ID
                  </div>
                  <div
                    className="mt-0.5 font-mono text-sm text-[#F0F6FC]"
                    title={run.id}
                  >
                    {shortId(run.id, 12)}
                  </div>
                </div>

                <span
                  className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-bold ${STATUS_BADGE[headline.tone]}`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[headline.tone]}`} />
                  Status: {headline.label}
                </span>

                <div className="hidden h-7 w-px bg-[#1C2128] sm:block" />

                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <Metric label="Duration" value={formatDuration(durationMs)} />
                  <Metric label="Attempts" value={attemptCount} />
                  <Metric
                    label="Trigger"
                    value={
                      run.trigger_type === 'checkpoint' && run.checkpoint_name
                        ? `${run.trigger_type} · ${run.checkpoint_name}`
                        : run.trigger_type
                    }
                  />
                  <Metric
                    label="Fault activated"
                    value={faultActivated ? 'Yes' : 'No'}
                    muted={!faultActivated}
                  />
                </div>

                {run.cancel_requested_at && (
                  <Pill tone="rose">cancel requested {formatTime(run.cancel_requested_at)}</Pill>
                )}

                <div className="ml-auto shrink-0 text-right">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-[#F0F6FC]">
                    Started
                  </div>
                  <div className="mt-0.5 whitespace-nowrap font-mono text-[10.5px] text-[#F0F6FC]">
                    {formatDateTime(run.started_at ?? run.created_at)}
                  </div>
                </div>
              </div>
            )}

            {run?.error_message && (
              <div className="flex items-start gap-2.5 rounded-xl border border-[#F85149]/30 bg-[#F85149]/10 px-4 py-3">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[#F85149]" />
                <div>
                  <p className="text-xs font-semibold text-[#FF7B72]">Runner reported an error</p>
                  <p className="mt-0.5 break-words text-[11px] text-[#FF7B72]/90">
                    {run.error_message}
                  </p>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
              {/* ------------------------------------------ left: narrative */}
              <div className="space-y-4 lg:col-span-2">
                <section className="rounded-xl border border-[#30363D] bg-[#000000] px-4 py-4">
                  <div className="mb-4 flex items-center justify-between gap-2">
                    <div>
                      <h2 className="text-sm font-semibold text-[#F0F6FC]">Activity</h2>
                      <p className="mt-0.5 text-[11px] text-[#F0F6FC]">
                        What the runner did, in order
                      </p>
                    </div>
                    <IconBadge icon={<ListTree className="h-3.5 w-3.5" />} />
                  </div>

                  {narrative.length === 0 ? (
                    <EmptyState
                      icon={<Clock className="w-5 h-5" />}
                      title="No activity yet"
                      description="The runner records each stage as it runs."
                    />
                  ) : (
                    <ol className="relative space-y-4 border-l border-[#30363D] pl-5">
                      {narrative.map((item) => (
                        <li key={item.key} className="relative">
                          <span
                            aria-hidden="true"
                            className={`absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-[#000000] ${TONE_DOT[item.tone]}`}
                          />
                          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                            <time
                              dateTime={item.at}
                              className="font-mono text-[11px] tabular-nums text-[#F0F6FC]"
                            >
                              {formatTime(item.at)}
                            </time>
                            <span className={`text-[13px] font-semibold ${TONE_TEXT[item.tone]}`}>
                              {item.title}
                            </span>
                          </div>
                          {(item.detail || item.workerId || item.executionId) && (
                            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[#F0F6FC]">
                              {item.detail && <span>{item.detail}</span>}
                              {item.workerId && (
                                <span>
                                  Worker{' '}
                                  <span
                                    className="font-mono text-[#F0F6FC]"
                                    title={item.workerId}
                                  >
                                    {shortId(item.workerId, 8)}
                                  </span>
                                </span>
                              )}
                              {item.executionId && (
                                <Link
                                  to={`/applications/${appId}/executions/${item.executionId}`}
                                  className="font-mono text-[#F0F6FC] hover:underline"
                                >
                                  execution {shortId(item.executionId, 8)}
                                </Link>
                              )}
                            </div>
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
                </section>

                <CollapsibleSection
                  title="Show full lifecycle"
                  description="Backend state progression"
                  icon={<Gauge className="h-4 w-4 text-[#F0F6FC]" />}
                  meta={
                    <span className="font-mono text-[11px] text-[#F0F6FC]">
                      {run?.lifecycle_state ?? 'PENDING'}
                    </span>
                  }
                >
                  <LifecycleProgress state={run?.lifecycle_state ?? 'PENDING'} />
                  <dl className="mt-4 space-y-1.5 text-[11px]">
                    <div className="flex justify-between gap-3">
                      <dt className="text-[#F0F6FC]">Started</dt>
                      <dd className="font-mono text-[#F0F6FC]">
                        {formatTime(run?.started_at ?? run?.created_at)}
                      </dd>
                    </div>
                    {run?.finished_at && (
                      <div className="flex justify-between gap-3">
                        <dt className="text-[#F0F6FC]">Finished</dt>
                        <dd className="font-mono text-[#F0F6FC]">
                          {formatTime(run.finished_at)}
                        </dd>
                      </div>
                    )}
                    {run?.celery_task_ids.length ? (
                      <div className="flex justify-between gap-3">
                        <dt className="text-[#F0F6FC]">Celery task ids</dt>
                        <dd className="truncate font-mono text-[#F0F6FC]" title={run.celery_task_ids.join(', ')}>
                          {run.celery_task_ids.join(', ')}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                </CollapsibleSection>
              </div>

              {/* ------------------------------------------- right: evidence */}
              <div className="space-y-4 lg:col-span-3">
                <section className="rounded-xl border border-[#30363D] bg-[#000000] px-4 py-4">
                  <div className="mb-4 flex items-start justify-between gap-2">
                    <div>
                      <h2 className="text-sm font-semibold text-[#F0F6FC]">
                        Recovery observations
                      </h2>
                      <p className="mt-0.5 text-[11px] text-[#F0F6FC]">
                        Measured by the backend evaluator
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {recovery && (
                        <span
                          className={`rounded border px-2 py-0.5 text-[10px] font-mono font-semibold ${
                            recovery.evidence_complete
                              ? 'border-[#3FB950]/40 bg-[#3FB950]/15 text-[#56D364]'
                              : 'border-[#D29922]/45 bg-[#D29922]/15 text-[#F0F6FC]'
                          }`}
                        >
                          {recovery.evidence_complete ? 'EVIDENCE COMPLETE' : 'EVIDENCE INCOMPLETE'}
                        </span>
                      )}
                      <IconBadge icon={<Clock className="h-3.5 w-3.5" />} />
                    </div>
                  </div>

                  {!recovery ? (
                    <p className="text-[11px] text-[#F0F6FC]">
                      The evaluator has not recorded a recovery observation yet.
                    </p>
                  ) : (
                    <>
                      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
                        <Stat label="Attempts" value={recovery.attempt_count} />
                        <Stat label="Retry requests" value={recovery.retry_request_count} />
                        <Stat
                          label="Recovery time"
                          value={formatDuration(recovery.recovery_duration_ms)}
                        />
                        {recoveryPolicy.recovery_deadline_seconds ? (
                          <Stat
                            label="Deadline"
                            value={`${recoveryPolicy.recovery_deadline_seconds}s`}
                          />
                        ) : (
                          <Stat
                            label="Subsequent attempts"
                            value={recovery.subsequent_attempt_count}
                          />
                        )}
                      </dl>

                      {recovery.missing_evidence.length > 0 && (
                        <p className="mt-3 text-[11px] text-[#F0F6FC]">
                          Missing evidence: {recovery.missing_evidence.join(', ')}
                        </p>
                      )}
                      {recovery.error && (
                        <p className="mt-3 text-[11px] text-[#FF7B72]">
                          Observation error: {recovery.error}
                        </p>
                      )}
                    </>
                  )}

                  {reasons.length > 0 && (
                    <ul className="mt-4 space-y-1 border-t border-[#30363D] pt-3">
                      {reasons.map((reason, index) => (
                        <li
                          key={`${reason.code ?? 'reason'}-${index}`}
                          className={`text-[11px] leading-relaxed ${
                            TONE_TEXT[verdictTone(run?.verdict ?? null)]
                          }`}
                        >
                          <span className="font-mono text-[10px]">{reason.code ?? 'reason'}: </span>
                          {reason.message ?? ''}
                        </li>
                      ))}
                    </ul>
                  )}
                  {checks.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {checks.map((check, index) => (
                        <div
                          key={`${check.check ?? 'check'}-${index}`}
                          className={`text-[11px] ${
                            check.ok ? 'text-[#56D364]' : 'text-[#FF7B72]'
                          }`}
                        >
                          {check.ok ? '✓' : '✕'} {humanizeCheck(check.check)}
                          {check.detail ? ` — ${check.detail}` : ''}
                        </div>
                      ))}
                    </div>
                  )}

                  <p className="mt-3 border-t border-[#30363D] pt-3 text-[10px] leading-relaxed text-[#F0F6FC]">
                    {verdictExplanation(run?.verdict ?? null)} Scope: execution-level recovery
                    only; a PASS does not prove business-data correctness.
                  </p>
                </section>

                <CollapsibleSection
                  title="Failure injection details"
                  description="Debug details"
                  icon={<ShieldAlert className="h-4 w-4 text-[#F85149]" />}
                  meta={
                    <>
                      {faultActivated ? (
                        <span className="rounded border border-[#D29922]/45 bg-[#D29922]/15 px-2 py-0.5 text-[10px] font-mono font-semibold text-[#F0F6FC]">
                          ACTIVATED
                        </span>
                      ) : (
                        <span className="rounded border border-[#6E7681]/40 bg-[#6E7681]/15 px-2 py-0.5 text-[10px] font-mono text-[#F0F6FC]">
                          NOT ACTIVATED
                        </span>
                      )}
                      {faults.length > 0 && (
                        <span className="font-mono text-[11px] text-[#F0F6FC]">
                          {faults.length}
                        </span>
                      )}
                      <InfoHint
                        label="Fault states"
                        text="Configured is not activated: ARMED means the injector is prepared, ACTIVE means the trigger matched and the fault was injected."
                      />
                    </>
                  }
                >
                  {faults.length === 0 ? (
                    <p className="text-[11px] text-[#F0F6FC]">
                      No fault events recorded for this run.
                    </p>
                  ) : (
                    <ul className="space-y-3">
                      {faults.map((fault: FaultEvent) => (
                        <li
                          key={fault.id}
                          className="relative border-l border-[#30363D] pl-4"
                        >
                          <span
                            aria-hidden="true"
                            className={`absolute -left-[5px] top-1.5 h-2 w-2 rounded-full ${
                              TONE_DOT[FAULT_TONE[fault.state] ?? 'gray']
                            }`}
                          />
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs font-semibold text-[#F0F6FC]">
                              {fault.scenario_id}
                            </span>
                            <StatusBadge status={fault.state} />
                            <span className="font-mono text-[11px] text-[#F0F6FC]">
                              {formatTime(fault.occurred_at)}
                            </span>
                          </div>
                          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[#F0F6FC]">
                            {fault.activation_at && (
                              <span>
                                activated{' '}
                                <span className="font-mono text-[#F0F6FC]">
                                  {formatTime(fault.activation_at)}
                                </span>
                              </span>
                            )}
                            {fault.deactivation_at && (
                              <span>
                                released{' '}
                                <span className="font-mono text-[#F0F6FC]">
                                  {formatTime(fault.deactivation_at)}
                                </span>
                              </span>
                            )}
                            {fault.trigger_type && (
                              <span>trigger {fault.trigger_type}</span>
                            )}
                            {fault.trigger_ref && (
                              <span className="font-mono">{fault.trigger_ref}</span>
                            )}
                          </div>
                          {fault.error && (
                            <p className="mt-1 text-[11px] text-[#FF7B72]">
                              Injector error: {fault.error}
                            </p>
                          )}
                          {fault.detail && Object.keys(fault.detail).length > 0 && (
                            <details className="mt-1">
                              <summary className="cursor-pointer text-[10px] text-[#F0F6FC]">
                                injector payload
                              </summary>
                              <pre className="mt-1 overflow-x-auto rounded-lg border border-[#30363D] bg-[#000000] p-2 font-mono text-[10px]">
                                {prettyJson(fault.detail)}
                              </pre>
                            </details>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </CollapsibleSection>

                <CollapsibleSection
                  title="Environment & cleanup"
                  description="Isolated runner resources"
                  icon={<Boxes className="h-4 w-4 text-[#F0F6FC]" />}
                  meta={
                    environment ? (
                      <StatusBadge status={environment.provisioning_state} />
                    ) : undefined
                  }
                >
                  {!environment ? (
                    <p className="text-[11px] text-[#F0F6FC]">
                      No environment has been provisioned for this run yet.
                    </p>
                  ) : (
                    <div className="space-y-3">
                      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-[11px] sm:grid-cols-3">
                        <div>
                          <dt className="text-[#F0F6FC]">Runtime</dt>
                          <dd className="mt-0.5 font-mono text-[#F0F6FC]">
                            {environment.runtime_type}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-[#F0F6FC]">Cleanup</dt>
                          <dd className="mt-0.5 text-[#F0F6FC]">{environment.cleanup_state}</dd>
                        </div>
                        {environment.ready_at && (
                          <div>
                            <dt className="text-[#F0F6FC]">Ready</dt>
                            <dd className="mt-0.5 font-mono text-[#F0F6FC]">
                              {formatTime(environment.ready_at)}
                            </dd>
                          </div>
                        )}
                        {environment.cleaned_at && (
                          <div>
                            <dt className="text-[#F0F6FC]">Cleaned</dt>
                            <dd className="mt-0.5 font-mono text-[#F0F6FC]">
                              {formatTime(environment.cleaned_at)}
                            </dd>
                          </div>
                        )}
                        {environment.stopped_at && (
                          <div>
                            <dt className="text-[#F0F6FC]">Stopped</dt>
                            <dd className="mt-0.5 font-mono text-[#F0F6FC]">
                              {formatTime(environment.stopped_at)}
                            </dd>
                          </div>
                        )}
                      </dl>

                      {environment.error && (
                        <p className="text-[11px] text-[#FF7B72]">{environment.error}</p>
                      )}
                      {environment.cleanup_error && (
                        <p className="text-[11px] text-[#FF7B72]">
                          Cleanup error: {environment.cleanup_error}
                        </p>
                      )}

                      {readiness.length > 0 && (
                        <div>
                          <span className="text-[10px] font-semibold uppercase tracking-wider text-[#F0F6FC]">
                            Readiness
                          </span>
                          <ul className="mt-1.5 space-y-1">
                            {readiness.map((check, index) => (
                              <li
                                key={`${check.check ?? 'check'}-${index}`}
                                className={`text-[11px] ${
                                  check.ok ? 'text-[#56D364]' : 'text-[#FF7B72]'
                                }`}
                              >
                                {check.ok ? '✓' : '✕'} {humanizeCheck(check.check)}
                                {check.detail ? ` — ${check.detail}` : ''}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </CollapsibleSection>

                <CollapsibleSection
                  title="Dedicated workers"
                  description="Runner-managed workers for this environment"
                  icon={<Server className="h-4 w-4 text-[#F0F6FC]" />}
                  meta={
                    <span className="font-mono text-[11px] text-[#F0F6FC]">
                      {detail?.workers.length ?? 0}
                    </span>
                  }
                >
                  {(detail?.workers.length ?? 0) === 0 ? (
                    <p className="text-[11px] text-[#F0F6FC]">
                      No dedicated worker was started for this run.
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="text-[10px] uppercase tracking-wider text-[#F0F6FC]">
                          <tr className="border-b border-[#30363D]">
                            <th className="py-2 pr-3 font-semibold">Worker</th>
                            <th className="px-3 py-2 font-semibold">Queue</th>
                            <th className="px-3 py-2 font-semibold">State</th>
                            <th className="px-3 py-2 font-semibold">Started</th>
                            <th className="px-3 py-2 font-semibold">Ready</th>
                            <th className="py-2 pl-3 font-semibold">Terminated</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#1C2128]">
                          {detail?.workers.map((worker) => (
                            <tr key={worker.id}>
                              <td className="py-2 pr-3">
                                <span className="font-mono text-[11px] text-[#F0F6FC]">
                                  {worker.hostname ?? worker.worker_key}
                                </span>
                                {worker.error && (
                                  <div className="text-[10px] text-[#FF7B72]">{worker.error}</div>
                                )}
                              </td>
                              <td className="px-3 py-2 font-mono text-[11px] text-[#F0F6FC]">
                                {worker.queue_name}
                              </td>
                              <td className="px-3 py-2">
                                <StatusBadge status={worker.lifecycle_state} />
                              </td>
                              <td className="px-3 py-2 font-mono text-[11px] text-[#F0F6FC]">
                                {worker.started_at ? formatTime(worker.started_at) : ''}
                              </td>
                              <td className="px-3 py-2 font-mono text-[11px] text-[#F0F6FC]">
                                {worker.ready_at ? formatTime(worker.ready_at) : ''}
                              </td>
                              <td className="py-2 pl-3 font-mono text-[11px] text-[#F0F6FC]">
                                {worker.terminated_at ? formatTime(worker.terminated_at) : ''}
                                {worker.termination_reason && (
                                  <div className="font-sans text-[10px] text-[#F0F6FC]">
                                    {worker.termination_reason}
                                  </div>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CollapsibleSection>

                <CollapsibleSection
                  title="Configuration snapshot"
                  description="Frozen at run creation from the approved revision"
                  icon={<FileJson className="h-4 w-4 text-[#F0F6FC]" />}
                  meta={
                    <span className="font-mono text-[11px] text-[#F0F6FC]">
                      rev {shortId(run?.test_plan_revision_id, 8)}
                    </span>
                  }
                >
                  <dl className="mb-3 grid grid-cols-2 gap-x-6 gap-y-2 text-[11px] sm:grid-cols-4">
                    <div>
                      <dt className="text-[#F0F6FC]">Case</dt>
                      <dd className="mt-0.5 font-mono text-[#F0F6FC]">{run?.case_key ?? '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-[#F0F6FC]">Scenario</dt>
                      <dd className="mt-0.5 font-mono text-[#F0F6FC]">
                        {run?.scenario_id ?? '—'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[#F0F6FC]">Task</dt>
                      <dd className="mt-0.5 font-mono text-[#F0F6FC] break-all">
                        {caseTaskName ?? shortId(run?.registered_task_id, 12)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[#F0F6FC]">Plan revision</dt>
                      <dd className="mt-0.5 font-mono text-[#F0F6FC]">
                        {shortId(run?.test_plan_revision_id, 10)}
                      </dd>
                    </div>
                  </dl>
                  <pre className="max-h-72 overflow-auto rounded-lg border border-[#30363D] bg-[#000000] p-3 font-mono text-[10px]">
                    {prettyJson(configuration)}
                  </pre>
                </CollapsibleSection>

                <CollapsibleSection
                  title="Raw event log"
                  description="Every runtime event the backend recorded"
                  icon={<Bug className="h-4 w-4 text-[#F0F6FC]" />}
                  meta={
                    <span className="font-mono text-[11px] text-[#F0F6FC]">
                      {rawEvents.length}
                    </span>
                  }
                >
                  {rawEvents.length === 0 ? (
                    <p className="text-[11px] text-[#F0F6FC]">No runtime events recorded.</p>
                  ) : (
                    <ol className="divide-y divide-[#1C2128]">
                      {rawEvents.map((event) => (
                        <li key={event.id} className="py-2 first:pt-0 last:pb-0">
                          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                            <time
                              dateTime={event.occurred_at}
                              className="font-mono text-[11px] tabular-nums text-[#F0F6FC]"
                            >
                              {formatTime(event.occurred_at)}
                            </time>
                            <span className="text-[11px] font-medium text-[#F0F6FC]">
                              {event.event_type.replace(/_/g, ' ')}
                            </span>
                            <span className="font-mono text-[10px] uppercase text-[#F0F6FC]">
                              {event.source}
                            </span>
                          </div>
                          {event.payload && Object.keys(event.payload).length > 0 && (
                            <details className="mt-0.5">
                              <summary className="cursor-pointer text-[10px] text-[#F0F6FC]">
                                payload
                              </summary>
                              <pre className="mt-1 overflow-x-auto rounded-lg border border-[#30363D] bg-[#000000] p-2 font-mono text-[10px]">
                                {prettyJson(event.payload)}
                              </pre>
                            </details>
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
                </CollapsibleSection>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#F0F6FC]">
              <Link
                to={`/applications/${appId}/executions`}
                className="inline-flex items-center gap-1.5 font-medium text-[#F0F6FC] hover:text-[#F0F6FC]"
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
        message="VeriQ will release the injected fault, stop the dedicated worker and remove the isolated environment. The run is not marked cancelled locally; the backend confirms the transition and cleanup is reported in Environment & cleanup."
        confirmLabel="Request cancellation"
        isDestructive
        isBusy={cancelling}
        onConfirm={cancel}
        onCancel={() => setCancelOpen(false)}
      />
    </Layout>
  );
};

const IconBadge: React.FC<{ icon: React.ReactNode }> = ({ icon }) => (
  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-[#30363D] bg-[#000000] text-[#F0F6FC]">
    {icon}
  </span>
);

export default TestRunDetail;
