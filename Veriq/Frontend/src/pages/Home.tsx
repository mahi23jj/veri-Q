import React, { useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Boxes,
  FlaskConical,
  ListChecks,
  Server,
  Terminal,
  TriangleAlert,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { formatCount, formatDateTime, formatDuration, formatRelative } from '../lib/format';

export const Home: React.FC = () => {
  const { applications, loading: applicationsLoading, error: applicationsError } = useApplication();

  const loadWorkspace = useCallback(async () => {
    const [workers, onlineWorkers, executions, failedExecutions, experiments, recentExecutions] =
      await Promise.all([
        api.listWorkers({ limit: 1 }),
        api.listWorkers({ status: 'ONLINE', limit: 1 }),
        api.listExecutions({ limit: 1 }),
        api.listExecutions({ status: 'FAILED', limit: 1 }),
        api.listExperiments({ limit: 1 }),
        api.listExecutions({ limit: 6 }),
      ]);
    return { workers, onlineWorkers, executions, failedExecutions, experiments, recentExecutions };
  }, []);

  const { data, loading, error, reload } = useApiResource(loadWorkspace);

  const metricCards = [
    {
      label: 'Applications',
      value: applications.length,
      hint: 'registered targets',
      icon: Boxes,
      tone: 'text-[#C9D1D9]',
      to: '/applications',
    },
    {
      label: 'Workers online',
      value: data ? `${data.onlineWorkers.total} / ${data.workers.total}` : '—',
      hint: 'heartbeat-derived status',
      icon: Server,
      tone: 'text-[#C9D1D9]',
      to: applications[0] ? `/applications/${applications[0].id}/workers` : '/applications',
    },
    {
      label: 'Task executions',
      value: data ? formatCount(data.executions.total) : '—',
      hint: 'recorded attempts',
      icon: Activity,
      tone: 'text-[#C9D1D9]',
      to: applications[0] ? `/applications/${applications[0].id}/executions` : '/applications',
    },
    {
      label: 'Failed executions',
      value: data ? formatCount(data.failedExecutions.total) : '—',
      hint: 'TASK_FAILED reported',
      icon: TriangleAlert,
      tone: 'text-[#F85149]',
      to: applications[0] ? `/applications/${applications[0].id}/executions?status=FAILED` : '/applications',
    },
  ];

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-8">
        <PageHeader
          title="Workspace Overview"
          description="VeriQ observes Celery task discovery, worker heartbeats and ordinary execution telemetry. Select an application to work in its context."
          actions={
            <Link
              to="/applications?action=register"
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg shadow-2xs transition-all"
            >
              <Boxes className="w-4 h-4" /> Register Application
            </Link>
          }
        />

        {applicationsError && <ErrorState message={applicationsError} />}

        <section aria-labelledby="metrics-summary">
          <h2 id="metrics-summary" className="sr-only">
            Workspace metrics
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {metricCards.map((card) => (
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
                <div className="mt-3 flex items-baseline gap-2">
                  <span className="font-serif font-bold text-2xl md:text-3xl text-[#F0F6FC]">
                    {applicationsLoading && card.label === 'Applications' ? '—' : card.value}
                  </span>
                </div>
                <span className="text-[11px] text-[#B1BAC4]">{card.hint}</span>
              </Link>
            ))}
          </div>
        </section>

        {error && <ErrorState message={error} onRetry={reload} />}

        {!applicationsLoading && applications.length === 0 ? (
          <SectionCard
            title="Connect your first application"
            description="The dashboard is empty until a target application reports discovery."
            icon={<Terminal className="w-4 h-4 text-[#C9D1D9]" />}
          >
            <div className="space-y-4">
              <ol className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                {[
                  ['1. Register', 'Create the application and copy its one-time API key.'],
                  ['2. Install the SDK', 'Install the veriq package in your Celery application.'],
                  ['3. Start a worker', 'Call integrate(celery_app, veriq) and start Celery.'],
                  ['4. Inspect', 'Tasks, workers and executions appear in this application.'],
                ].map(([title, description]) => (
                  <li key={title} className="p-3.5 bg-[#000000] border border-[#30363D] rounded-lg">
                    <span className="font-semibold text-[#F0F6FC] block">{title}</span>
                    <span className="text-[#B1BAC4] mt-0.5 block leading-relaxed">{description}</span>
                  </li>
                ))}
              </ol>
              <div className="flex flex-wrap gap-2">
                <Link
                  to="/applications?action=register"
                  className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg transition-all"
                >
                  Register application <ArrowRight className="w-3.5 h-3.5" />
                </Link>
                <Link
                  to="/integration"
                  className="inline-flex items-center gap-2 px-4 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors"
                >
                  <Terminal className="w-3.5 h-3.5" /> Read integration guide
                </Link>
              </div>
            </div>
          </SectionCard>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <SectionCard
              className="lg:col-span-2"
              title="Recent task executions"
              description="Newest ordinary executions across your applications"
              icon={<Activity className="w-4 h-4 text-[#C9D1D9]" />}
              actions={
                applications[0] ? (
                  <Link
                    to={`/applications/${applications[0].id}/executions`}
                    className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC] flex items-center gap-1"
                  >
                    All executions <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                ) : undefined
              }
              bodyClassName="p-0"
            >
              {loading && !data ? (
                <LoadingState label="Loading executions…" />
              ) : !data || data.recentExecutions.items.length === 0 ? (
                <div className="p-5">
                  <EmptyState
                    icon={<Activity className="w-5 h-5" />}
                    title="No executions reported yet"
                    description="Start an instrumented worker and run a task. Each attempt appears here when the SDK reports its lifecycle events."
                  />
                </div>
              ) : (
                <div className="divide-y divide-[#30363D]">
                  {data.recentExecutions.items.map((execution) => (
                    <Link
                      key={execution.id}
                      to={`/applications/${execution.target_app_id}/executions/${execution.id}`}
                      className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-[#000000] transition-colors"
                    >
                      <div className="min-w-0">
                        <div className="text-xs font-medium text-[#F0F6FC] font-mono truncate">
                          {execution.task_name}
                        </div>
                        <div className="text-[11px] text-[#B1BAC4] mt-0.5 truncate">
                          {execution.worker_hostname || 'unknown worker'} · {execution.queue_name || 'unknown queue'} ·{' '}
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
              title="Applications"
              description="Select one to scope the dashboard"
              icon={<Boxes className="w-4 h-4 text-[#C9D1D9]" />}
              bodyClassName="p-0"
            >
              <div className="divide-y divide-[#30363D]">
                {applications.map((application) => (
                  <Link
                    key={application.id}
                    to={`/applications/${application.id}`}
                    className="block px-5 py-3 hover:bg-[#000000] transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-[#F0F6FC] truncate">{application.name}</span>
                      <span className="text-[10px] font-mono uppercase text-[#B1BAC4]">
                        {application.environment}
                      </span>
                    </div>
                    <div className="text-[11px] text-[#B1BAC4] mt-0.5">
                      Updated {formatRelative(application.updated_at)}
                    </div>
                  </Link>
                ))}
              </div>
              <div className="p-4 border-t border-[#30363D]">
                <Link
                  to="/applications"
                  className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] hover:bg-[#161B22] rounded-lg transition-colors"
                >
                  <Boxes className="w-3.5 h-3.5 text-[#B1BAC4]" /> Manage applications
                </Link>
              </div>
            </SectionCard>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <SectionCard title="Task catalog" icon={<ListChecks className="w-4 h-4 text-[#C9D1D9]" />}>
            <p className="text-xs text-[#B1BAC4] leading-relaxed">
              Celery task names discovered from your application. Discovery is independent of execution
              telemetry and can be enabled or disabled per task.
            </p>
          </SectionCard>
          <SectionCard title="Experiments" icon={<FlaskConical className="w-4 h-4 text-[#C9D1D9]" />}>
            <p className="text-xs text-[#B1BAC4] leading-relaxed">
              Experiment definitions are stored now. The backend does not yet expose dashboard run
              listing, failure injection or invariant results.
            </p>
          </SectionCard>
          <SectionCard title="SDK integration" icon={<Terminal className="w-4 h-4 text-[#C9D1D9]" />}>
            <p className="text-xs text-[#B1BAC4] leading-relaxed">
              VeriQ is report-only: the SDK observes Celery signals and never starts, pauses or stops a
              worker.
            </p>
            <Link
              to="/integration"
              className="inline-flex items-center gap-1 text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC] mt-2"
            >
              Open guide <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </SectionCard>
        </div>
      </div>
    </Layout>
  );
};

export default Home;
