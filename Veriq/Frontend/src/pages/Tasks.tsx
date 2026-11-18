import React, { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  ChevronRight,
  Info,
  ListChecks,
  RefreshCw,
  X,
  Activity,
  Terminal,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import type { TaskCatalogItem, TaskObservationStatus } from '../api/types';
import {
  CodeBlock,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  Pill,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { formatDateTime, formatRelative, shortId } from '../lib/format';

const PAGE_SIZE = 20;

const OBSERVATION_LABELS: Record<TaskObservationStatus, string> = {
  DISCOVERED: 'Discovered',
  OBSERVING: 'Observing',
  DISABLED: 'Disabled',
};

const TaskDetailModal: React.FC<{ taskId: string; appId: string; onClose: () => void }> = ({
  taskId,
  appId,
  onClose,
}) => {
  const loadTask = useCallback(async () => {
    const [task, executions] = await Promise.all([
      api.getRegisteredTask(taskId),
      api.listTaskExecutions(taskId, { limit: 10 }),
    ]);
    return { task, executions };
  }, [taskId]);

  const { data, loading, error, reload } = useApiResource(loadTask);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#343832]/40 backdrop-blur-xs">
      <div className="w-full max-w-2xl max-h-[90vh] bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-xl overflow-hidden flex flex-col">
        <div className="px-5 py-3.5 border-b border-[#E5E1D7] bg-[#FAF8F3] flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-serif font-bold text-base text-[#343832] truncate">
              {data?.task.task_name ?? 'Task'}
            </h2>
            <p className="text-[11px] text-[#777A72]">
              Discovered task metadata and recent execution attempts
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#777A72] hover:text-[#343832] rounded-md hover:bg-[#EFEEE7]"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto space-y-4">
          {loading && !data ? (
            <LoadingState />
          ) : error ? (
            <ErrorState message={error} onRetry={reload} />
          ) : data ? (
            <>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {[
                  ['Observation', <StatusBadge key="s" status={data.task.status} />],
                  ['Discovery source', <span key="v" className="font-mono">{data.task.discovery_source}</span>],
                  ['First seen', formatDateTime(data.task.first_seen_at)],
                  ['Last seen', formatDateTime(data.task.last_seen_at)],
                  ['Discovered at', formatDateTime(data.task.discovered_at)],
                  ['Executions', String(data.task.execution_count)],
                ].map(([label, value], index) => (
                  <div key={index} className="p-2.5 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg">
                    <span className="text-[10px] text-[#777A72] block">{label}</span>
                    <span className="text-[11.5px] text-[#343832] mt-0.5 block break-words">{value}</span>
                  </div>
                ))}
              </div>

              <div>
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                  Queues observed for this task
                </h3>
                {data.task.queue_names.length === 0 ? (
                  <p className="text-xs text-[#777A72]">No queue names have been observed yet.</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {data.task.queue_names.map((queue) => (
                      <Pill key={queue} tone="blue">
                        {queue}
                      </Pill>
                    ))}
                  </div>
                )}
              </div>

              {data.task.task_metadata && Object.keys(data.task.task_metadata).length > 0 && (
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                    Stored task metadata
                  </h3>
                  <pre className="p-3 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg text-[11px] font-mono overflow-x-auto">
                    {JSON.stringify(data.task.task_metadata, null, 2)}
                  </pre>
                </div>
              )}

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[#777A72]">
                    Recent executions for this task
                  </h3>
                  <Link
                    to={`/applications/${appId}/executions?task=${encodeURIComponent(data.task.task_name)}`}
                    className="text-[11px] font-medium text-[#5f745b] hover:text-[#343832]"
                  >
                    View all
                  </Link>
                </div>
                {data.executions.items.length === 0 ? (
                  <p className="text-xs text-[#777A72] p-3 border border-dashed border-[#E5E1D7] rounded-lg">
                    No executions recorded for this task yet.
                  </p>
                ) : (
                  <div className="divide-y divide-[#E5E1D7] border border-[#E5E1D7] rounded-lg overflow-hidden">
                    {data.executions.items.map((execution) => (
                      <Link
                        key={execution.id}
                        to={`/applications/${appId}/executions/${execution.id}`}
                        className="flex items-center justify-between gap-2 px-3 py-2.5 bg-white hover:bg-[#FAF8F3]"
                      >
                        <div className="min-w-0">
                          <div className="text-[11px] text-[#343832]">
                            {formatDateTime(execution.started_at)}
                          </div>
                          <div className="text-[10px] text-[#777A72] font-mono truncate">
                            {execution.worker_hostname || 'unknown worker'} · {shortId(execution.execution_id)}
                          </div>
                        </div>
                        <StatusBadge status={execution.status} />
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
};

export const Tasks: React.FC = () => {
  const { appId } = useParams<{ appId: string }>();
  const { application } = useScopedApplication(appId);
  const [statusFilter, setStatusFilter] = useState<'ALL' | TaskObservationStatus>('ALL');
  const [skip, setSkip] = useState(0);
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [updatingTaskId, setUpdatingTaskId] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    return api.listApplicationTasks(appId, {
      status: statusFilter === 'ALL' ? undefined : statusFilter,
      skip,
      limit: PAGE_SIZE,
    });
  }, [appId, statusFilter, skip]);

  const { data, loading, error, reload } = useApiResource(loadTasks);

  const changeObservation = async (task: TaskCatalogItem, status: TaskObservationStatus) => {
    setUpdatingTaskId(task.id);
    try {
      await api.setTaskObservation(task.id, status);
      toast.success(
        status === 'DISABLED'
          ? `Telemetry disabled for ${task.task_name}`
          : `Observation set to ${OBSERVATION_LABELS[status]} for ${task.task_name}`,
      );
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not update observation');
    } finally {
      setUpdatingTaskId(null);
    }
  };

  if (!appId) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <EmptyState title="No application selected" description="Choose an application first." />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        <PageHeader
          title="Task Catalog"
          description={`Celery tasks discovered in ${application?.name ?? 'this application'}. Discovery is independent of execution telemetry.`}
          eyebrow={
            <span className="text-[11px] text-[#777A72] font-mono">GET /api/v1/registered-tasks</span>
          }
          actions={
            <>
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#EFEEE7] transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <Link
                to="/integration"
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg transition-all"
              >
                <Terminal className="w-3.5 h-3.5" /> Integration guide
              </Link>
            </>
          }
        />

        <details className="bg-[#8297AC]/8 border border-[#8297AC]/25 rounded-xl">
          <summary className="px-4 py-3 cursor-pointer text-xs font-medium text-[#3b5168] flex items-center gap-2">
            <Info className="w-3.5 h-3.5" />
            How does task discovery work?
          </summary>
          <div className="px-4 pb-4 space-y-3">
            <p className="text-xs text-[#52564e] leading-relaxed">
              The SDK reports the names in <span className="font-mono">celery_app.tasks</span> when the
              integration starts. Starting an instrumented Celery application or worker is enough to
              refresh discovery; no dashboard action is required.
            </p>
            <CodeBlock
              label="python"
              code={`from veriq import VeriQ
from veriq.celery import integrate

veriq = VeriQ(api_url="http://localhost:8000", api_key="vq_...")
integrate(celery_app, veriq)  # reports task discovery on startup`}
            />
            <p className="text-[11px] text-[#777A72]">
              Observation status only controls whether ordinary execution telemetry is stored. Tasks
              remain discovered even when observation is disabled.
            </p>
          </div>
        </details>

        {error && <ErrorState message={error} onRetry={reload} />}

        <SectionCard
          title="Discovered tasks"
          description={data ? `${data.total} task${data.total === 1 ? '' : 's'} in this application` : 'Loading…'}
          icon={<ListChecks className="w-4 h-4 text-[#8297AC]" />}
          actions={
            <div className="flex items-center gap-2">
              <label htmlFor="task-status-filter" className="text-[11px] text-[#777A72]">
                Observation
              </label>
              <select
                id="task-status-filter"
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value as 'ALL' | TaskObservationStatus);
                  setSkip(0);
                }}
                className="px-2.5 py-1.5 text-xs bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
              >
                <option value="ALL">All statuses</option>
                <option value="DISCOVERED">Discovered</option>
                <option value="OBSERVING">Observing</option>
                <option value="DISABLED">Disabled</option>
              </select>
            </div>
          }
          bodyClassName="p-0"
        >
          {loading && !data ? (
            <LoadingState label="Loading task catalog…" />
          ) : !data || data.items.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<ListChecks className="w-5 h-5" />}
                title="No tasks discovered"
                description="Discover tasks by starting an instrumented Celery application. If the SDK cannot reach VeriQ, nothing is reported."
                action={
                  <Link
                    to="/integration"
                    className="text-xs font-medium text-[#5f745b] hover:text-[#343832]"
                  >
                    Read the integration guide
                  </Link>
                }
              />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#FAF8F3] text-[10px] uppercase tracking-wider text-[#777A72]">
                    <tr>
                      <th className="px-5 py-2.5 font-semibold">Task name</th>
                      <th className="px-3 py-2.5 font-semibold">Observation</th>
                      <th className="px-3 py-2.5 font-semibold">Executions</th>
                      <th className="px-3 py-2.5 font-semibold">Last execution</th>
                      <th className="px-3 py-2.5 font-semibold">Queues</th>
                      <th className="px-3 py-2.5 font-semibold">Last seen</th>
                      <th className="px-3 py-2.5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E5E1D7]">
                    {data.items.map((task) => (
                      <tr
                        key={task.id}
                        onClick={() => setOpenTaskId(task.id)}
                        className="hover:bg-[#FAF8F3] cursor-pointer transition-colors"
                      >
                        <td className="px-5 py-3 max-w-[320px]">
                          <div className="font-mono text-[11.5px] text-[#343832] truncate" title={task.task_name}>
                            {task.task_name}
                          </div>
                          <div className="text-[10px] text-[#777A72] mt-0.5">
                            Source: {task.discovery_source} · {shortId(task.id)}
                          </div>
                        </td>
                        <td className="px-3 py-3" onClick={(event) => event.stopPropagation()}>
                          <select
                            value={task.status}
                            disabled={updatingTaskId === task.id}
                            onChange={(event) =>
                              void changeObservation(task, event.target.value as TaskObservationStatus)
                            }
                            className="px-2 py-1 text-[11px] bg-white border border-[#E5E1D7] rounded-md focus:outline-none focus:ring-1 focus:ring-[#879B83] disabled:opacity-50"
                            title="Change whether ordinary execution telemetry is stored"
                          >
                            <option value="DISCOVERED">Discovered</option>
                            <option value="OBSERVING">Observing</option>
                            <option value="DISABLED">Disabled</option>
                          </select>
                        </td>
                        <td className="px-3 py-3">
                          <span className="font-mono text-[#343832]">{task.execution_count}</span>
                        </td>
                        <td className="px-3 py-3 whitespace-nowrap">
                          {task.last_execution_at ? (
                            <>
                              <div className="text-[11px] text-[#343832]">
                                {formatRelative(task.last_execution_at)}
                              </div>
                              <div className="mt-0.5">
                                <StatusBadge status={task.last_outcome} />
                              </div>
                            </>
                          ) : (
                            <span className="text-[#777A72]">—</span>
                          )}
                        </td>
                        <td className="px-3 py-3">
                          {task.queue_names.length === 0 ? (
                            <span className="text-[#777A72]">—</span>
                          ) : (
                            <div className="flex flex-wrap gap-1 max-w-[180px]">
                              {task.queue_names.slice(0, 3).map((queue) => (
                                <Pill key={queue} tone="blue">
                                  {queue}
                                </Pill>
                              ))}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-3 text-[11px] text-[#777A72] whitespace-nowrap">
                          {formatRelative(task.last_seen_at)}
                        </td>
                        <td className="px-3 py-3 text-right">
                          <ChevronRight className="w-4 h-4 text-[#777A72] inline" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-5 pb-4">
                <Pagination
                  total={data.total}
                  skip={data.skip}
                  limit={data.limit}
                  onChange={setSkip}
                />
              </div>
            </>
          )}
        </SectionCard>

        <div className="p-4 bg-[#FAF8F3] border border-[#E5E1D7] rounded-xl flex items-start gap-2.5 text-xs text-[#777A72]">
          <Activity className="w-3.5 h-3.5 mt-0.5 text-[#8297AC] shrink-0" />
          <p className="leading-relaxed">
            Execution counts and last outcomes are catalog aggregates computed by the backend. Open a
            task for its recent attempts, or use the Executions page for application-wide history.
          </p>
        </div>
      </div>

      {openTaskId && (
        <TaskDetailModal taskId={openTaskId} appId={appId} onClose={() => setOpenTaskId(null)} />
      )}
    </Layout>
  );
};

export default Tasks;
