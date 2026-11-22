import React, { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  CheckCircle2,
  FlaskConical,
  Play,
  RefreshCw,
  SkipForward,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import type { TestPlanTestCase, TestPlanValidation } from '../api/types';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pill,
  SectionCard,
  StatusBadge,
  Tooltip,
} from '../components/ui';
import { CompatibilityBadge, VerdictBadge } from '../components/reliability';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import { formatDateTime, formatRelative, shortId } from '../lib/format';
import { prettyJson } from '../lib/json';

const IssueList: React.FC<{ issues: string[] }> = ({ issues }) => (
  <span className="block space-y-1">
    {issues.map((issue) => (
      <span key={issue} className="block">
        {issue}
      </span>
    ))}
  </span>
);

export const ReliabilityPlan: React.FC = () => {
  const { appId, planId } = useParams<{ appId: string; planId: string }>();
  useScopedApplication(appId);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    if (!appId || !planId) throw new Error('No plan selected');
    const [plan, capabilities, runs] = await Promise.all([
      api.getTestPlan(appId, planId),
      api.runnerCapabilities(appId),
      api.listTestRuns(appId, { plan_id: planId, limit: 50 }),
    ]);
    const revision = plan.latest_revision?.revision ?? plan.current_revision;
    const cases =
      revision > 0 ? await api.listPlanTestCases(appId, planId, revision, { limit: 1000 }) : [];
    return { plan, capabilities, runs, cases };
  }, [appId, planId]);

  const { data, loading, error, reload } = useApiResource(load);

  const [validation, setValidation] = useState<TestPlanValidation | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [startCase, setStartCase] = useState<TestPlanTestCase | null>(null);

  const plan = data?.plan;
  const cases = useMemo(() => data?.cases ?? [], [data]);
  const runnerEnabled = data?.capabilities.runner_enabled ?? false;

  const selectedCase = cases.find((item) => item.id === selectedCaseId) ?? null;
  const approvedCurrent =
    plan?.status === 'APPROVED' && plan.approved_revision === plan.current_revision;

  const readyCount = cases.filter((item) => item.status === 'READY').length;
  const blockedCount = cases.length - readyCount;
  const revision = plan?.latest_revision?.revision ?? plan?.current_revision ?? 0;

  /** Blocking evidence per case, from the frozen comparison and the last validation. */
  const caseIssues = useMemo(() => {
    const map = new Map<string, string[]>();
    const push = (key: string | undefined, message: string) => {
      if (!key) return;
      const existing = map.get(key) ?? [];
      if (!existing.includes(message)) existing.push(message);
      map.set(key, existing);
    };
    cases.forEach((item) => {
      item.compatibility.reasons
        .filter((reason) => reason.severity !== 'warning')
        .forEach((reason) => push(item.case_key, `${reason.code}: ${reason.message}`));
    });
    validation?.blocking_issues.forEach((issue) => {
      push(
        String(issue.case_key ?? ''),
        String(issue.message ?? issue.code ?? 'Blocked case'),
      );
    });
    return map;
  }, [cases, validation]);

  const canApprove = plan?.status === 'READY_FOR_REVIEW' && blockedCount === 0 && !!revision;
  const approveHint = approvedCurrent
    ? `Revision ${revision} is already approved`
    : blockedCount > 0
      ? `Resolve ${blockedCount} blocking issue${blockedCount === 1 ? '' : 's'} to approve`
      : plan?.status !== 'READY_FOR_REVIEW'
        ? 'Submit this revision for review to approve'
        : `Approve revision ${revision}`;

  const runAction = async (action: 'generate' | 'validate' | 'submit' | 'approve' | 'revoke') => {
    if (!appId || !planId || !plan) return;
    setBusy(action);
    try {
      if (action === 'generate') {
        const result = await api.generateTestPlan(appId, planId);
        toast.success(`Generated revision ${result.revision.revision}`);
        setValidation(null);
        setSelectedCaseId(null);
      } else if (action === 'validate') {
        const result = await api.validateTestPlan(appId, planId);
        setValidation(result);
        toast[result.ok ? 'success' : 'info'](
          result.ok
            ? `Validation passed: ${result.ready_cases} ready case${result.ready_cases === 1 ? '' : 's'}`
            : `Validation found ${result.blocking_issues.length} blocking issue${result.blocking_issues.length === 1 ? '' : 's'}`,
        );
      } else if (action === 'submit') {
        await api.submitTestPlan(appId, planId);
        toast.success('Plan submitted for review');
      } else if (action === 'approve') {
        const updated = await api.approveTestPlan(appId, planId, plan.current_revision);
        toast.success(`Approved revision ${updated.approved_revision}`);
      } else {
        await api.revokeTestPlan(appId, planId);
        toast.info('Plan approval revoked');
      }
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Action failed');
    } finally {
      setBusy(null);
    }
  };

  const startRun = async () => {
    if (!appId || !planId || !startCase) return;
    setBusy('start');
    try {
      const result = await api.startTestRun(appId, planId, startCase.id);
      setStartCase(null);
      toast.success('Test run started in an isolated environment');
      navigate(`/applications/${appId}/reliability/runs/${result.run.id}`);
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not start the test run');
    } finally {
      setBusy(null);
    }
  };

  if (!appId || !planId) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <EmptyState title="No test plan selected" description="Choose a plan from reliability planning." />
        </div>
      </Layout>
    );
  }

  const secondaryButton =
    'inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium text-[#C9D1D9] bg-transparent border border-[#30363D] rounded-md hover:bg-[#161B22] disabled:opacity-40 disabled:cursor-not-allowed';

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-5">
        <PageHeader
          title={plan?.name ?? 'Test plan'}
          description={plan?.description ?? 'Immutable revisions, validation, review and explicit approval.'}
          eyebrow={
            <Link
              to={`/applications/${appId}/reliability`}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
            >
              <ArrowLeft className="w-3.5 h-3.5" /> Back to reliability planning
            </Link>
          }
          actions={
            <>
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <button
                onClick={() => runAction('generate')}
                disabled={busy !== null}
                className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] disabled:opacity-50"
              >
                <FlaskConical className="w-3.5 h-3.5" />
                {busy === 'generate' ? 'Generating…' : 'Generate matrix'}
              </button>
              <Tooltip content={approveHint} side="bottom">
                <button
                  onClick={() => runAction('approve')}
                  disabled={busy !== null || !canApprove}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-[#FFFFFF]"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  {approvedCurrent ? `Approved v${revision}` : `Approve revision ${revision || 1}`}
                </button>
              </Tooltip>
            </>
          }
        />

        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && !data ? (
          <LoadingState label="Loading test plan…" />
        ) : (
          <>
            {/* ------------------------------------------------------ status bar */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 bg-[#000000] border border-[#30363D] rounded-lg text-[11px] text-[#B1BAC4]">
              <span className="flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-[#7D8590]">
                  Plan status
                </span>
                <StatusBadge status={plan?.status} />
              </span>

              <span className="hidden sm:block w-px h-3.5 bg-[#30363D]" />

              <span className="flex items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-[#7D8590]">
                  Current revision
                </span>
                <span className="font-mono text-[#F0F6FC]">
                  {plan?.current_revision ? `v${plan.current_revision}` : '—'}
                </span>
                <span className="text-[#7D8590]">
                  {plan?.latest_revision ? `(${formatRelative(plan.latest_revision.created_at)})` : '(not generated)'}
                </span>
              </span>

              <span className="hidden sm:block w-px h-3.5 bg-[#30363D]" />

              <span className="flex items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-[#7D8590]">
                  Approved revision
                </span>
                <span className="font-mono text-[#F0F6FC]">
                  {plan?.approved_revision ? `v${plan.approved_revision}` : 'None'}
                </span>
                {plan?.approved_at && (
                  <span className="text-[#7D8590]">({formatDateTime(plan.approved_at)})</span>
                )}
              </span>

              <span className="hidden sm:block w-px h-3.5 bg-[#30363D]" />

              <span className="flex items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-[#7D8590]">
                  Test cases
                </span>
                <span className="text-[#F0F6FC]">{cases.length} total</span>
                <span className="text-emerald-400">{readyCount} ready</span>
                <span className={blockedCount > 0 ? 'text-rose-400' : 'text-[#7D8590]'}>
                  {blockedCount} blocked
                </span>
              </span>

              <div className="ml-auto flex flex-wrap items-center gap-1.5">
                <button
                  onClick={() => runAction('validate')}
                  disabled={busy !== null || !plan?.current_revision}
                  className={secondaryButton}
                >
                  {busy === 'validate' ? 'Validating…' : 'Validate'}
                </button>
                <button
                  onClick={() => runAction('submit')}
                  disabled={busy !== null || plan?.status !== 'VALIDATING'}
                  className={secondaryButton}
                  title="Only VALIDATING plans can be submitted"
                >
                  Submit for review
                </button>
                <button
                  onClick={() => runAction('revoke')}
                  disabled={busy !== null || !plan?.approved_revision}
                  className={`${secondaryButton} text-rose-400 hover:bg-rose-500/10`}
                >
                  <Ban className="w-3 h-3" /> Revoke
                </button>
              </div>
            </div>

            {!runnerEnabled && data && (
              <p className="text-[11px] text-[#B1BAC4] px-1">
                The backend reports the runner as disabled, so starting a run is not available.
                Planning and approval still work.
              </p>
            )}

            {validation && (
              <div className="flex flex-wrap items-center gap-2 px-1 text-[11px] text-[#B1BAC4]">
                <Pill tone={validation.ok ? 'sage' : 'rose'}>
                  {validation.ok ? 'VALID' : `${validation.blocking_issues.length} BLOCKING`}
                </Pill>
                <span className="font-mono text-[10px]">
                  revision {validation.revision} · {validation.ready_cases} ready ·{' '}
                  {validation.blocked_cases} blocked · {validation.total_cases} total
                </span>
                {validation.drift.length > 0 && (
                  <Tooltip
                    side="bottom"
                    content={<IssueList issues={validation.drift.map((entry) => String(entry.message ?? entry.case_key ?? entry.kind ?? 'drift'))} />}
                  >
                    <span className="inline-flex items-center gap-1 text-amber-400">
                      <AlertTriangle className="w-3 h-3" /> {validation.drift.length} drift
                    </span>
                  </Tooltip>
                )}
                {validation.warnings.length > 0 && (
                  <Tooltip
                    side="bottom"
                    content={<IssueList issues={validation.warnings.map((entry) => String(entry.message ?? entry.code ?? 'warning'))} />}
                  >
                    <span className="inline-flex items-center gap-1 text-[#C9D1D9]">
                      <AlertTriangle className="w-3 h-3" /> {validation.warnings.length} warning
                      {validation.warnings.length === 1 ? '' : 's'}
                    </span>
                  </Tooltip>
                )}
              </div>
            )}

            {/* ----------------------------------------------------- test matrix */}
            <SectionCard
              title={`Test Matrix${revision ? ` (Revision ${revision})` : ''}`}
              description={
                plan?.latest_revision
                  ? `${cases.length} case${cases.length === 1 ? '' : 's'} frozen for this revision`
                  : 'Generate a matrix to freeze task, scenario and trigger combinations'
              }
              icon={<FlaskConical className="w-4 h-4 text-[#C9D1D9]" />}
              bodyClassName="p-0"
            >
              {!plan?.latest_revision ? (
                <div className="p-5">
                  <EmptyState
                    icon={<FlaskConical className="w-5 h-5" />}
                    title="No matrix generated"
                    description="The matrix is built from the selected tasks' contracts, enabled scenarios and configured adapters. Generate it to inspect the cases."
                  />
                </div>
              ) : cases.length === 0 ? (
                <div className="p-5">
                  <EmptyState
                    title="No test cases"
                    description="The backend produced no cases for this revision. Enable compatible scenarios or add a test contract, then generate a new revision."
                  />
                </div>
              ) : (
                <div className="overflow-x-auto max-h-[70vh]">
                  <table className="w-full text-left text-xs border-separate border-spacing-0">
                    <thead className="sticky top-0 z-10 bg-[#0B0F14] text-[10px] uppercase tracking-wider text-[#7D8590]">
                      <tr>
                        <th className="px-4 py-2 font-semibold border-b border-[#30363D]">Case</th>
                        <th className="px-3 py-2 font-semibold border-b border-[#30363D]">Task</th>
                        <th className="px-3 py-2 font-semibold border-b border-[#30363D]">Scenario</th>
                        <th className="px-3 py-2 font-semibold border-b border-[#30363D]">Trigger</th>
                        <th className="px-3 py-2 font-semibold border-b border-[#30363D]">Status</th>
                        <th className="px-3 py-2 font-semibold border-b border-[#30363D]">Compatibility</th>
                        <th className="px-4 py-2 font-semibold border-b border-[#30363D] text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cases.map((testCase) => {
                        const issues = caseIssues.get(testCase.case_key) ?? [];
                        const blocked = testCase.status !== 'READY';
                        return (
                          <tr
                            key={testCase.id}
                            className={`transition-colors ${
                              selectedCaseId === testCase.id
                                ? 'bg-[#161B22]'
                                : 'hover:bg-[#161B22]/60'
                            }`}
                          >
                            <td className="px-4 py-2 border-b border-[#30363D]/70">
                              <button
                                onClick={() =>
                                  setSelectedCaseId(
                                    selectedCaseId === testCase.id ? null : testCase.id,
                                  )
                                }
                                className="font-mono text-[11px] text-[#F0F6FC] hover:text-[#C9D1D9] underline-offset-2 hover:underline"
                              >
                                {testCase.case_key}
                              </button>
                              <div className="text-[10px] text-[#7D8590] font-mono">
                                {shortId(testCase.id, 8)}
                              </div>
                            </td>
                            <td className="px-3 py-2 border-b border-[#30363D]/70 max-w-[180px]">
                              <span
                                className="font-mono text-[11px] text-[#C9D1D9] block truncate"
                                title={testCase.task_name}
                              >
                                {testCase.task_name}
                              </span>
                            </td>
                            <td className="px-3 py-2 border-b border-[#30363D]/70">
                              <div className="flex items-center gap-1.5">
                                <Pill tone="muted">{testCase.scenario_id}</Pill>
                                {(blocked || issues.length > 0) && (
                                  <Tooltip
                                    content={
                                      issues.length > 0 ? (
                                        <IssueList issues={issues} />
                                      ) : (
                                        'Blocked by the backend compatibility check'
                                      )
                                    }
                                  >
                                    <AlertTriangle className="w-3 h-3 text-rose-400/80 shrink-0" />
                                  </Tooltip>
                                )}
                              </div>
                            </td>
                            <td className="px-3 py-2 border-b border-[#30363D]/70 text-[11px] text-[#C9D1D9]">
                              {testCase.trigger_type}
                              {testCase.checkpoint_name && (
                                <span className="text-[10px] text-[#7D8590] font-mono">
                                  {' '}
                                  · {testCase.checkpoint_name}
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 border-b border-[#30363D]/70">
                              <StatusBadge status={testCase.status} />
                            </td>
                            <td className="px-3 py-2 border-b border-[#30363D]/70">
                              <CompatibilityBadge status={testCase.compatibility.status} />
                            </td>
                            <td className="px-4 py-2 border-b border-[#30363D]/70 text-right whitespace-nowrap">
                              {blocked ? (
                                <Tooltip content={issues.length > 0 ? <IssueList issues={issues} /> : approveHint}>
                                  <span className="text-[10px] font-medium text-rose-400/70 cursor-help">
                                    Blocked
                                  </span>
                                </Tooltip>
                              ) : approvedCurrent && runnerEnabled ? (
                                <button
                                  onClick={() => setStartCase(testCase)}
                                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-md"
                                >
                                  <Play className="w-3 h-3" /> Run
                                </button>
                              ) : (
                                <Tooltip
                                  content={
                                    !runnerEnabled
                                      ? 'The backend reports the runner as disabled'
                                      : approveHint
                                  }
                                >
                                  <span className="text-[10px] text-[#7D8590] cursor-help">
                                    {!runnerEnabled ? 'Runner disabled' : 'Approve to run'}
                                  </span>
                                </Tooltip>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>

            {selectedCase && (
              <SectionCard
                title={`Case ${selectedCase.case_key}`}
                description="Frozen configuration and backend compatibility evidence"
                icon={<SkipForward className="w-4 h-4 text-[#C9D1D9]" />}
                actions={
                  <button
                    onClick={() => setSelectedCaseId(null)}
                    className="text-[11px] text-[#B1BAC4] hover:text-[#F0F6FC]"
                  >
                    Close
                  </button>
                }
              >
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="space-y-3">
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Compatibility reasons
                      </span>
                      {selectedCase.compatibility.reasons.length === 0 ? (
                        <p className="text-[11px] text-[#3e563a] mt-1">
                          No blocking reasons reported by the backend.
                        </p>
                      ) : (
                        <ul className="mt-1 space-y-1">
                          {selectedCase.compatibility.reasons.map((reason) => (
                            <li
                              key={`${reason.code}-${reason.message}`}
                              className={`text-[11px] leading-relaxed ${
                                reason.severity === 'warning' ? 'text-[#C9D1D9]' : 'text-rose-400'
                              }`}
                            >
                              <span className="font-mono text-[10px]">{reason.code}: </span>
                              {reason.message}
                            </li>
                          ))}
                        </ul>
                      )}
                      {selectedCase.compatibility.reasons.some(
                        (reason) =>
                          reason.code === 'HTTP_DEPENDENCY_URL_MISSING' ||
                          reason.code === 'HTTP_DEPENDENCY_URL_INVALID',
                      ) && (
                        <p className="mt-2 text-[11px] text-amber-400 leading-relaxed">
                          This case is blocked because the HTTP fault proxy has no upstream
                          dependency. Open the task from Reliability planning, set the upstream
                          dependency URL on the '{selectedCase.scenario_id}' scenario, save it,
                          then regenerate this plan revision.
                        </p>
                      )}
                    </div>
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Recovery policy
                      </span>
                      <pre className="mt-1 p-2.5 rounded-lg bg-[#000000] border border-[#30363D] text-[10.5px] font-mono overflow-x-auto">
                        {prettyJson(selectedCase.recovery_policy ?? {}) || '—'}
                      </pre>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Adapters
                      </span>
                      <pre className="mt-1 p-2.5 rounded-lg bg-[#000000] border border-[#30363D] text-[10.5px] font-mono overflow-x-auto">
                        {prettyJson(selectedCase.adapter_refs) || '—'}
                      </pre>
                    </div>
                  </div>
                  <div className="space-y-3">
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Test input / fixture
                      </span>
                      <pre className="mt-1 p-2.5 rounded-lg bg-[#000000] border border-[#30363D] text-[10.5px] font-mono overflow-x-auto">
                        {prettyJson(selectedCase.test_input ?? {}) || '—'}
                        {selectedCase.input_fixture_ref
                          ? `\nfixture: ${selectedCase.input_fixture_ref}`
                          : ''}
                      </pre>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Scenario configuration
                      </span>
                      <pre className="mt-1 p-2.5 rounded-lg bg-[#000000] border border-[#30363D] text-[10.5px] font-mono overflow-x-auto">
                        {prettyJson(selectedCase.scenario_config ?? {}) || '{}'}
                      </pre>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Assertions
                      </span>
                      <pre className="mt-1 p-2.5 rounded-lg bg-[#000000] border border-[#30363D] text-[10.5px] font-mono overflow-x-auto max-h-40">
                        {prettyJson(selectedCase.assertions) || '[]'}
                      </pre>
                    </div>
                    <div className="text-[10px] text-[#B1BAC4] font-mono break-all">
                      fingerprint: {selectedCase.configuration_fingerprint}
                      <br />
                      contract: {selectedCase.contract_version ? `v${selectedCase.contract_version}` : 'none'}
                      <br />
                      cleanup: {prettyJson(selectedCase.cleanup ?? {}) || 'none'}
                    </div>
                  </div>
                </div>
              </SectionCard>
            )}

            <SectionCard
              title="Runs for this plan"
              description="Every run started from an approved revision"
              icon={<Play className="w-4 h-4 text-[#C9D1D9]" />}
              actions={
                <Link
                  to={`/applications/${appId}/reliability/runs`}
                  className="text-[11px] font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
                >
                  All test runs
                </Link>
              }
              bodyClassName="p-0"
            >
              {(data?.runs.length ?? 0) === 0 ? (
                <p className="px-5 py-4 text-[11px] text-[#B1BAC4]">
                  No runs yet.{' '}
                  {approvedCurrent
                    ? 'Start a ready case above.'
                    : 'Approve the revision to start.'}
                </p>
              ) : (
                <div className="divide-y divide-[#30363D]">
                  {data?.runs.map((run) => (
                    <Link
                      key={run.id}
                      to={`/applications/${appId}/reliability/runs/${run.id}`}
                      className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5 hover:bg-[#161B22]/60"
                    >
                      <div className="min-w-0">
                        <div className="text-xs font-mono text-[#F0F6FC] truncate">{run.case_key}</div>
                        <div className="text-[10px] text-[#7D8590]">
                          {shortId(run.id, 10)} · {run.scenario_id} · {formatDateTime(run.created_at)}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusBadge status={run.lifecycle_state} />
                        <VerdictBadge verdict={run.verdict} />
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </SectionCard>
          </>
        )}
      </div>

      <ConfirmationDialog
        isOpen={!!startCase}
        title="Start isolated test run?"
        message={
          startCase
            ? `This starts "${startCase.case_key}" (${startCase.task_name}, ${startCase.scenario_id}, trigger ${startCase.trigger_type}) in an isolated environment. It inherits the approved revision ${plan?.approved_revision}. VeriQ will provision its own worker, broker and database, inject the configured fault and evaluate recovery. Nothing is executed until you confirm.`
            : ''
        }
        confirmLabel={busy === 'start' ? 'Starting…' : 'Start test run'}
        cancelLabel="Cancel"
        isDestructive={false}
        isBusy={busy === 'start'}
        onConfirm={startRun}
        onCancel={() => setStartCase(null)}
      />

    </Layout>
  );
};

export default ReliabilityPlan;
