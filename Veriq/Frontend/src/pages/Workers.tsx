import React, { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ChevronRight,
  Info,
  RefreshCw,
  Server,
  Terminal,
  X,
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
  Pagination,
  Pill,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { formatDateTime, formatRelative } from '../lib/format';

const PAGE_SIZE = 20;

const WorkerDetailModal: React.FC<{ workerId: string; onClose: () => void }> = ({
  workerId,
  onClose,
}) => {
  const loadWorker = useCallback(() => api.getWorker(workerId), [workerId]);
  const { data, loading, error, reload } = useApiResource(loadWorker);

  const consumed = data?.queues.filter((queue) => queue.is_consumed) ?? [];
  const configured = data?.queues.filter((queue) => queue.is_configured) ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#F0F6FC]/40 backdrop-blur-xs">
      <div className="w-full max-w-2xl max-h-[90vh] bg-[#000000] rounded-xl border border-[#30363D] shadow-xl overflow-hidden flex flex-col">
        <div className="px-5 py-3.5 border-b border-[#30363D] bg-[#000000] flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-serif font-bold text-base text-[#F0F6FC] truncate">
              {data?.worker_hostname || data?.hostname || 'Worker instance'}
            </h2>
            <p className="text-[11px] text-[#B1BAC4]">
              Worker identity, heartbeat and queue inventory reported by the SDK
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#B1BAC4] hover:text-[#F0F6FC] rounded-md hover:bg-[#161B22]"
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
                  ['Status', <StatusBadge key="status" status={data.status} />],
                  ['PID', data.pid ?? '—'],
                  ['First seen', formatDateTime(data.first_seen_at)],
                  ['Last heartbeat', formatDateTime(data.last_seen_at)],
                  ['Worker instance id', <span key="instance" className="font-mono break-all">{data.worker_instance_id}</span>],
                  ['Process identity', <span key="identity" className="font-mono break-all">{data.process_start_identity || '—'}</span>],
                ].map(([label, value], index) => (
                  <div key={index} className="p-2.5 bg-[#000000] border border-[#30363D] rounded-lg min-w-0">
                    <span className="text-[10px] text-[#B1BAC4] block">{label}</span>
                    <span className="text-[11.5px] text-[#F0F6FC] mt-0.5 block break-words">{value}</span>
                  </div>
                ))}
              </div>

              <div>
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1.5">
                  Queues consumed ({consumed.length})
                </h3>
                {consumed.length === 0 ? (
                  <p className="text-xs text-[#B1BAC4] p-2.5 border border-dashed border-[#30363D] rounded-lg">
                    No consumed queues reported. The SDK reports these from Celery's consumer state when
                    available.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {consumed.map((queue) => (
                      <Pill key={queue.id} tone="sage" title={`Consumed · last seen ${formatDateTime(queue.last_seen_at)}`}>
                        {queue.queue_name}
                      </Pill>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1.5">
                  Queues configured ({configured.length})
                </h3>
                {configured.length === 0 ? (
                  <p className="text-xs text-[#B1BAC4] p-2.5 border border-dashed border-[#30363D] rounded-lg">
                    No configured queues reported.
                  </p>
                ) : (
                  <div className="border border-[#30363D] rounded-lg overflow-hidden divide-y divide-[#30363D]">
                    {configured.map((queue) => (
                      <div key={queue.id} className="flex items-center justify-between gap-2 px-3 py-2 bg-[#000000]">
                        <div className="min-w-0">
                          <div className="text-[11.5px] font-mono text-[#F0F6FC] truncate">
                            {queue.queue_name}
                          </div>
                          <div className="text-[10px] text-[#B1BAC4]">
                            exchange: {queue.exchange || '—'} · routing key: {queue.routing_key || '—'}
                          </div>
                        </div>
                        <Pill tone={queue.is_consumed ? 'sage' : 'muted'}>
                          {queue.is_consumed ? 'consumed' : 'not consumed'}
                        </Pill>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-[10px] text-[#B1BAC4] mt-1.5 leading-relaxed">
                  Configured queues come from <span className="font-mono">celery_app.amqp.queues</span>.
                  A worker may configure a queue without consuming it; consumed queues are reported
                  separately by the SDK.
                </p>
              </div>

              <div>
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1.5">
                  Registered tasks ({data.registered_task_names?.length ?? 0})
                </h3>
                {!data.registered_task_names || data.registered_task_names.length === 0 ? (
                  <p className="text-xs text-[#B1BAC4] p-2.5 border border-dashed border-[#30363D] rounded-lg">
                    This worker did not report a task list.
                  </p>
                ) : (
                  <div className="max-h-48 overflow-y-auto border border-[#30363D] rounded-lg divide-y divide-[#30363D]">
                    {data.registered_task_names.map((name) => (
                      <div key={name} className="px-3 py-1.5 text-[11px] font-mono text-[#F0F6FC] bg-[#000000]">
                        {name}
                      </div>
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

export const Workers: React.FC = () => {
  const { appId } = useParams<{ appId: string }>();
  const { application } = useScopedApplication(appId);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [skip, setSkip] = useState(0);
  const [openWorkerId, setOpenWorkerId] = useState<string | null>(null);

  const loadWorkers = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    return api.listWorkers({
      target_app_id: appId,
      status: statusFilter === 'ALL' ? undefined : statusFilter,
      skip,
      limit: PAGE_SIZE,
    });
  }, [appId, statusFilter, skip]);

  const { data, loading, error, reload } = useApiResource(loadWorkers);

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
          title="Workers & Queues"
          description={`Worker instances discovered for ${application?.name ?? 'this application'}, with heartbeat status and queue inventory.`}
          eyebrow={<span className="text-[11px] text-[#B1BAC4] font-mono">GET /api/v1/workers</span>}
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
            Worker rows are report-only. VeriQ does not provide restart, stop or kill controls, and this
            dashboard has none. A worker is marked <span className="font-mono">OFFLINE</span> when no
            heartbeat has been received for 120 seconds.
          </p>
        </div>

        {error && <ErrorState message={error} onRetry={reload} />}

        <SectionCard
          title="Worker instances"
          description={data ? `${data.total} instance${data.total === 1 ? '' : 's'} discovered` : 'Loading…'}
          icon={<Server className="w-4 h-4 text-[#C9D1D9]" />}
          actions={
            <div className="flex items-center gap-2">
              <label htmlFor="worker-status-filter" className="text-[11px] text-[#B1BAC4]">
                Status
              </label>
              <select
                id="worker-status-filter"
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value);
                  setSkip(0);
                }}
                className="px-2.5 py-1.5 text-xs bg-[#000000] border border-[#30363D] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]"
              >
                <option value="ALL">All statuses</option>
                <option value="ONLINE">Online</option>
                <option value="OFFLINE">Offline</option>
                <option value="UNKNOWN">Unknown</option>
              </select>
            </div>
          }
          bodyClassName="p-0"
        >
          {loading && !data ? (
            <LoadingState label="Loading workers…" />
          ) : !data || data.items.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<Server className="w-5 h-5" />}
                title="No workers discovered"
                description="Start a Celery worker after calling integrate(celery_app, veriq). The worker_ready and heartbeat_sent signals create and refresh this inventory."
                action={
                  <Link
                    to="/integration"
                    className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
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
                  <thead className="bg-[#000000] text-[10px] uppercase tracking-wider text-[#B1BAC4]">
                    <tr>
                      <th className="px-5 py-2.5 font-semibold">Worker</th>
                      <th className="px-3 py-2.5 font-semibold">Status</th>
                      <th className="px-3 py-2.5 font-semibold">Last heartbeat</th>
                      <th className="px-3 py-2.5 font-semibold">Consumed queues</th>
                      <th className="px-3 py-2.5 font-semibold">Configured queues</th>
                      <th className="px-3 py-2.5 font-semibold">Tasks</th>
                      <th className="px-3 py-2.5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#30363D]">
                    {data.items.map((worker) => {
                      const consumed = worker.queues.filter((queue) => queue.is_consumed);
                      const configured = worker.queues.filter((queue) => queue.is_configured);
                      return (
                        <tr
                          key={worker.id}
                          onClick={() => setOpenWorkerId(worker.id)}
                          className="hover:bg-[#000000] cursor-pointer transition-colors"
                        >
                          <td className="px-5 py-3 max-w-[240px]">
                            <div className="text-xs font-medium text-[#F0F6FC] truncate">
                              {worker.worker_hostname || worker.hostname || 'unknown host'}
                            </div>
                            <div className="text-[10px] font-mono text-[#B1BAC4] mt-0.5 truncate">
                              PID {worker.pid ?? '—'} · {worker.worker_instance_id.slice(0, 8)}
                            </div>
                          </td>
                          <td className="px-3 py-3">
                            <StatusBadge status={worker.status} />
                          </td>
                          <td className="px-3 py-3 whitespace-nowrap text-[11px] text-[#B1BAC4]">
                            {formatRelative(worker.last_seen_at)}
                          </td>
                          <td className="px-3 py-3">
                            {consumed.length === 0 ? (
                              <span className="text-[#B1BAC4]">—</span>
                            ) : (
                              <div className="flex flex-wrap gap-1 max-w-[180px]">
                                {consumed.slice(0, 3).map((queue) => (
                                  <Pill key={queue.id} tone="sage">
                                    {queue.queue_name}
                                  </Pill>
                                ))}
                                {consumed.length > 3 && <Pill>+{consumed.length - 3}</Pill>}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-3">
                            {configured.length === 0 ? (
                              <span className="text-[#B1BAC4]">—</span>
                            ) : (
                              <div className="flex flex-wrap gap-1 max-w-[180px]">
                                {configured.slice(0, 3).map((queue) => (
                                  <Pill key={queue.id} tone={queue.is_consumed ? 'sage' : 'muted'}>
                                    {queue.queue_name}
                                  </Pill>
                                ))}
                                {configured.length > 3 && <Pill>+{configured.length - 3}</Pill>}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-3 font-mono text-[#F0F6FC]">
                            {worker.registered_task_names?.length ?? 0}
                          </td>
                          <td className="px-3 py-3 text-right">
                            <ChevronRight className="w-4 h-4 text-[#B1BAC4] inline" />
                          </td>
                        </tr>
                      );
                    })}
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

      {openWorkerId && (
        <WorkerDetailModal workerId={openWorkerId} onClose={() => setOpenWorkerId(null)} />
      )}
    </Layout>
  );
};

export default Workers;
