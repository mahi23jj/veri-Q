import React, { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  ArrowLeft,
  Ban,
  CheckCircle2,
  FlaskConical,
  Play,
  RefreshCw,
  ShieldCheck,
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
} from '../components/ui';
import { CompatibilityBadge, VerdictBadge } from '../components/reliability';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import { formatDateTime, formatRelative, shortId } from '../lib/format';
import { prettyJson } from '../lib/json';

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
  const cases = data?.cases ?? [];
  const runnerEnabled = data?.capabilities.runner_enabled ?? false;

  const selectedCase = cases.find((item) => item.id === selectedCaseId) ?? null;
  const approvedCurrent =
    plan?.status === 'APPROVED' && plan.approved_revision === plan.current_revision;

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

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
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
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <button
                onClick={() => runAction('generate')}
                disabled={busy !== null}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg disabled:opacity-60"
              >
                <FlaskConical className="w-3.5 h-3.5" />
                {busy === 'generate' ? 'Generating…' : 'Generate matrix'}
              </button>
            </>
          }
        />

        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && !data ? (
          <LoadingState label="Loading test plan…" />
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="p-4 bg-[#000000] rounded-xl border border-[#30363D]">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Plan status
                </span>
                <div className="mt-1.5">
                  <StatusBadge status={plan?.status} />
                </div>
              </div>
              <div className="p-4 bg-[#000000] rounded-xl border border-[#30363D]">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Current revision
                </span>
                <div className="mt-1 font-serif font-bold text-xl text-[#F0F6FC]">
                  {plan?.current_revision || '—'}
                </div>
                <div className="text-[10px] text-[#B1BAC4]">
                  {plan?.latest_revision
                    ? formatRelative(plan.latest_revision.created_at)
                    : 'not generated'}
                </div>
              </div>
              <div className="p-4 bg-[#000000] rounded-xl border border-[#30363D]">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Approved revision
                </span>
                <div className="mt-1 font-serif font-bold text-xl text-[#F0F6FC]">
                  {plan?.approved_revision ?? 'None'}
                </div>
                <div className="text-[10px] text-[#B1BAC4]">
                  {plan?.approved_at ? formatDateTime(plan.approved_at) : 'not approved'}
                </div>
              </div>
              <div className="p-4 bg-[#000000] rounded-xl border border-[#30363D]">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Test cases
                </span>
                <div className="mt-1 font-serif font-bold text-xl text-[#F0F6FC]">{cases.length}</div>
                <div className="text-[10px] text-[#B1BAC4]">
                  {cases.filter((item) => item.status === 'READY').length} ready ·{' '}
                  {cases.filter((item) => item.status !== 'READY').length} blocked
                </div>
              </div>
            </div>

            <SectionCard
              title="Review and approval"
              description="Approval is bound to one immutable revision; any later change invalidates it"
              icon={<ShieldCheck className="w-4 h-4 text-[#C9D1D9]" />}
            >
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => runAction('validate')}
                  disabled={busy !== null || !plan?.current_revision}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] disabled:opacity-40"
                >
                  Validate revision
                </button>
                <button
                  onClick={() => runAction('submit')}
                  disabled={busy !== null || plan?.status !== 'VALIDATING'}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] disabled:opacity-40"
                  title="Only VALIDATING plans can be submitted"
                >
                  Submit for review
                </button>
                <button
                  onClick={() => runAction('approve')}
                  disabled={busy !== null || plan?.status !== 'READY_FOR_REVIEW'}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[11px] font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg disabled:opacity-40"
                  title="Only READY_FOR_REVIEW plans can be approved"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Approve revision {plan?.current_revision}
                </button>
                <button
                  onClick={() => runAction('revoke')}
                  disabled={busy !== null || !plan?.approved_revision}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-[#FF7B72] bg-[#000000] border border-[#F85149]/30 rounded-lg hover:bg-[#F85149]/10 disabled:opacity-40"
                >
                  <Ban className="w-3.5 h-3.5" /> Revoke approval
                </button>
              </div>

              <p className="mt-3 text-[11px] text-[#B1BAC4] leading-relaxed">
                A plan must be generated, validated, submitted and approved before a test case can run.
                If the configuration changes after approval, the backend clears the approval instead of
                presenting a stale approved revision.
              </p>
              {!runnerEnabled && data && (
                <p className="mt-3 p-3 rounded-lg bg-[#C9D1D9]/25 border border-[#C9D1D9]/60 text-[11px] text-[#C9D1D9] leading-relaxed">
                  The backend reports the runner as disabled, so starting a run is not available.
                  Planning and approval still work.
                </p>
              )}

              {validation && (
                <div className="mt-4 p-3.5 rounded-lg border border-[#30363D] bg-[#000000] space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-[#F0F6FC]">Validation</span>
                    <Pill tone={validation.ok ? 'sage' : 'rose'}>
                      {validation.ok ? 'OK' : 'BLOCKING ISSUES'}
                    </Pill>
                    <span className="text-[10px] text-[#B1BAC4] font-mono">
                      revision {validation.revision} · {validation.ready_cases} ready ·{' '}
                      {validation.blocked_cases} blocked · {validation.total_cases} total
                    </span>
                  </div>
                  {validation.blocking_issues.length === 0 && validation.drift.length === 0 && (
                    <p className="text-[11px] text-[#3e563a]">
                      Revision matches the current configuration and every case is ready.
                    </p>
                  )}
                  {validation.drift.map((entry, index) => (
                    <div key={`drift-${index}`} className="text-[11px] text-[#C9D1D9]">
                      <span className="font-mono text-[10px]">{String(entry.kind ?? 'drift')}: </span>
                      {String(entry.message ?? entry.case_key ?? '')}
                    </div>
                  ))}
                  {validation.blocking_issues.map((entry, index) => (
                    <div key={`blocked-${index}`} className="text-[11px] text-[#FF7B72]">
                      <span className="font-mono text-[10px]">
                        {String(entry.case_key ?? entry.code ?? 'blocked')}:{' '}
                      </span>
                      {String(entry.message ?? entry.status ?? 'blocked case')}
                    </div>
                  ))}
                  {validation.warnings.map((entry, index) => (
                    <div key={`warning-${index}`} className="text-[11px] text-[#C9D1D9]">
                      <span className="font-mono text-[10px]">
                        {String(entry.code ?? 'warning')}:{' '}
                      </span>
                      {String(entry.message ?? '')}
                    </div>
                  ))}
                </div>
              )}
            </SectionCard>

            <SectionCard
              title="Test matrix"
              description={
                plan?.latest_revision
                  ? `Revision ${plan.latest_revision.revision} · ${plan.latest_revision.status}`
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
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-[#000000] text-[10px] uppercase tracking-wider text-[#B1BAC4]">
                      <tr>
                        <th className="px-5 py-2.5 font-semibold">Case</th>
                        <th className="px-3 py-2.5 font-semibold">Task</th>
                        <th className="px-3 py-2.5 font-semibold">Scenario</th>
                        <th className="px-3 py-2.5 font-semibold">Trigger</th>
                        <th className="px-3 py-2.5 font-semibold">Status</th>
                        <th className="px-3 py-2.5 font-semibold">Compatibility</th>
                        <th className="px-3 py-2.5" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#30363D]">
                      {cases.map((testCase) => (
                        <tr
                          key={testCase.id}
                          className={`hover:bg-[#000000] transition-colors ${
                            selectedCaseId === testCase.id ? 'bg-[#C9D1D9]/8' : ''
                          }`}
                        >
                          <td className="px-5 py-3">
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
                            <div className="text-[10px] text-[#B1BAC4] font-mono">
                              {shortId(testCase.id, 8)}
                            </div>
                          </td>
                          <td className="px-3 py-3 max-w-[200px]">
                            <span className="font-mono text-[11px] text-[#C9D1D9] block truncate" title={testCase.task_name}>
                              {testCase.task_name}
                            </span>
                          </td>
                          <td className="px-3 py-3">
                            <Pill tone="blue">{testCase.scenario_id}</Pill>
                            <div className="text-[10px] text-[#B1BAC4] font-mono mt-0.5">
                              v{testCase.scenario_version}
                            </div>
                          </td>
                          <td className="px-3 py-3 text-[11px] text-[#C9D1D9]">
                            {testCase.trigger_type}
                            {testCase.checkpoint_name && (
                              <div className="text-[10px] text-[#B1BAC4] font-mono">
                                {testCase.checkpoint_name}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-3">
                            <StatusBadge status={testCase.status} />
                          </td>
                          <td className="px-3 py-3">
                            <CompatibilityBadge status={testCase.compatibility.status} />
                          </td>
                          <td className="px-3 py-3 text-right">
                            {approvedCurrent && runnerEnabled && testCase.status === 'READY' ? (
                              <button
                                onClick={() => setStartCase(testCase)}
                                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg"
                              >
                                <Play className="w-3 h-3" /> Start
                              </button>
                            ) : (
                              <span className="text-[10px] text-[#B1BAC4]">
                                {testCase.status !== 'READY'
                                  ? 'Blocked'
                                  : !runnerEnabled
                                    ? 'Runner disabled'
                                    : 'Approve to run'}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
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
                                reason.severity === 'warning' ? 'text-[#C9D1D9]' : 'text-[#FF7B72]'
                              }`}
                            >
                              <span className="font-mono text-[10px]">{reason.code}: </span>
                              {reason.message}
                            </li>
                          ))}
                        </ul>
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
                <div className="p-5">
                  <EmptyState
                    icon={<Play className="w-5 h-5" />}
                    title="No runs yet"
                    description={
                      approvedCurrent
                        ? 'Approve is recorded. Start a READY test case above to execute it in isolation.'
                        : 'Generate, validate and approve the current revision to unlock the Start action.'
                    }
                  />
                </div>
              ) : (
                <div className="divide-y divide-[#30363D]">
                  {data?.runs.map((run) => (
                    <Link
                      key={run.id}
                      to={`/applications/${appId}/reliability/runs/${run.id}`}
                      className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 hover:bg-[#000000]"
                    >
                      <div className="min-w-0">
                        <div className="text-xs font-mono text-[#F0F6FC] truncate">{run.case_key}</div>
                        <div className="text-[10px] text-[#B1BAC4]">
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

            {plan?.latest_revision && (
              <div className="text-[11px] text-[#B1BAC4] flex flex-wrap items-center justify-between gap-2">
                <span>
                  Matrix summary: {prettyJson(plan.latest_revision.summary ?? {}) || '—'}
                </span>
                <span className="font-mono">
                  revision id {shortId(plan.latest_revision.id, 10)}
                </span>
              </div>
            )}
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
