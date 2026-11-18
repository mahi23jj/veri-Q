import React, { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Flag,
  Info,
  RefreshCw,
  RotateCcw,
  Server,
  TriangleAlert,
  XCircle,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import type { ExecutionEvent, TaskExecutionDetail } from '../api/types';
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
import {
  formatDateTime,
  formatDuration,
  formatRelative,
  formatTime,
  shortId,
  stringifyPayload,
} from '../lib/format';

/** Visual treatment + copy for each event type the backend stores. */
function eventMeta(eventType: string) {
  switch (eventType) {
    case 'TASK_STARTED':
      return {
        label: 'Task started',
        tone: 'bg-[#8297AC]',
        icon: Activity,
        description: 'The worker began executing this attempt.',
      };
    case 'TASK_SUCCEEDED':
      return {
        label: 'Task succeeded',
        tone: 'bg-[#879B83]',
        icon: CheckCircle2,
        description: 'The task returned without raising.',
      };
    case 'TASK_FAILED':
      return {
        label: 'Task failed',
        tone: 'bg-[#A46F70]',
        icon: XCircle,
        description: 'The task raised an exception and this attempt ended.',
      };
    case 'TASK_RETRY_REQUESTED':
      return {
        label: 'Retry requested',
        tone: 'bg-[#D8C8AE]',
        icon: RotateCcw,
        description: 'Celery asked for the task to be retried; a new attempt will follow.',
      };
    case 'TASK_CHECKPOINT':
      return {
        label: 'Checkpoint',
        tone: 'bg-[#8297AC]',
        icon: Flag,
        description: 'The task reported a report-only checkpoint.',
      };
    default:
      return {
        label: eventType,
        tone: 'bg-[#777A72]',
        icon: Info,
        description: 'Reported event.',
      };
  }
}

/** Pull the exception details the SDK records on TASK_FAILED payloads. */
function exceptionDetails(event: ExecutionEvent): { name?: string; message?: string; traceback?: string } | null {
  if (event.event_type !== 'TASK_FAILED' || !event.payload) return null;
  const payload = event.payload as Record<string, unknown>;
  const pick = (key: string) => (typeof payload[key] === 'string' ? (payload[key] as string) : undefined);
  const details = {
    name: pick('exception_type') ?? pick('exception'),
    message: pick('exception_message') ?? pick('message'),
    traceback: pick('traceback'),
  };
  return details.name || details.message || details.traceback ? details : null;
}

function offsetFrom(startedAt: string, occurredAt: string): string {
  const start = new Date(startedAt).getTime();
  const at = new Date(occurredAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(at)) return '';
  const diff = Math.max(0, at - start);
  if (diff < 1000) return `+${diff} ms`;
  return `+${(diff / 1000).toFixed(2)} s`;
}

const TimelineEntry: React.FC<{ event: ExecutionEvent; startedAt: string }> = ({ event, startedAt }) => {
  const [expanded, setExpanded] = useState(event.event_type === 'TASK_FAILED');
  const meta = eventMeta(event.event_type);
  const Icon = meta.icon;
  const exception = exceptionDetails(event);
  const payloadText = stringifyPayload(event.payload);

  return (
    <li className="relative pl-8">
      <span
        className={`absolute left-[3px] top-3 w-4 h-4 rounded-full ${meta.tone} ring-4 ring-[#FDFCFA] flex items-center justify-center`}
      >
        <Icon className="w-2.5 h-2.5 text-white" />
      </span>

      <div className="bg-[#FAF8F3] border border-[#E5E1D7] rounded-xl p-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <span className="text-sm font-semibold text-[#343832]">{meta.label}</span>
            <Pill tone="muted" title={event.event_type}>
              {event.event_type}
            </Pill>
            <Pill tone="blue" title="Source recorded by the backend">
              {event.source}
            </Pill>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-[#777A72] font-mono shrink-0">
            <span>{formatTime(event.occurred_at)}</span>
            <span className="text-[#B3B5AC]">·</span>
            <span title="Offset from the start of this execution">
              {offsetFrom(startedAt, event.occurred_at)}
            </span>
          </div>
        </div>

        <p className="text-xs text-[#61655b] mt-1">{meta.description}</p>

        {exception && (
          <div className="mt-3 p-3 bg-[#A46F70]/10 border border-[#A46F70]/30 rounded-lg">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-[#733e3f] mb-1">
              Exception
            </div>
            <div className="font-mono text-[11.5px] text-[#733e3f] break-words">
              {exception.name ? `${exception.name}: ` : ''}
              {exception.message ?? 'No message reported'}
            </div>
            {exception.traceback && (
              <pre className="mt-2 p-2.5 bg-[#343832] text-[#F7F5EF] rounded-md text-[11px] font-mono overflow-x-auto max-h-64">
                {exception.traceback}
              </pre>
            )}
          </div>
        )}

        {payloadText && (
          <>
            <button
              onClick={() => setExpanded((value) => !value)}
              className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-[#5f745b] hover:text-[#343832]"
            >
              {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              {expanded ? 'Hide payload' : 'Inspect payload'}
            </button>
            {expanded && (
              <pre className="mt-2 p-2.5 bg-white border border-[#E5E1D7] rounded-md text-[11px] font-mono text-[#343832] overflow-x-auto max-w-full">
                {payloadText}
              </pre>
            )}
          </>
        )}
      </div>
    </li>
  );
};

export const ExecutionDetail: React.FC = () => {
  const { appId, executionId } = useParams<{ appId: string; executionId: string }>();

  const loadExecution = useCallback(async () => {
    if (!executionId) throw new Error('No execution selected');
    const [execution, events] = await Promise.all([
      api.getExecution(executionId),
      api.listExecutionEvents(executionId),
    ]);
    return { execution, events } as { execution: TaskExecutionDetail; events: ExecutionEvent[] };
  }, [executionId]);

  const { data, loading, error, reload } = useApiResource(loadExecution);

  const loadAttempts = useCallback(async () => {
    const celeryTaskId = data?.execution.celery_task_id;
    if (!celeryTaskId) return null;
    return api.listExecutions({ celery_task_id: celeryTaskId, limit: 50 });
  }, [data?.execution.celery_task_id]);

  const { data: attempts } = useApiResource(loadAttempts);

  if (!appId || !executionId) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <EmptyState title="No execution selected" description="Open an execution from the history." />
        </div>
      </Layout>
    );
  }

  if (loading && !data) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <LoadingState label="Loading execution and event timeline…" />
        </div>
      </Layout>
    );
  }

  if (!data) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-4">
          <Link
            to={`/applications/${appId}/executions`}
            className="inline-flex items-center gap-1.5 text-xs text-[#777A72] hover:text-[#343832]"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to executions
          </Link>
          <ErrorState message={error ?? 'Execution not found'} onRetry={reload} />
        </div>
      </Layout>
    );
  }

  const { execution, events } = data;
  const orderedEvents = [...events].sort(
    (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
  );
  const terminal = orderedEvents.find(
    (event) => event.event_type === 'TASK_SUCCEEDED' || event.event_type === 'TASK_FAILED',
  );
  const checkpoints = orderedEvents.filter((event) => event.event_type === 'TASK_CHECKPOINT');
  const sameCeleryTaskAttempts = (attempts?.items ?? []).filter((item) => item.id !== execution.id);

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        <div className="space-y-3">
          <Link
            to={`/applications/${appId}/executions`}
            className="inline-flex items-center gap-1.5 text-xs text-[#777A72] hover:text-[#343832]"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to executions
          </Link>

          <PageHeader
            title={execution.task_name}
            description={`Attempt ${shortId(execution.execution_id, 12)} · ${orderedEvents.length} recorded event${
              orderedEvents.length === 1 ? '' : 's'
            }`}
            eyebrow={
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={execution.status} />
                {execution.queue_name && <Pill tone="blue">{execution.queue_name}</Pill>}
                {terminal && (
                  <Pill tone={terminal.event_type === 'TASK_FAILED' ? 'rose' : 'sage'}>
                    terminal: {terminal.event_type}
                  </Pill>
                )}
              </div>
            }
            actions={
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#EFEEE7] transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
            }
          />
        </div>

        {error && <ErrorState message={error} onRetry={reload} />}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          <div className="lg:col-span-2 space-y-6">
            <SectionCard
              title="Execution timeline"
              description="Chronological lifecycle events reported by the SDK"
              icon={<Clock className="w-4 h-4 text-[#8297AC]" />}
              bodyClassName="p-5"
            >
              {orderedEvents.length === 0 ? (
                <EmptyState
                  icon={<Activity className="w-5 h-5" />}
                  title="No events stored for this execution"
                  description="The execution row exists but no lifecycle events were stored. This happens when observation is disabled for the task, or when events were acknowledged but filtered by the backend."
                />
              ) : (
                <ol className="relative space-y-4 border-l border-[#E5E1D7] ml-2 pl-0">
                  {orderedEvents.map((event) => (
                    <TimelineEntry key={event.id} event={event} startedAt={execution.started_at} />
                  ))}
                </ol>
              )}
            </SectionCard>

            {checkpoints.length > 0 && (
              <SectionCard
                title={`Checkpoints reached (${checkpoints.length})`}
                description="Report-only markers emitted by veriq.checkpoint(name)"
                icon={<Flag className="w-4 h-4 text-[#8297AC]" />}
              >
                <div className="space-y-2">
                  {checkpoints.map((event) => {
                    const name =
                      event.payload && typeof event.payload['name'] === 'string'
                        ? (event.payload['name'] as string)
                        : event.payload && typeof event.payload['checkpoint'] === 'string'
                          ? (event.payload['checkpoint'] as string)
                          : 'unnamed checkpoint';
                    return (
                      <div
                        key={event.id}
                        className="flex items-center justify-between gap-3 p-2.5 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg"
                      >
                        <span className="font-mono text-[11.5px] text-[#343832] break-all">{name}</span>
                        <span className="text-[11px] text-[#777A72] font-mono shrink-0">
                          {formatTime(event.occurred_at)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </SectionCard>
            )}

            {sameCeleryTaskAttempts.length > 0 && (
              <SectionCard
                title="Related attempts"
                description={`Other executions sharing Celery task id ${execution.celery_task_id}`}
                icon={<RotateCcw className="w-4 h-4 text-[#8297AC]" />}
                bodyClassName="p-0"
              >
                <div className="divide-y divide-[#E5E1D7]">
                  {sameCeleryTaskAttempts.map((attempt) => (
                    <Link
                      key={attempt.id}
                      to={`/applications/${appId}/executions/${attempt.id}`}
                      className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-[#FAF8F3] transition-colors"
                    >
                      <div className="min-w-0">
                        <div className="text-[11.5px] font-mono text-[#343832]">
                          {shortId(attempt.execution_id, 12)}
                        </div>
                        <div className="text-[11px] text-[#777A72] mt-0.5">
                          {formatDateTime(attempt.started_at)} ·{' '}
                          {attempt.worker_hostname || 'unknown worker'}
                        </div>
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className="text-[11px] font-mono text-[#777A72]">
                          {formatDuration(attempt.duration_ms)}
                        </span>
                        <StatusBadge status={attempt.status} />
                      </div>
                    </Link>
                  ))}
                </div>
              </SectionCard>
            )}
          </div>

          <div className="space-y-6">
            <SectionCard
              title="Execution details"
              description="One row per actual attempt"
              icon={<Server className="w-4 h-4 text-[#8297AC]" />}
            >
              <div className="grid grid-cols-1 gap-2">
                <DetailRow label="Status">
                  <StatusBadge status={execution.status} />
                </DetailRow>
                <DetailRow label="Execution id" mono>
                  {execution.execution_id}
                </DetailRow>
                <DetailRow label="Database id" mono>
                  {execution.id}
                </DetailRow>
                <DetailRow label="Celery task id" mono>
                  {execution.celery_task_id || '—'}
                </DetailRow>
                <DetailRow label="Worker" mono>
                  {execution.worker_hostname || '—'}
                </DetailRow>
                <DetailRow label="Worker instance id" mono>
                  {execution.worker_instance_id || '—'}
                </DetailRow>
                <DetailRow label="PID / process identity" mono>
                  {execution.pid ?? '—'} · {execution.process_start_identity || '—'}
                </DetailRow>
                <DetailRow label="Queue" mono>
                  {execution.queue_name || '—'}
                </DetailRow>
                <DetailRow label="Started">
                  {formatDateTime(execution.started_at)}{' '}
                  <span className="text-[#777A72]">({formatRelative(execution.started_at)})</span>
                </DetailRow>
                <DetailRow label="Finished">
                  {execution.finished_at ? formatDateTime(execution.finished_at) : 'Still running / no terminal event'}
                </DetailRow>
                <DetailRow label="Duration" mono>
                  {formatDuration(execution.duration_ms)}
                </DetailRow>
                <DetailRow label="Registered task id" mono>
                  {execution.registered_task_id || '—'}
                </DetailRow>
                <DetailRow label="Experiment link">
                  {execution.experiment_run_id ? (
                    <span className="font-mono break-all">{execution.experiment_run_id}</span>
                  ) : (
                    'Not linked to an experiment run'
                  )}
                </DetailRow>
              </div>
            </SectionCard>

            <div className="p-4 bg-[#8297AC]/8 border border-[#8297AC]/25 rounded-xl text-xs text-[#3b5168] flex items-start gap-2">
              <TriangleAlert className="w-4 h-4 mt-0.5 shrink-0" />
              <p className="leading-relaxed">
                Execution events are separate from experiment events. This timeline never merges the two,
                and there is no dashboard endpoint yet for experiment run events (they require the
                application API key).
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default ExecutionDetail;
