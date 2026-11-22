import React, { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Boxes,
  FlaskConical,
  ListChecks,
  Server,
  ShieldCheck,
  Terminal,
  TriangleAlert,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pill,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { formatCount, formatDateTime, formatDuration, formatRelative } from '../lib/format';

export const ApplicationOverview: React.FC = () => {
  const { appId } = useParams<{ appId: string }>();
  const { application, loading: applicationsLoading } = useScopedApplication(appId);

  const loadOverview = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    const [app, tasks, workers, executions, failures, experiments] = await Promise.all([
      api.getApplication(appId),
      api.listApplicationTasks(appId, { limit: 5 }),
      api.listWorkers({ target_app_id: appId, limit: 100 }),
      api.listExecutions({ target_app_id: appId, limit: 6 }),
      api.listExecutions({ target_app_id: appId, status: 'FAILED', limit: 3 }),
      api.listExperiments({ target_app_id: appId, limit: 100 }),
    ]);
    return { app, tasks, workers, executions, failures, experiments };
  }, [appId]);

  const { data, loading, error, reload } = useApiResource(loadOverview);

  if (!appId) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <EmptyState title="No application selected" description="Choose an application from Applications." />
        </div>
      </Layout>
    );
  }

  if (applicationsLoading && !application) {
    return (
      <Layout>
        <LoadingState />
      </Layout>
    );
  }

  if (!application && !loading && !data) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-4">
          <ErrorState
            message={`Application ${appId} was not found. It may have been deleted.`}
            onRetry={reload}
          />
          <Link to="/applications" className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC]">
            Back to applications
          </Link>
        </div>
      </Layout>
    );
  }

  const app = data?.app ?? application;
  const onlineWorkers = data?.workers.items.filter((worker) => worker.status === 'ONLINE').length ?? 0;
  const base = `/applications/${appId}`;

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        <PageHeader
          title={app?.name ?? 'Application overview'}
          description={app?.description ?? 'Tasks, workers and recent execution activity for this application.'}
          eyebrow={
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone="sage">{app?.environment ?? '…'}</Pill>
              <span className="text-[11px] text-[#B1BAC4] font-mono">{appId}</span>
            </div>
          }
          actions={
            <>
              <Link
                to={`${base}/executions`}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors"
              >
                <Activity className="w-3.5 h-3.5" /> Executions
              </Link>
              <Link
                to={`${base}/reliability`}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors"
              >
                <ShieldCheck className="w-3.5 h-3.5" /> Reliability tests
              </Link>
              <Link
                to="/integration"
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg transition-all"
              >
                <Terminal className="w-3.5 h-3.5" /> SDK setup
              </Link>
            </>
          }
        />

        {error && <ErrorState message={error} onRetry={reload} />}

        {loading && !data ? (
          <LoadingState label="Loading application activity…" />
        ) : (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                {
                  label: 'Registered tasks',
                  value: data ? formatCount(data.tasks.total) : '—',
                  hint: 'discovered in Celery',
                  icon: ListChecks,
                  tone: 'text-[#C9D1D9]',
                  to: `${base}/tasks`,
                },
                {
                  label: 'Workers online',
                  value: data ? `${onlineWorkers} / ${data.workers.total}` : '—',
                  hint: 'stale after 120s',
                  icon: Server,
                  tone: 'text-[#C9D1D9]',
                  to: `${base}/workers`,
                },
                {
                  label: 'Executions',
                  value: data ? formatCount(data.executions.total) : '—',
                  hint: 'recorded attempts',
                  icon: Activity,
                  tone: 'text-[#C9D1D9]',
                  to: `${base}/executions`,
                },
                {
                  label: 'Failed executions',
                  value: data ? formatCount(data.failures.total) : '—',
                  hint: 'TASK_FAILED reported',
                  icon: TriangleAlert,
                  tone: 'text-[#F85149]',
                  to: `${base}/executions?status=FAILED`,
                },
              ].map((card) => (
                <Link
                  key={card.label}
                  to={card.to}
                  className="p-5 bg-[#000000] rounded-xl border border-[#30363D] shadow-2xs transition-all hover:border-[#C9D1D9]"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[#B1BAC4]">
                      {card.label}
                    </span>
                    <card.icon className={`w-4 h-4 ${card.tone}`} />
                  </div>
                  <div className="mt-3">
                    <span className="font-serif font-bold text-2xl md:text-3xl text-[#F0F6FC]">
                      {card.value}
                    </span>
                  </div>
                  <span className="text-[11px] text-[#B1BAC4]">{card.hint}</span>
                </Link>
              ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <SectionCard
                className="lg:col-span-2"
                title="Recent executions"
                description="Each row is one actual attempt"
                icon={<Activity className="w-4 h-4 text-[#C9D1D9]" />}
                actions={
                  <Link
                    to={`${base}/executions`}
                    className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC] flex items-center gap-1"
                  >
                    View all <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                }
                bodyClassName="p-0"
              >
                {!data || data.executions.items.length === 0 ? (
                  <div className="p-5">
                    <EmptyState
                      icon={<Activity className="w-5 h-5" />}
                      title="No task executions yet"
                      description="Once an instrumented Celery worker runs a task, its lifecycle events appear here."
                      action={
                        <Link
                          to="/integration"
                          className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
                        >
                          Set up the SDK
                        </Link>
                      }
                    />
                  </div>
                ) : (
                  <div className="divide-y divide-[#30363D]">
                    {data.executions.items.map((execution) => (
                      <Link
                        key={execution.id}
                        to={`${base}/executions/${execution.id}`}
                        className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-[#000000] transition-colors"
                      >
                        <div className="min-w-0">
                          <div className="text-xs font-medium text-[#F0F6FC] font-mono truncate">
                            {execution.task_name}
                          </div>
                          <div className="text-[11px] text-[#B1BAC4] mt-0.5 truncate">
                            {execution.worker_hostname || 'unknown worker'} ·{' '}
                            {execution.queue_name || 'unknown queue'} ·{' '}
                            {formatDateTime(execution.started_at)}
                          </div>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          <span className="text-[11px] font-mono text-[#B1BAC4] hidden sm:block">
                            {formatDuration(execution.duration_ms)}
                          </span>
                          <StatusBadge status={execution.status} />
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </SectionCard>

              <SectionCard
                title="Workers"
                description="Heartbeat-derived inventory"
                icon={<Server className="w-4 h-4 text-[#C9D1D9]" />}
                actions={
                  <Link
                    to={`${base}/workers`}
                    className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC] flex items-center gap-1"
                  >
                    All <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                }
                bodyClassName="p-0"
              >
                {!data || data.workers.items.length === 0 ? (
                  <div className="p-5">
                    <EmptyState
                      icon={<Server className="w-5 h-5" />}
                      title="No workers discovered"
                      description="Worker rows appear after WORKER_STARTED or a reported task execution."
                    />
                  </div>
                ) : (
                  <div className="divide-y divide-[#30363D]">
                    {data.workers.items.slice(0, 4).map((worker) => (
                      <div key={worker.id} className="px-5 py-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-[#F0F6FC] truncate">
                            {worker.worker_hostname || worker.hostname || 'unknown host'}
                          </span>
                          <StatusBadge status={worker.status} />
                        </div>
                        <div className="text-[11px] text-[#B1BAC4] mt-0.5">
                          Last heartbeat {formatRelative(worker.last_seen_at)}
                        </div>
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {worker.queues.filter((queue) => queue.is_consumed).length > 0 ? (
                            worker.queues
                              .filter((queue) => queue.is_consumed)
                              .slice(0, 3)
                              .map((queue) => (
                                <Pill key={queue.id} tone="sage" title="Consumed queue">
                                  {queue.queue_name}
                                </Pill>
                              ))
                          ) : (
                            <span className="text-[10px] text-[#B1BAC4]">No consumed queues reported</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SectionCard
                title="Task catalog"
                description="Discovered Celery task names"
                icon={<ListChecks className="w-4 h-4 text-[#C9D1D9]" />}
                actions={
                  <Link
                    to={`${base}/tasks`}
                    className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC] flex items-center gap-1"
                  >
                    All tasks <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                }
                bodyClassName="p-0"
              >
                {!data || data.tasks.items.length === 0 ? (
                  <div className="p-5">
                    <EmptyState
                      icon={<ListChecks className="w-5 h-5" />}
                      title="No tasks discovered"
                      description="Call integrate(celery_app, veriq) in the target application to report its registered task names."
                    />
                  </div>
                ) : (
                  <div className="divide-y divide-[#30363D]">
                    {data.tasks.items.map((task) => (
                      <Link
                        key={task.id}
                        to={`${base}/tasks`}
                        className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-[#000000] transition-colors"
                      >
                        <div className="min-w-0">
                          <div className="text-xs font-mono text-[#F0F6FC] truncate">{task.task_name}</div>
                          <div className="text-[11px] text-[#B1BAC4] mt-0.5">
                            {task.execution_count} execution{task.execution_count === 1 ? '' : 's'} · last seen{' '}
                            {formatRelative(task.last_seen_at)}
                          </div>
                        </div>
                        <StatusBadge status={task.status} />
                      </Link>
                    ))}
                  </div>
                )}
              </SectionCard>

              <div className="space-y-6">
                <SectionCard
                  title="Recent failures"
                  description="TASK_FAILED events reported by the SDK"
                  icon={<TriangleAlert className="w-4 h-4 text-[#F85149]" />}
                  actions={
                    <Link
                      to={`${base}/executions?status=FAILED`}
                      className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC] flex items-center gap-1"
                    >
                      Investigate <ArrowRight className="w-3.5 h-3.5" />
                    </Link>
                  }
                  bodyClassName="p-0"
                >
                  {!data || data.failures.items.length === 0 ? (
                    <div className="p-5">
                      <EmptyState
                        icon={<TriangleAlert className="w-5 h-5" />}
                        title="No failed executions"
                        description="No TASK_FAILED events have been recorded for this application."
                      />
                    </div>
                  ) : (
                    <div className="divide-y divide-[#30363D]">
                      {data.failures.items.map((execution) => (
                        <Link
                          key={execution.id}
                          to={`${base}/executions/${execution.id}`}
                          className="block px-5 py-3 hover:bg-[#000000] transition-colors"
                        >
                          <div className="text-xs font-mono text-[#F0F6FC] truncate">{execution.task_name}</div>
                          <div className="text-[11px] text-[#B1BAC4] mt-0.5">
                            {execution.worker_hostname || 'unknown worker'} ·{' '}
                            {formatDateTime(execution.started_at)}
                          </div>
                        </Link>
                      ))}
                    </div>
                  )}
                </SectionCard>

                <SectionCard
                  title="Experiments"
                  description="Definitions scoped to this application"
                  icon={<FlaskConical className="w-4 h-4 text-[#C9D1D9]" />}
                  actions={
                    <Link
                      to={`${base}/experiments`}
                      className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC] flex items-center gap-1"
                    >
                      Open <ArrowRight className="w-3.5 h-3.5" />
                    </Link>
                  }
                >
                  <div className="flex items-center justify-between text-xs">
                    <div>
                      <span className="font-serif font-bold text-xl text-[#F0F6FC]">
                        {data?.experiments.total ?? 0}
                      </span>
                      <span className="text-[#B1BAC4] ml-2">definitions</span>
                    </div>
                    <Boxes className="w-4 h-4 text-[#B1BAC4]" />
                  </div>
                  <p className="text-[11px] text-[#B1BAC4] mt-2 leading-relaxed">
                    Legacy experiment definitions remain read-only history. Reliability plans, approved
                    revisions and isolated runs are managed in{' '}
                    <Link
                      to={`${base}/reliability`}
                      className="font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
                    >
                      Reliability testing
                    </Link>
                    .
                  </p>
                </SectionCard>
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
};

export default ApplicationOverview;
