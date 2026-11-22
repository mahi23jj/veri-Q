import React, { useCallback, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Activity, Info, RefreshCw, Terminal, TriangleAlert } from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { formatDateTime, formatDuration, shortId } from '../lib/format';

const PAGE_SIZE = 20;

export const Executions: React.FC = () => {
  const { appId } = useParams<{ appId: string }>();
  const { application } = useScopedApplication(appId);
  const [searchParams] = useSearchParams();

  const [status, setStatus] = useState(searchParams.get('status') ?? '');
  const [taskName, setTaskName] = useState(searchParams.get('task') ?? '');
  const [skip, setSkip] = useState(0);

  const loadExecutions = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    return api.listExecutions({
      target_app_id: appId,
      status: status || undefined,
      task_name: taskName || undefined,
      skip,
      limit: PAGE_SIZE,
    });
  }, [appId, status, taskName, skip]);

  const loadTasks = useCallback(async () => {
    if (!appId) return { items: [] };
    return api.listApplicationTasks(appId, { limit: 1000 });
  }, [appId]);

  const { data, loading, error, reload } = useApiResource(loadExecutions);
  const { data: taskOptions } = useApiResource(loadTasks);

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
          title="Task Executions"
          description={`Every reported execution attempt for ${application?.name ?? 'this application'}, newest first.`}
          eyebrow={<span className="text-[11px] text-[#B1BAC4] font-mono">GET /api/v1/task-executions</span>}
          actions={
            <>
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <Link
                to="/integration"
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg transition-all"
              >
                <Terminal className="w-3.5 h-3.5" /> Integration guide
              </Link>
            </>
          }
        />

        <div className="p-4 bg-[#C9D1D9]/8 border border-[#C9D1D9]/25 rounded-xl flex items-start gap-2.5 text-xs text-[#C9D1D9]">
          <Info className="w-4 h-4 mt-0.5 shrink-0" />
          <p className="leading-relaxed">
            One row is one actual attempt. Celery retries and redeliveries may reuse a{' '}
            <span className="font-mono">celery_task_id</span> but each attempt receives its own
            execution id. Open a row to see its chronological event timeline and checkpoints.
          </p>
        </div>

        {error && <ErrorState message={error} onRetry={reload} />}

        <SectionCard
          title="Execution history"
          description={data ? `${data.total} execution${data.total === 1 ? '' : 's'} recorded` : 'Loading…'}
          icon={<Activity className="w-4 h-4 text-[#C9D1D9]" />}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="execution-status-filter" className="text-[11px] text-[#B1BAC4]">
                Status
              </label>
              <select
                id="execution-status-filter"
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  setSkip(0);
                }}
                className="px-2.5 py-1.5 text-xs bg-[#000000] border border-[#30363D] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]"
              >
                <option value="">All statuses</option>
                <option value="RUNNING">Running</option>
                <option value="SUCCEEDED">Succeeded</option>
                <option value="FAILED">Failed</option>
                <option value="RETRYING">Retrying</option>
              </select>

              <label htmlFor="execution-task-filter" className="text-[11px] text-[#B1BAC4] ml-1">
                Task
              </label>
              <select
                id="execution-task-filter"
                value={taskName}
                onChange={(event) => {
                  setTaskName(event.target.value);
                  setSkip(0);
                }}
                className="px-2.5 py-1.5 text-xs bg-[#000000] border border-[#30363D] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9] max-w-[220px]"
              >
                <option value="">All tasks</option>
                {taskOptions?.items.map((task) => (
                  <option key={task.id} value={task.task_name}>
                    {task.task_name}
                  </option>
                ))}
              </select>

              {(status || taskName) && (
                <button
                  onClick={() => {
                    setStatus('');
                    setTaskName('');
                    setSkip(0);
                  }}
                  className="text-[11px] font-medium text-[#C9D1D9] hover:text-[#F0F6FC] px-1"
                >
                  Clear
                </button>
              )}
            </div>
          }
          bodyClassName="p-0"
        >
          {loading && !data ? (
            <LoadingState label="Loading executions…" />
          ) : !data || data.items.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={status === 'FAILED' ? <TriangleAlert className="w-5 h-5" /> : <Activity className="w-5 h-5" />}
                title={status === 'FAILED' ? 'No failed executions' : 'No executions found'}
                description={
                  status || taskName
                    ? 'No executions match the current filters. Clear the filters to see all reported attempts.'
                    : 'Run a task in an instrumented Celery worker. The SDK reports TASK_STARTED and terminal events, which create the attempt row and timeline.'
                }
              />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#000000] text-[10px] uppercase tracking-wider text-[#B1BAC4]">
                    <tr>
                      <th className="px-5 py-2.5 font-semibold">Task</th>
                      <th className="px-3 py-2.5 font-semibold">Status</th>
                      <th className="px-3 py-2.5 font-semibold">Worker</th>
                      <th className="px-3 py-2.5 font-semibold">Queue</th>
                      <th className="px-3 py-2.5 font-semibold">Started</th>
                      <th className="px-3 py-2.5 font-semibold">Duration</th>
                      <th className="px-3 py-2.5 font-semibold">Attempt</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#30363D]">
                    {data.items.map((execution) => (
                      <tr key={execution.id} className="hover:bg-[#000000] transition-colors">
                        <td className="px-5 py-3 max-w-[320px]">
                          <Link
                            to={`/applications/${appId}/executions/${execution.id}`}
                            className="block font-mono text-[11.5px] text-[#F0F6FC] hover:text-[#C9D1D9] truncate"
                            title={execution.task_name}
                          >
                            {execution.task_name}
                          </Link>
                          <div className="text-[10px] text-[#B1BAC4] mt-0.5 font-mono">
                            celery task: {execution.celery_task_id || '—'}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <StatusBadge status={execution.status} />
                        </td>
                        <td className="px-3 py-3 max-w-[180px]">
                          <div className="text-[11px] text-[#F0F6FC] truncate">
                            {execution.worker_hostname || 'unknown host'}
                          </div>
                          <div className="text-[10px] text-[#B1BAC4] truncate font-mono">
                            pid {execution.pid ?? '—'}
                          </div>
                        </td>
                        <td className="px-3 py-3 text-[11px] text-[#C9D1D9]">
                          {execution.queue_name || '—'}
                        </td>
                        <td className="px-3 py-3 whitespace-nowrap text-[11px] text-[#C9D1D9]">
                          {formatDateTime(execution.started_at)}
                        </td>
                        <td className="px-3 py-3 whitespace-nowrap text-[11px] font-mono text-[#C9D1D9]">
                          {formatDuration(execution.duration_ms)}
                        </td>
                        <td className="px-3 py-3">
                          <Link
                            to={`/applications/${appId}/executions/${execution.id}`}
                            className="text-[10px] font-mono text-[#C9D1D9] hover:text-[#F0F6FC]"
                            title={execution.execution_id}
                          >
                            {shortId(execution.execution_id, 10)}
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-5 pb-4">
                <Pagination total={data.total} skip={data.skip} limit={data.limit} onChange={setSkip} />
              </div>
            </>
          )}
        </SectionCard>
      </div>
    </Layout>
  );
};

export default Executions;
