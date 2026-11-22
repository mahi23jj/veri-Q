import React, { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  ChevronRight,
  Edit2,
  FlaskConical,
  Info,
  Plus,
  RefreshCw,
  Terminal,
  Trash2,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import type { Experiment } from '../api/types';
import { NewExperimentModal } from '../components/NewExperimentModal';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
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
import { formatRelative, shortId } from '../lib/format';

const PAGE_SIZE = 20;

export const Experiments: React.FC = () => {
  const { appId } = useParams<{ appId: string }>();
  const { application } = useScopedApplication(appId);

  const [skip, setSkip] = useState(0);
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'DRAFT'>('ALL');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editing, setEditing] = useState<Experiment | null>(null);
  const [deleting, setDeleting] = useState<Experiment | null>(null);
  const [busy, setBusy] = useState(false);

  const loadExperiments = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    return api.listExperiments({ target_app_id: appId, skip, limit: PAGE_SIZE });
  }, [appId, skip]);

  const loadTasks = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    return api.listApplicationTasks(appId, { limit: 1000 });
  }, [appId]);

  const { data, loading, error, reload } = useApiResource(loadExperiments);
  const { data: tasks } = useApiResource(loadTasks);

  const visibleExperiments =
    data?.items.filter((experiment) => statusFilter === 'ALL' || experiment.status === statusFilter) ??
    [];

  const openCreate = () => {
    setEditing(null);
    setIsModalOpen(true);
  };

  const handleSaved = (saved: Experiment) => {
    setIsModalOpen(false);
    setEditing(null);
    toast.success(
      editing ? `Draft "${saved.name}" updated` : `Experiment "${saved.name}" created as a draft`,
    );
    reload();
  };

  const handleDelete = async () => {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.deleteExperiment(deleting.id);
      toast.info(`Draft "${deleting.name}" deleted`);
      setDeleting(null);
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not delete experiment');
    } finally {
      setBusy(false);
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
          title="Reliability Experiments"
          description={`Experiment definitions for ${application?.name ?? 'this application'}. These are separate from ordinary task execution telemetry.`}
          eyebrow={<span className="text-[11px] text-[#B1BAC4] font-mono">GET /api/v1/experiments</span>}
          actions={
            <>
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <button
                onClick={openCreate}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg shadow-2xs transition-all"
              >
                <Plus className="w-4 h-4" /> New Experiment
              </button>
            </>
          }
        />

        <div className="p-4 bg-[#C9D1D9]/25 border border-[#C9D1D9]/60 rounded-xl text-xs text-[#C9D1D9] flex items-start gap-2.5">
          <Info className="w-4 h-4 mt-0.5 shrink-0" />
          <div className="leading-relaxed space-y-1">
            <p>
              <span className="font-semibold">Current backend capability:</span> experiments are stored as
              definitions and drafts can be edited or deleted. There is no dashboard endpoint to list
              experiment runs or their events, no failure injection, no runner control and no invariant
              results yet.
            </p>
            <p>
              Runs are created by a runner calling{' '}
              <span className="font-mono">POST /api/v1/experiments/&#123;id&#125;/runs</span> with the
              application API key. This dashboard does not create runs.
            </p>
          </div>
        </div>

        {error && <ErrorState message={error} onRetry={reload} />}

        <SectionCard
          title="Experiment definitions"
          description={data ? `${data.total} definition${data.total === 1 ? '' : 's'}` : 'Loading…'}
          icon={<FlaskConical className="w-4 h-4 text-[#C9D1D9]" />}
          actions={
            <div className="flex items-center gap-1.5">
              {(['ALL', 'DRAFT'] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setStatusFilter(tab)}
                  className={`px-3 py-1 text-[11px] rounded-lg font-medium transition-colors ${
                    statusFilter === tab
                      ? 'bg-[#C9D1D9]/15 text-[#F0F6FC] border border-[#C9D1D9]/30'
                      : 'text-[#B1BAC4] hover:bg-[#161B22]'
                  }`}
                >
                  {tab === 'ALL' ? 'All' : 'Draft'}
                </button>
              ))}
            </div>
          }
          bodyClassName="p-0"
        >
          {loading && !data ? (
            <LoadingState label="Loading experiments…" />
          ) : visibleExperiments.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<FlaskConical className="w-5 h-5" />}
                title={statusFilter === 'DRAFT' ? 'No draft experiments' : 'No experiments yet'}
                description="Create a definition to describe the task, scenario and checkpoint you want to protect. Creating one does not enqueue a task."
                action={
                  <button
                    onClick={openCreate}
                    className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg"
                  >
                    <Plus className="w-3.5 h-3.5" /> New Experiment
                  </button>
                }
              />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#000000] text-[10px] uppercase tracking-wider text-[#B1BAC4]">
                    <tr>
                      <th className="px-5 py-2.5 font-semibold">Experiment</th>
                      <th className="px-3 py-2.5 font-semibold">Task</th>
                      <th className="px-3 py-2.5 font-semibold">Scenario</th>
                      <th className="px-3 py-2.5 font-semibold">Checkpoint</th>
                      <th className="px-3 py-2.5 font-semibold">Timeout</th>
                      <th className="px-3 py-2.5 font-semibold">Status</th>
                      <th className="px-3 py-2.5 font-semibold">Created</th>
                      <th className="px-3 py-2.5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#30363D]">
                    {visibleExperiments.map((experiment) => {
                      const isDraft = experiment.status === 'DRAFT';
                      return (
                        <tr key={experiment.id} className="hover:bg-[#000000] transition-colors">
                          <td className="px-5 py-3 max-w-[280px]">
                            <Link
                              to={`/applications/${appId}/experiments/${experiment.id}`}
                              className="block font-medium text-[#F0F6FC] hover:text-[#C9D1D9] truncate"
                              title={experiment.name}
                            >
                              {experiment.name}
                            </Link>
                            <div className="text-[10px] text-[#B1BAC4] mt-0.5 font-mono">
                              {shortId(experiment.id, 10)}
                            </div>
                          </td>
                          <td className="px-3 py-3 max-w-[240px]">
                            <div className="font-mono text-[11px] text-[#F0F6FC] truncate" title={experiment.task_name}>
                              {experiment.task_name}
                            </div>
                          </td>
                          <td className="px-3 py-3">
                            <Pill tone="blue">{experiment.scenario}</Pill>
                          </td>
                          <td className="px-3 py-3 font-mono text-[11px] text-[#C9D1D9]">
                            {experiment.checkpoint_name || '—'}
                          </td>
                          <td className="px-3 py-3 font-mono text-[11px] text-[#C9D1D9]">
                            {experiment.timeout_seconds}s
                          </td>
                          <td className="px-3 py-3">
                            <StatusBadge status={experiment.status} />
                          </td>
                          <td className="px-3 py-3 whitespace-nowrap text-[11px] text-[#B1BAC4]">
                            {formatRelative(experiment.created_at)}
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex items-center justify-end gap-1">
                              {isDraft && (
                                <>
                                  <button
                                    onClick={() => {
                                      setEditing(experiment);
                                      setIsModalOpen(true);
                                    }}
                                    className="p-1.5 text-[#B1BAC4] hover:text-[#F0F6FC] hover:bg-[#161B22] rounded-md transition-colors"
                                    title="Edit draft"
                                  >
                                    <Edit2 className="w-3.5 h-3.5" />
                                  </button>
                                  <button
                                    onClick={() => setDeleting(experiment)}
                                    className="p-1.5 text-[#F85149] hover:bg-[#F85149]/15 rounded-md transition-colors"
                                    title="Delete draft"
                                  >
                                    <Trash2 className="w-3.5 h-3.5" />
                                  </button>
                                </>
                              )}
                              <Link
                                to={`/applications/${appId}/experiments/${experiment.id}`}
                                className="p-1.5 text-[#B1BAC4] hover:text-[#F0F6FC] hover:bg-[#161B22] rounded-md transition-colors"
                                title="Inspect experiment"
                              >
                                <ChevronRight className="w-4 h-4" />
                              </Link>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="px-5 pb-4">
                <Pagination total={data?.total ?? 0} skip={data?.skip ?? 0} limit={data?.limit ?? PAGE_SIZE} onChange={setSkip} />
              </div>
            </>
          )}
        </SectionCard>

        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#B1BAC4]">
          <span>
            Experiment events are stored separately from task execution events. This dashboard never merges
            them.
          </span>
          <Link
            to="/integration"
            className="inline-flex items-center gap-1.5 font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
          >
            <Terminal className="w-3.5 h-3.5" /> SDK integration guide
          </Link>
        </div>
      </div>

      <NewExperimentModal
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setEditing(null);
        }}
        applicationId={appId}
        taskNames={tasks?.items.map((task) => task.task_name) ?? []}
        initialData={editing}
        onSaved={handleSaved}
      />

      <ConfirmationDialog
        isOpen={!!deleting}
        title="Delete Draft Experiment"
        message={`Permanently delete draft "${deleting?.name}"? The backend rejects deletion of non-draft experiments and experiments referenced by runs.`}
        confirmLabel="Delete Draft"
        isBusy={busy}
        onConfirm={handleDelete}
        onCancel={() => setDeleting(null)}
      />
    </Layout>
  );
};

export default Experiments;
