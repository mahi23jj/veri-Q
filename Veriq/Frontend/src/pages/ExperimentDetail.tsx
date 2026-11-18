import React, { useCallback, useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  ArrowLeft,
  Edit2,
  FlaskConical,
  Info,
  Lock,
  RefreshCw,
  Terminal,
  Trash2,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useApiResource } from '../hooks/useApiResource';
import { api, API_BASE_URL } from '../api/client';
import type { Experiment } from '../api/types';
import { NewExperimentModal } from '../components/NewExperimentModal';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import {
  CodeBlock,
  DetailRow,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pill,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { formatDateTime, formatRelative } from '../lib/format';

const RUNS_GAP_CODE = `# Runs and their events require the application API key and are
# not exposed to the dashboard today:
curl -X POST ${API_BASE_URL}/api/v1/experiments/<experiment-id>/runs \\
  -H "X-API-Key: vq_..."

curl ${API_BASE_URL}/api/v1/experiment-runs/<run-id> \\
  -H "X-API-Key: vq_..."
curl ${API_BASE_URL}/api/v1/experiment-runs/<run-id>/events \\
  -H "X-API-Key: vq_..."`;

export const ExperimentDetail: React.FC = () => {
  const { appId, experimentId } = useParams<{ appId: string; experimentId: string }>();
  const navigate = useNavigate();
  const [isEditing, setIsEditing] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadExperiment = useCallback(async () => {
    if (!experimentId) throw new Error('No experiment selected');
    return api.getExperiment(experimentId);
  }, [experimentId]);

  const loadTasks = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    return api.listApplicationTasks(appId, { limit: 1000 });
  }, [appId]);

  const { data: experiment, loading, error, reload } = useApiResource(loadExperiment);
  const { data: tasks } = useApiResource(loadTasks);

  const handleSaved = (saved: Experiment) => {
    setIsEditing(false);
    toast.success(`Draft "${saved.name}" updated`);
    reload();
  };

  const handleDelete = async () => {
    if (!experiment) return;
    setBusy(true);
    try {
      await api.deleteExperiment(experiment.id);
      toast.info(`Draft "${experiment.name}" deleted`);
      navigate(`/applications/${appId}/experiments`, { replace: true });
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not delete experiment');
    } finally {
      setBusy(false);
    }
  };

  if (!appId || !experimentId) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <EmptyState title="No experiment selected" description="Open an experiment from the list." />
        </div>
      </Layout>
    );
  }

  if (loading && !experiment) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <LoadingState label="Loading experiment…" />
        </div>
      </Layout>
    );
  }

  if (!experiment) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-4">
          <Link
            to={`/applications/${appId}/experiments`}
            className="inline-flex items-center gap-1.5 text-xs text-[#777A72] hover:text-[#343832]"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to experiments
          </Link>
          <ErrorState message={error ?? 'Experiment not found'} onRetry={reload} />
        </div>
      </Layout>
    );
  }

  const isDraft = experiment.status === 'DRAFT';
  const belongsToApplication = experiment.target_app_id === appId;

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-6xl w-full mx-auto space-y-6">
        <div className="space-y-3">
          <Link
            to={`/applications/${appId}/experiments`}
            className="inline-flex items-center gap-1.5 text-xs text-[#777A72] hover:text-[#343832]"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to experiments
          </Link>

          <PageHeader
            title={experiment.name}
            description={experiment.description || 'No description provided.'}
            eyebrow={
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={experiment.status} />
                <Pill tone="blue">{experiment.scenario}</Pill>
                {experiment.checkpoint_name && (
                  <Pill tone="beige">@{experiment.checkpoint_name}</Pill>
                )}
              </div>
            }
            actions={
              <>
                <button
                  onClick={reload}
                  className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#EFEEE7] transition-colors"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
                </button>
                {isDraft && (
                  <>
                    <button
                      onClick={() => setIsEditing(true)}
                      className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#EFEEE7] transition-colors"
                    >
                      <Edit2 className="w-3.5 h-3.5" /> Edit draft
                    </button>
                    <button
                      onClick={() => setIsDeleting(true)}
                      className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#A46F70] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#A46F70]/10 transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" /> Delete
                    </button>
                  </>
                )}
              </>
            }
          />
        </div>

        {!belongsToApplication && (
          <div className="p-4 bg-[#D8C8AE]/25 border border-[#D8C8AE]/60 rounded-xl text-xs text-[#6b5a43]">
            This experiment belongs to application{' '}
            <span className="font-mono">{experiment.target_app_id}</span>, not the application in the URL.
            The backend does not scope experiments to the dashboard's selected application.
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          <SectionCard
            className="lg:col-span-2"
            title="Definition"
            description="Stored configuration returned by GET /experiments/{id}"
            icon={<FlaskConical className="w-4 h-4 text-[#8297AC]" />}
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <DetailRow label="Scenario" mono>
                {experiment.scenario}
              </DetailRow>
              <DetailRow label="Target task" mono>
                {experiment.task_name}
              </DetailRow>
              <DetailRow label="Checkpoint name" mono>
                {experiment.checkpoint_name || '—'}
              </DetailRow>
              <DetailRow label="Timeout" mono>
                {experiment.timeout_seconds} s
              </DetailRow>
              <DetailRow label="Status">
                <StatusBadge status={experiment.status} />
              </DetailRow>
              <DetailRow label="Application" mono>
                {experiment.target_app_id}
              </DetailRow>
              <DetailRow label="Created">
                {formatDateTime(experiment.created_at)}{' '}
                <span className="text-[#777A72]">({formatRelative(experiment.created_at)})</span>
              </DetailRow>
              <DetailRow label="Updated">{formatDateTime(experiment.updated_at)}</DetailRow>
            </div>

            {experiment.config_snapshot && Object.keys(experiment.config_snapshot).length > 0 && (
              <div className="mt-4">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                  Config snapshot
                </h3>
                <pre className="p-3 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg text-[11px] font-mono overflow-x-auto">
                  {JSON.stringify(experiment.config_snapshot, null, 2)}
                </pre>
              </div>
            )}

            <div className="mt-4 p-3 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg text-xs text-[#61655b] leading-relaxed">
              <span className="font-semibold text-[#343832] block mb-1">How this definition is used</span>
              A runner creates a run for this experiment with the application API key. Ordinary task
              executions are linked to a run only when the task is dispatched with{' '}
              <span className="font-mono">veriq_run_id</span> /{' '}
              <span className="font-mono">veriq_operation_id</span> headers. VeriQ does not inject failures
              or terminate workers.
            </div>
          </SectionCard>

          <div className="space-y-6">
            <SectionCard
              title="Runs"
              description="Not available to the dashboard"
              icon={<Lock className="w-4 h-4 text-[#777A72]" />}
            >
              <div className="space-y-3 text-xs text-[#61655b] leading-relaxed">
                <p>
                  The backend has no endpoint to list the runs of an experiment. Run and event reads are
                  scoped to the application API key and only addressable by run id.
                </p>
                <div className="p-3 bg-[#FAF8F3] border border-dashed border-[#E5E1D7] rounded-lg">
                  <span className="font-semibold text-[#343832] block mb-1">Backend gap</span>
                  Needed for a dashboard runs table:{' '}
                  <span className="font-mono">GET /api/v1/experiments/&#123;id&#125;/runs</span> (unauthenticated,
                  paginated).
                </div>
                <CodeBlock code={RUNS_GAP_CODE} label="bash — runner-only endpoints" />
              </div>
            </SectionCard>

            <div className="p-4 bg-[#8297AC]/8 border border-[#8297AC]/25 rounded-xl text-xs text-[#3b5168] flex items-start gap-2">
              <Info className="w-4 h-4 mt-0.5 shrink-0" />
              <p className="leading-relaxed">
                This page intentionally shows no verdicts, invariants or failure-injection controls: the
                backend implements none of them yet.
              </p>
            </div>

            <Link
              to="/integration"
              className="flex items-center justify-between gap-2 p-4 bg-[#FDFCFA] border border-[#E5E1D7] rounded-xl text-xs text-[#52564e] hover:border-[#D8C8AE] transition-colors"
            >
              <span className="flex items-center gap-2">
                <Terminal className="w-3.5 h-3.5 text-[#8297AC]" /> SDK integration guide
              </span>
              <span className="text-[#777A72]">→</span>
            </Link>
          </div>
        </div>
      </div>

      <NewExperimentModal
        isOpen={isEditing}
        onClose={() => setIsEditing(false)}
        applicationId={experiment.target_app_id}
        taskNames={tasks?.items.map((task) => task.task_name) ?? []}
        initialData={experiment}
        onSaved={handleSaved}
      />

      <ConfirmationDialog
        isOpen={isDeleting}
        title="Delete Draft Experiment"
        message={`Permanently delete "${experiment.name}"? Experiments referenced by runs or no longer in DRAFT are rejected by the backend.`}
        confirmLabel="Delete Draft"
        isBusy={busy}
        onConfirm={handleDelete}
        onCancel={() => setIsDeleting(false)}
      />
    </Layout>
  );
};

export default ExperimentDetail;
