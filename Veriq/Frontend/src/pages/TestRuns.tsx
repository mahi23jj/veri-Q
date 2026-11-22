import React, { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import { ArrowLeft, Play, RefreshCw, RotateCcw } from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import type { TestCaseRun } from '../api/types';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { VerdictBadge } from '../components/reliability';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import { formatDateTime, formatDuration, shortId } from '../lib/format';

const LIFECYCLE_FILTERS = [
  'ALL',
  'PENDING',
  'VALIDATING',
  'PROVISIONING',
  'PREPARING_FAULT',
  'STARTING',
  'RUNNING',
  'INJECTING',
  'OBSERVING_RECOVERY',
  'EVALUATING',
  'FINALIZING',
  'COMPLETED',
  'FAILED',
  'CANCELLED',
];

const VERDICT_FILTERS = ['ALL', 'PASS', 'FAIL', 'INCONCLUSIVE', 'INVALID_RUN', 'ERROR'];

const ACTIVE_STATES = new Set([
  'PENDING',
  'VALIDATING',
  'PROVISIONING',
  'PREPARING_FAULT',
  'STARTING',
  'RUNNING',
  'INJECTING',
  'OBSERVING_RECOVERY',
  'EVALUATING',
  'FINALIZING',
]);

function duration(run: TestCaseRun): string {
  if (!run.started_at) return '—';
  const start = new Date(run.started_at).getTime();
  const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return '—';
  return formatDuration(Math.max(0, end - start));
}

export const TestRuns: React.FC = () => {
  const { appId } = useParams<{ appId: string }>();
  const { application } = useScopedApplication(appId);

  const [lifecycle, setLifecycle] = useState('ALL');
  const [verdict, setVerdict] = useState('ALL');
  const [recoverOpen, setRecoverOpen] = useState(false);
  const [recovering, setRecovering] = useState(false);

  const loadRuns = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    return api.listTestRuns(appId, {
      lifecycle_state: lifecycle === 'ALL' ? undefined : lifecycle,
      verdict: verdict === 'ALL' ? undefined : verdict,
      limit: 200,
    });
  }, [appId, lifecycle, verdict]);

  const { data, loading, error, reload } = useApiResource(loadRuns);

  const recover = async () => {
    if (!appId) return;
    setRecovering(true);
    try {
      const result = await api.recoverInterruptedRuns(appId);
      toast.info(
        result.recovered.length === 0
          ? 'No interrupted runs to finalize'
          : `Finalized ${result.recovered.length} interrupted run${result.recovered.length === 1 ? '' : 's'}`,
      );
      setRecoverOpen(false);
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not recover runs');
    } finally {
      setRecovering(false);
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

  const runs = data ?? [];
  const activeCount = runs.filter((run) => ACTIVE_STATES.has(run.lifecycle_state)).length;

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        <PageHeader
          title="Reliability test runs"
          description={`Runs started from approved plan revisions for ${application?.name ?? 'this application'}. Lifecycle status and reliability verdict are separate fields.`}
          eyebrow={
            <Link
              to={`/applications/${appId}/reliability`}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
            >
              <ArrowLeft className="w-3.5 h-3.5" /> Back to planning
            </Link>
          }
          actions={
            <>
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <button
                onClick={() => setRecoverOpen(true)}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
                title="Finalize runs left behind by an interrupted backend"
              >
                <RotateCcw className="w-3.5 h-3.5" /> Recover interrupted
              </button>
            </>
          }
        />

        {error && <ErrorState message={error} onRetry={reload} />}

        <SectionCard
          title="Run history"
          description={
            data
              ? `${runs.length} run${runs.length === 1 ? '' : 's'}${
                  activeCount > 0 ? ` · ${activeCount} active` : ''
                }`
              : 'Loading…'
          }
          icon={<Play className="w-4 h-4 text-[#C9D1D9]" />}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={lifecycle}
                onChange={(event) => setLifecycle(event.target.value)}
                className="px-2.5 py-1.5 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg"
                aria-label="Filter by lifecycle state"
              >
                {LIFECYCLE_FILTERS.map((state) => (
                  <option key={state} value={state}>
                    {state === 'ALL' ? 'All lifecycle states' : state.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
              <select
                value={verdict}
                onChange={(event) => setVerdict(event.target.value)}
                className="px-2.5 py-1.5 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg"
                aria-label="Filter by verdict"
              >
                {VERDICT_FILTERS.map((value) => (
                  <option key={value} value={value}>
                    {value === 'ALL' ? 'All verdicts' : value.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </div>
          }
          bodyClassName="p-0"
        >
          {loading && !data ? (
            <LoadingState label="Loading test runs…" />
          ) : runs.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<Play className="w-5 h-5" />}
                title="No test runs"
                description="Approve a plan revision and start a READY test case from the plan detail page. Runs cannot be created by opening this page."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-[#000000] text-[10px] uppercase tracking-wider text-[#B1BAC4]">
                  <tr>
                    <th className="px-5 py-2.5 font-semibold">Run</th>
                    <th className="px-3 py-2.5 font-semibold">Case</th>
                    <th className="px-3 py-2.5 font-semibold">Scenario</th>
                    <th className="px-3 py-2.5 font-semibold">Started</th>
                    <th className="px-3 py-2.5 font-semibold">Duration</th>
                    <th className="px-3 py-2.5 font-semibold">Lifecycle</th>
                    <th className="px-3 py-2.5 font-semibold">Verdict</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#30363D]">
                  {runs.map((run) => (
                    <tr key={run.id} className="hover:bg-[#000000] transition-colors">
                      <td className="px-5 py-3">
                        <Link
                          to={`/applications/${appId}/reliability/runs/${run.id}`}
                          className="font-mono text-[11px] text-[#F0F6FC] hover:text-[#C9D1D9]"
                        >
                          {shortId(run.id, 10)}
                        </Link>
                        {run.error_message && (
                          <div
                            className="text-[10px] text-[#FF7B72] truncate max-w-[220px]"
                            title={run.error_message}
                          >
                            {run.error_message}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-3 max-w-[220px]">
                        <span className="font-mono text-[11px] text-[#C9D1D9] block truncate" title={run.case_key}>
                          {run.case_key}
                        </span>
                        <span className="text-[10px] text-[#B1BAC4] font-mono">
                          {run.trigger_type}
                          {run.checkpoint_name ? ` · ${run.checkpoint_name}` : ''}
                        </span>
                      </td>
                      <td className="px-3 py-3 font-mono text-[11px] text-[#C9D1D9]">{run.scenario_id}</td>
                      <td className="px-3 py-3 whitespace-nowrap text-[11px] text-[#B1BAC4]">
                        {formatDateTime(run.started_at ?? run.created_at)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap text-[11px] font-mono text-[#C9D1D9]">
                        {duration(run)}
                      </td>
                      <td className="px-3 py-3">
                        <StatusBadge status={run.lifecycle_state} />
                      </td>
                      <td className="px-3 py-3">
                        <VerdictBadge verdict={run.verdict} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      </div>

      <ConfirmationDialog
        isOpen={recoverOpen}
        title="Recover interrupted runs"
        message="VeriQ finalizes active runs whose orchestrator no longer exists: their evidence is kept, the verdict becomes INCONCLUSIVE and environments are cleaned up. It never re-submits a task."
        confirmLabel="Recover runs"
        isDestructive={false}
        isBusy={recovering}
        onConfirm={recover}
        onCancel={() => setRecoverOpen(false)}
      />
    </Layout>
  );
};

export default TestRuns;
