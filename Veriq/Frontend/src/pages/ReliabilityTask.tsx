import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  AlertTriangle,
  ArrowLeft,
  Braces,
  ChevronDown,
  FileJson,
  Flag,
  ListChecks,
  Save,
  ShieldCheck,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api } from '../api/client';
import type {
  CompatibilityEvaluation,
  CompatibilityReason,
  RecoveryPolicy,
  ScenarioDefinition,
  TaskScenarioItem,
  TestContractPayload,
} from '../api/types';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pill,
  SectionCard,
  StatusBadge,
} from '../components/ui';
import { CompatibilityBadge } from '../components/reliability';
import { formatRelative } from '../lib/format';
import { parseJsonArray, parseJsonObject, prettyJson } from '../lib/json';

const scenarioConfigProperties = (
  definition: ScenarioDefinition | undefined,
): Record<string, unknown> | null => {
  const schema = definition?.configuration_schema as
    | { properties?: Record<string, unknown> }
    | undefined;
  return schema?.properties ?? null;
};

/** The HTTP fault proxy scenarios declare 'dependency_url' in their schema. */
const supportsDependencyUrl = (definition: ScenarioDefinition | undefined): boolean => {
  const properties = scenarioConfigProperties(definition);
  return !!properties && Object.prototype.hasOwnProperty.call(properties, 'dependency_url');
};

const isAbsoluteHttpUrl = (value: string): boolean => {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
};

const DEFAULT_RECOVERY: RecoveryPolicy = {
  max_attempts: 3,
  per_attempt_timeout_seconds: 60,
  recovery_deadline_seconds: 120,
  expected_terminal_state: 'SUCCEEDED',
  expect_retry: null,
  expect_redelivery: null,
  settle_seconds: 3,
};

const ReasonList: React.FC<{ reasons: CompatibilityReason[] }> = ({ reasons }) => {
  if (reasons.length === 0) return null;
  return (
    <ul className="space-y-1">
      {reasons.map((reason) => (
        <li
          key={`${reason.code}-${reason.message}`}
          className={`flex items-start gap-1.5 text-[11px] leading-relaxed ${
            reason.severity === 'warning' ? 'text-[#C9D1D9]' : 'text-[#FF7B72]'
          }`}
        >
          <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
          <span>
            <span className="font-mono text-[10px] opacity-75">{reason.code}: </span>
            {reason.message}
          </span>
        </li>
      ))}
    </ul>
  );
};

export const ReliabilityTask: React.FC = () => {
  const { appId, taskId } = useParams<{ appId: string; taskId: string }>();
  const { application } = useScopedApplication(appId);

  const load = useCallback(async () => {
    if (!appId || !taskId) throw new Error('No task selected');
    const [overview, catalog] = await Promise.all([
      api.taskReliability(appId, taskId),
      api.listScenarios(),
    ]);
    return { overview, catalog };
  }, [appId, taskId]);

  const { data, loading, error, reload } = useApiResource(load);

  const [evaluation, setEvaluation] = useState<CompatibilityEvaluation[] | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [activeTab, setActiveTab] = useState<'scenarios' | 'contract'>('scenarios');

  const evaluateSelections = async () => {
    if (!appId || !taskId) return;
    const selections = (data?.overview.automatic_scenarios ?? [])
      .filter((scenario) => scenario.enabled)
      .map((scenario) => ({
        task_id: taskId,
        scenario_id: scenario.scenario_id,
        trigger_type: 'automatic' as const,
      }));
    if (selections.length === 0) {
      toast.info('Enable at least one automatic scenario first.');
      return;
    }
    setEvaluating(true);
    try {
      const result = await api.evaluateCompatibility(appId, selections);
      setEvaluation(result.results);
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not evaluate compatibility');
    } finally {
      setEvaluating(false);
    }
  };

  const scenarioDefinitions = useMemo(() => {
    const map = new Map<string, ScenarioDefinition>();
    data?.catalog.items.forEach((scenario) => map.set(scenario.id, scenario));
    return map;
  }, [data?.catalog.items]);

  /* ------------------------------------------------------------- contract */

  const contract = data?.overview.contract ?? null;
  const payload = contract?.payload ?? {};
  const recovery = (payload.recovery as Partial<RecoveryPolicy> | undefined) ?? {};

  const [safeInput, setSafeInput] = useState('{}');
  const [assertionsText, setAssertionsText] = useState('[]');
  const [measurementsText, setMeasurementsText] = useState('[]');
  const [cleanupText, setCleanupText] = useState('{"mode":"none"}');
  const [fixtureRef, setFixtureRef] = useState('');
  const [notes, setNotes] = useState('');
  const [maxAttempts, setMaxAttempts] = useState('3');
  const [attemptTimeout, setAttemptTimeout] = useState('60');
  const [recoveryDeadline, setRecoveryDeadline] = useState('120');
  const [terminalState, setTerminalState] = useState<'SUCCEEDED' | 'FAILED' | 'ANY'>('SUCCEEDED');
  const [expectRetry, setExpectRetry] = useState<'inherit' | 'true' | 'false'>('inherit');
  const [settleSeconds, setSettleSeconds] = useState('3');
  const [savingContract, setSavingContract] = useState(false);

  useEffect(() => {
    const current = data?.overview.contract?.payload;
    if (!current) return;
    const policy = (current.recovery as Partial<RecoveryPolicy> | undefined) ?? {};
    setSafeInput(prettyJson(current.safe_input ?? {}) || '{}');
    setAssertionsText(prettyJson(current.assertions ?? []) || '[]');
    setMeasurementsText(prettyJson(current.effect_measurements ?? []) || '[]');
    setCleanupText(prettyJson(current.cleanup ?? { mode: 'none' }) || '{"mode":"none"}');
    setFixtureRef(String(current.input_fixture_ref ?? ''));
    setNotes(String(current.notes ?? ''));
    setMaxAttempts(String(policy.max_attempts ?? DEFAULT_RECOVERY.max_attempts));
    setAttemptTimeout(
      String(policy.per_attempt_timeout_seconds ?? DEFAULT_RECOVERY.per_attempt_timeout_seconds),
    );
    setRecoveryDeadline(
      String(policy.recovery_deadline_seconds ?? DEFAULT_RECOVERY.recovery_deadline_seconds),
    );
    setTerminalState(
      (policy.expected_terminal_state as 'SUCCEEDED' | 'FAILED' | 'ANY') ?? 'SUCCEEDED',
    );
    setExpectRetry(
      policy.expect_retry === true ? 'true' : policy.expect_retry === false ? 'false' : 'inherit',
    );
    setSettleSeconds(String(policy.settle_seconds ?? DEFAULT_RECOVERY.settle_seconds));
  }, [data?.overview.contract]);

  const saveContract = async () => {
    if (!appId || !taskId) return;
    const parsed = parseJsonObject(safeInput);
    if (parsed.error || parsed.value === null) {
      toast.error(`Safe test input: ${parsed.error ?? 'invalid object'}`);
      return;
    }
    const parsedAssertions = parseJsonArray(assertionsText);
    if (parsedAssertions.error || parsedAssertions.value === null) {
      toast.error(`Assertions: ${parsedAssertions.error ?? 'invalid array'}`);
      return;
    }
    const parsedMeasurements = parseJsonArray(measurementsText);
    if (parsedMeasurements.error || parsedMeasurements.value === null) {
      toast.error(`Effect measurements: ${parsedMeasurements.error ?? 'invalid array'}`);
      return;
    }
    const parsedCleanup = parseJsonObject(cleanupText);
    if (parsedCleanup.error || parsedCleanup.value === null) {
      toast.error(`Cleanup: ${parsedCleanup.error ?? 'invalid object'}`);
      return;
    }
    const body: TestContractPayload = {
      safe_input: parsed.value,
      input_fixture_ref: fixtureRef.trim() || null,
      effect_measurements: parsedMeasurements.value,
      assertions: parsedAssertions.value,
      cleanup: parsedCleanup.value as TestContractPayload['cleanup'],
      recovery: {
        max_attempts: Number(maxAttempts) || DEFAULT_RECOVERY.max_attempts,
        per_attempt_timeout_seconds:
          Number(attemptTimeout) || DEFAULT_RECOVERY.per_attempt_timeout_seconds,
        recovery_deadline_seconds:
          Number(recoveryDeadline) || DEFAULT_RECOVERY.recovery_deadline_seconds,
        expected_terminal_state: terminalState,
        expect_retry: expectRetry === 'inherit' ? null : expectRetry === 'true',
        expect_redelivery: (recovery.expect_redelivery as boolean | null | undefined) ?? null,
        settle_seconds: Number(settleSeconds) || DEFAULT_RECOVERY.settle_seconds,
      },
      notes: notes.trim() || null,
    };
    setSavingContract(true);
    try {
      if (contract) {
        await api.updateContract(appId, contract.id, body);
        toast.success('Contract saved as a new version');
      } else {
        await api.createContract(appId, taskId, body);
        toast.success('Test contract created');
      }
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not save contract');
    } finally {
      setSavingContract(false);
    }
  };

  const validateContract = async () => {
    if (!appId || !contract) return;
    try {
      const result = await api.validateContract(appId, contract.id);
      if (result.valid) toast.success('Contract is valid');
      else toast.error(result.issues.map((issue) => issue.message).join('; ') || 'Contract is invalid');
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not validate contract');
    }
  };

  const saveScenario = async (scenarioId: string, enabled: boolean, configText: string) => {
    if (!appId || !taskId) throw new Error('No task selected');
    const parsed = parseJsonObject(configText);
    if (parsed.error || parsed.value === null) {
      throw new Error(`Scenario configuration: ${parsed.error ?? 'invalid object'}`);
    }
    await api.selectTaskScenario(appId, taskId, scenarioId, {
      enabled,
      config: parsed.value,
    });
    reload();
  };

  const saveCheckpointScenario = async (
    checkpointId: string,
    scenarioId: string,
    enabled: boolean,
  ) => {
    if (!appId) throw new Error('No application selected');
    await api.selectCheckpointScenario(appId, checkpointId, scenarioId, { enabled });
    reload();
  };

  const toggleCheckpoint = async (checkpointId: string, enabled: boolean) => {
    if (!appId) return;
    try {
      await api.updateCheckpointReliability(appId, checkpointId, enabled);
      toast.success(`Checkpoint reliability ${enabled ? 'enabled' : 'disabled'}`);
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not update checkpoint');
    }
  };

  if (!appId || !taskId) {
    return (
      <Layout>
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <EmptyState title="No task selected" description="Choose a task from reliability planning." />
        </div>
      </Layout>
    );
  }

  const overview = data?.overview;
  const task = overview?.registered_task;

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        <PageHeader
          title={task?.task_name ?? 'Task reliability configuration'}
          description={`Configure the safe test contract and the scenarios that should be planned for ${application?.name ?? 'this application'}.`}
          eyebrow={
            <Link
              to={`/applications/${appId}/reliability`}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
            >
              <ArrowLeft className="w-3.5 h-3.5" /> Back to reliability planning
            </Link>
          }
        />

        {error && <ErrorState message={error} onRetry={reload} />}

        {loading && !data ? (
          <LoadingState label="Loading task configuration…" />
        ) : (
          <>
            {(() => {
              const globalIssues = (overview?.contract_issues ?? []).filter((issue) =>
                ['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(issue.code),
              );
              if (globalIssues.length === 0) return null;
              return (
                <details className="rounded-xl border border-[#D29922]/40 bg-[#D29922]/10 px-4 py-3">
                  <summary className="cursor-pointer text-sm font-semibold text-[#E3B341]">
                    {globalIssues.length} global configuration issue
                    {globalIssues.length === 1 ? '' : 's'}
                  </summary>
                  <div className="mt-3 space-y-2">
                    {globalIssues.map((issue) => (
                      <p key={`${issue.code}-${issue.message}`} className="text-xs text-[#E3B341]">
                        <span className="font-mono text-[10px]">{issue.code}: </span>
                        {issue.message}
                      </p>
                    ))}
                  </div>
                </details>
              );
            })()}

            <div className="flex items-center gap-1 border-b border-[#30363D]">
              <button
                type="button"
                onClick={() => setActiveTab('scenarios')}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'scenarios'
                    ? 'border-[#F0F6FC] text-[#F0F6FC]'
                    : 'border-transparent text-[#B1BAC4] hover:text-[#F0F6FC]'
                }`}
              >
                Scenarios
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('contract')}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'contract'
                    ? 'border-[#F0F6FC] text-[#F0F6FC]'
                    : 'border-transparent text-[#B1BAC4] hover:text-[#F0F6FC]'
                }`}
              >
                Contract Settings
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-4 bg-[#000000] rounded-xl border border-[#30363D]">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Registered task
                </span>
                <div className="mt-1 text-xs font-mono text-[#F0F6FC] break-all">
                  {task?.task_name ?? '—'}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5">
                  <StatusBadge status={task?.status ?? 'UNKNOWN'} />
                  <span className="text-[10px] text-[#B1BAC4]">
                    last seen {formatRelative(task?.last_seen_at)}
                  </span>
                </div>
              </div>
              <div className="p-4 bg-[#000000] rounded-xl border border-[#30363D]">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Contract version
                </span>
                <div className="mt-1 font-serif font-bold text-xl text-[#F0F6FC]">
                  {contract ? `v${contract.version}` : 'None'}
                </div>
                <div className="text-[10px] text-[#B1BAC4] mt-0.5">
                  {contract ? `updated ${formatRelative(contract.updated_at)}` : 'Create one to enable assertions'}
                </div>
              </div>
              <div className="p-4 bg-[#000000] rounded-xl border border-[#30363D]">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Enabled scenarios
                </span>
                <div className="mt-1 font-serif font-bold text-xl text-[#F0F6FC]">
                  {overview
                    ? overview.automatic_scenarios.filter((scenario) => scenario.enabled).length +
                      overview.checkpoints.reduce(
                        (total, checkpoint) =>
                          total + checkpoint.scenarios.filter((scenario) => scenario.enabled).length,
                        0,
                      )
                    : 0}
                </div>
                <div className="text-[10px] text-[#B1BAC4] mt-0.5">
                  {overview?.checkpoints.length ?? 0} checkpoint
                  {(overview?.checkpoints.length ?? 0) === 1 ? '' : 's'} discovered
                </div>
              </div>
            </div>

            {task?.task_metadata && (
              <details className="rounded-xl border border-[#30363D] bg-[#000000] px-4 py-3">
                <summary className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold cursor-pointer">
                  Registered task metadata
                </summary>
                <pre className="mt-2 p-2.5 rounded-lg bg-[#000000] border border-[#30363D] text-[10px] font-mono overflow-x-auto">
                  {prettyJson(task.task_metadata)}
                </pre>
              </details>
            )}

            {activeTab === 'contract' && (
            <SectionCard
              title="Task test contract"
              description="Safe inputs and the recovery policy the runner will check"
              icon={<FileJson className="w-4 h-4 text-[#C9D1D9]" />}
              actions={
                contract ? (
                  <button
                    onClick={validateContract}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
                  >
                    <ShieldCheck className="w-3.5 h-3.5" /> Validate
                  </button>
                ) : undefined
              }
            >
              {overview?.contract_issues &&
                overview.contract_issues.filter(
                  (issue) =>
                    !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(issue.code),
                ).length > 0 && (
                <div className="mb-4 p-3 rounded-lg bg-[#F85149]/10 border border-[#F85149]/30 space-y-1">
                  {overview.contract_issues
                    .filter(
                      (issue) =>
                        !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(issue.code),
                    )
                    .map((issue) => (
                    <div key={`${issue.code}-${issue.message}`} className="text-[11px] text-[#FF7B72]">
                      <span className="font-mono text-[10px]">{issue.code}: </span>
                      {issue.message}
                    </div>
                    ))}
                </div>
              )}

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="space-y-3">
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Safe test input (JSON, never credentials)
                    </span>
                    <textarea
                      value={safeInput}
                      onChange={(event) => setSafeInput(event.target.value)}
                      rows={5}
                      className="mt-1 w-full px-3 py-2 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      placeholder='{"order_id": "test-order-1"}'
                    />
                    <span className="mt-1 block text-[10px] text-[#B1BAC4] leading-relaxed">
                      Dependency scenarios (dependency timeout, lost response) also need an
                      absolute http(s) URL here, or an upstream URL on the scenario
                      configuration, for the fault proxy to forward to.
                    </span>
                  </label>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Assertions (JSON array, required by most scenarios)
                    </span>
                    <textarea
                      value={assertionsText}
                      onChange={(event) => setAssertionsText(event.target.value)}
                      rows={4}
                      className="mt-1 w-full px-3 py-2 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      placeholder='[{"id":"task_succeeds","description":"Task succeeds","type":"execution_status","expected":"SUCCEEDED"}]'
                    />
                  </label>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Input fixture reference (optional)
                    </span>
                    <input
                      value={fixtureRef}
                      onChange={(event) => setFixtureRef(event.target.value)}
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      placeholder="fixture://checkout/order"
                    />
                  </label>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Notes
                    </span>
                    <textarea
                      value={notes}
                      onChange={(event) => setNotes(event.target.value)}
                      rows={2}
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg"
                    />
                  </label>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Effect measurements (JSON array, optional)
                    </span>
                    <textarea
                      value={measurementsText}
                      onChange={(event) => setMeasurementsText(event.target.value)}
                      rows={3}
                      className="mt-1 w-full px-3 py-2 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      placeholder="[]"
                    />
                  </label>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Cleanup (JSON object)
                    </span>
                    <textarea
                      value={cleanupText}
                      onChange={(event) => setCleanupText(event.target.value)}
                      rows={2}
                      className="mt-1 w-full px-3 py-2 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      placeholder='{"mode":"none"}'
                    />
                  </label>
                </div>

                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block">
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Max attempts
                      </span>
                      <input
                        value={maxAttempts}
                        onChange={(event) => setMaxAttempts(event.target.value)}
                        inputMode="numeric"
                        className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      />
                    </label>
                    <label className="block">
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Attempt timeout (s)
                      </span>
                      <input
                        value={attemptTimeout}
                        onChange={(event) => setAttemptTimeout(event.target.value)}
                        inputMode="numeric"
                        className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      />
                    </label>
                    <label className="block">
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Recovery deadline (s)
                      </span>
                      <input
                        value={recoveryDeadline}
                        onChange={(event) => setRecoveryDeadline(event.target.value)}
                        inputMode="numeric"
                        className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      />
                    </label>
                    <label className="block">
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                        Settle (s)
                      </span>
                      <input
                        value={settleSeconds}
                        onChange={(event) => setSettleSeconds(event.target.value)}
                        inputMode="numeric"
                        className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      />
                    </label>
                  </div>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Expected terminal state
                    </span>
                    <select
                      value={terminalState}
                      onChange={(event) =>
                        setTerminalState(event.target.value as 'SUCCEEDED' | 'FAILED' | 'ANY')
                      }
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg"
                    >
                      <option value="SUCCEEDED">SUCCEEDED</option>
                      <option value="FAILED">FAILED</option>
                      <option value="ANY">ANY</option>
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Retry expectation
                    </span>
                    <select
                      value={expectRetry}
                      onChange={(event) =>
                        setExpectRetry(event.target.value as 'inherit' | 'true' | 'false')
                      }
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg"
                    >
                      <option value="inherit">Inherit scenario default</option>
                      <option value="true">A retry must be requested</option>
                      <option value="false">No retry expected</option>
                    </select>
                  </label>
                  <p className="text-[10px] text-[#B1BAC4] leading-relaxed">
                    These values are stored in the contract payload. The runner evaluates them
                    against execution evidence only — no business-effect verification is performed.
                  </p>
                </div>
              </div>

              <div className="mt-4 flex items-center justify-between gap-2">
                <span className="text-[10px] text-[#B1BAC4]">
                  {contract
                    ? `Saving creates contract version v${contract.version + 1}`
                    : 'No contract exists for this task yet'}
                </span>
                <button
                  onClick={saveContract}
                  disabled={savingContract}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg disabled:opacity-60"
                >
                  <Save className="w-3.5 h-3.5" />
                  {savingContract ? 'Saving…' : contract ? 'Save new version' : 'Create contract'}
                </button>
              </div>
            </SectionCard>
            )}

            {activeTab === 'scenarios' && (
            <>
            <SectionCard
              title="Automatic scenarios"
              description="Compatibility is decided by the backend from contracts and configured adapters"
              icon={<ListChecks className="w-4 h-4 text-[#C9D1D9]" />}
              actions={
                <button
                  onClick={evaluateSelections}
                  disabled={evaluating}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] disabled:opacity-50"
                  title="Ask the backend to re-evaluate the enabled automatic selections"
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  {evaluating ? 'Evaluating…' : 'Re-check compatibility'}
                </button>
              }
            >
              {evaluation && (
                <div className="mb-3 p-3 rounded-lg border border-[#30363D] bg-[#000000] space-y-2">
                  <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                    Backend compatibility evaluation
                  </span>
                  {evaluation.map((result) => (
                    <div key={`${result.task_id}-${result.scenario_id}`} className="text-[11px] space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[#F0F6FC]">{result.scenario_id}</span>
                        <CompatibilityBadge status={result.status} />
                        <span className="text-[10px] text-[#B1BAC4]">
                          execution available: {result.execution_available ? 'yes' : 'no'}
                        </span>
                      </div>
                      <ReasonList reasons={result.reasons} />
                      <p className="text-[10px] text-[#B1BAC4]">{result.execution_note}</p>
                    </div>
                  ))}
                </div>
              )}
              {(overview?.automatic_scenarios.length ?? 0) === 0 ? (
                <EmptyState
                  title="No automatic scenarios"
                  description="The scenario catalogue returned no automatic scenarios for this task."
                />
              ) : (
                <div className="space-y-3">
                  {overview?.automatic_scenarios.map((item) => (
                    <ScenarioRowWithSave
                      key={item.scenario_id}
                      item={item}
                      definition={scenarioDefinitions.get(item.scenario_id)}
                      onSave={saveScenario}
                      onSaved={reload}
                    />
                  ))}
                </div>
              )}
            </SectionCard>

            <SectionCard
              title="Checkpoint scenarios"
              description="Checkpoints reported by the running task; each must be enabled for reliability testing"
              icon={<Flag className="w-4 h-4 text-[#C9D1D9]" />}
            >
              {(overview?.checkpoints.length ?? 0) === 0 ? (
                <EmptyState
                  icon={<Flag className="w-5 h-5" />}
                  title="No checkpoints reported"
                  description="Call veriq.checkpoint(name, payload) in the target task to make checkpoint-triggered scenarios available."
                />
              ) : (
                <div className="space-y-4">
                  {overview?.checkpoints.map((checkpoint) => (
                    <div
                      key={checkpoint.id}
                      className="rounded-lg border border-[#30363D] border-l-2 border-l-[#B1BAC4] bg-[#000000] overflow-hidden"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 border-b border-[#30363D]">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-xs font-semibold text-[#F0F6FC] font-mono truncate">
                            {checkpoint.name}
                          </span>
                          <Pill tone="muted">{checkpoint.report_count} reports</Pill>
                          {checkpoint.scenarios.reduce(
                            (total, scenario) =>
                              total +
                              [...scenario.compatibility.reasons, ...scenario.compatibility.warnings].filter(
                                (issue) =>
                                  !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(issue.code),
                              ).length,
                            0,
                          ) > 0 && (
                            <Pill tone="beige">
                              {checkpoint.scenarios.reduce(
                                (total, scenario) =>
                                  total +
                                  [...scenario.compatibility.reasons, ...scenario.compatibility.warnings].filter(
                                    (issue) =>
                                      !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(issue.code),
                                  ).length,
                                0,
                              )}{' '}
                              issues
                            </Pill>
                          )}
                          <span className="text-[10px] text-[#B1BAC4]">
                            last seen {formatRelative(checkpoint.last_seen_at)}
                          </span>
                        </div>
                        <label className="inline-flex items-center gap-1.5 text-[11px] text-[#C9D1D9]">
                          <input
                            type="checkbox"
                            checked={checkpoint.reliability_enabled}
                            onChange={(event) =>
                              toggleCheckpoint(checkpoint.id, event.target.checked)
                            }
                            className="accent-[#C9D1D9]"
                          />
                          Reliability enabled
                        </label>
                      </div>
                      <div className="p-3 space-y-2">
                        {checkpoint.scenarios.length === 0 ? (
                          <p className="text-[11px] text-[#B1BAC4]">
                            No scenario in the catalogue supports checkpoint triggers.
                          </p>
                        ) : (
                          checkpoint.scenarios.map((scenario) => {
                            const localIssues = [
                              ...scenario.compatibility.reasons,
                              ...scenario.compatibility.warnings,
                            ].filter((issue) =>
                              !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(issue.code),
                            );
                            return (
                              <details
                                key={scenario.scenario_id}
                                className="group rounded-lg border border-[#30363D] bg-[#000000]"
                              >
                                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3.5 py-3">
                                  <span className="flex min-w-0 items-center gap-2">
                                    <ChevronDown className="h-4 w-4 shrink-0 text-[#B1BAC4] transition-transform group-open:rotate-180" />
                                    <span className="min-w-0">
                                      <span className="block text-sm font-semibold text-[#F0F6FC]">
                                        {scenario.name}
                                      </span>
                                      <span className="mt-1 flex flex-wrap items-center gap-2">
                                        <CompatibilityBadge status={scenario.compatibility.status} />
                                        <Pill tone="muted">{scenario.scenario_id}</Pill>
                                        {localIssues.length > 0 && (
                                          <Pill tone="beige">{localIssues.length} issue{localIssues.length === 1 ? '' : 's'}</Pill>
                                        )}
                                      </span>
                                    </span>
                                  </span>
                                  <button
                                    type="button"
                                    role="switch"
                                    aria-checked={scenario.enabled}
                                    onClick={(event) => {
                                      event.preventDefault();
                                      saveCheckpointScenario(
                                        checkpoint.id,
                                        scenario.scenario_id,
                                        !scenario.enabled,
                                      ).catch((cause: unknown) =>
                                        toast.error(
                                          cause instanceof Error
                                            ? cause.message
                                            : 'Could not update scenario',
                                        ),
                                      );
                                    }}
                                    className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors ${
                                      scenario.enabled
                                        ? 'border-[#56D364] bg-[#56D364]'
                                        : 'border-[#30363D] bg-[#161B22]'
                                    }`}
                                  >
                                    <span
                                      className={`absolute top-0.5 h-5 w-5 rounded-full bg-[#FFFFFF] transition-transform ${
                                        scenario.enabled ? 'translate-x-[22px]' : 'translate-x-0.5'
                                      }`}
                                    />
                                  </button>
                                </summary>
                                <div className="border-t border-[#30363D] px-3.5 py-3 space-y-3">
                                  {scenario.description && (
                                    <p className="text-sm text-[#B1BAC4] leading-relaxed">
                                      {scenario.description}
                                    </p>
                                  )}
                                  <ReasonList reasons={scenario.compatibility.reasons.filter((reason) =>
                                    !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(reason.code),
                                  )} />
                                  {scenario.compatibility.warnings
                                    .filter((warning) =>
                                      !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(warning.code),
                                    )
                                    .map((warning) => (
                                      <p key={warning.code} className="text-xs text-[#E3B341]">
                                        <span className="font-mono text-[10px]">{warning.code}: </span>
                                        {warning.message}
                                      </p>
                                    ))}
                                </div>
                              </details>
                            );
                          })
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </SectionCard>
            </>
            )}
          </>
        )}
      </div>
    </Layout>
  );
};

/**
 * Wrapper that injects the save callback into the presentational scenario row.
 * Keeping the API call here means the row only handles its own draft state.
 */
const ScenarioRowWithSave: React.FC<{
  item: TaskScenarioItem;
  definition: ScenarioDefinition | undefined;
  onSave: (scenarioId: string, enabled: boolean, config: string) => Promise<void>;
  onSaved: () => void;
}> = ({ item, definition, onSave, onSaved }) => {
  const [open, setOpen] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const [enabled, setEnabled] = useState(item.enabled);
  const [config, setConfig] = useState(prettyJson(item.config ?? {}));
  const [dependencyUrl, setDependencyUrl] = useState(
    typeof item.config?.dependency_url === 'string' ? item.config.dependency_url : '',
  );
  const [configError, setConfigError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const needsDependencyUrl = supportsDependencyUrl(definition);
  const savedConfig = prettyJson(item.config ?? {});
  const savedDependencyUrl =
    typeof item.config?.dependency_url === 'string' ? item.config.dependency_url : '';

  useEffect(() => {
    setEnabled(item.enabled);
    setConfig(prettyJson(item.config ?? {}));
    setDependencyUrl(
      typeof item.config?.dependency_url === 'string' ? item.config.dependency_url : '',
    );
    setConfigError(null);
  }, [item.enabled, item.config]);

  const dirty =
    enabled !== item.enabled ||
    config !== savedConfig ||
    dependencyUrl !== savedDependencyUrl;
  const blocked = item.compatibility.status === 'UNSUPPORTED';

  const save = async () => {
    const parsed = parseJsonObject(config);
    if (parsed.error || parsed.value === null) {
      setConfigError(`Scenario configuration: ${parsed.error ?? 'invalid object'}`);
      return;
    }
    const merged: Record<string, unknown> = { ...parsed.value };
    if (needsDependencyUrl) {
      const trimmed = dependencyUrl.trim();
      if (trimmed && !isAbsoluteHttpUrl(trimmed)) {
        setConfigError('Upstream dependency URL must be an absolute http(s) URL');
        return;
      }
      if (trimmed) merged.dependency_url = trimmed;
      else delete merged.dependency_url;
    }
    setConfigError(null);
    setBusy(true);
    try {
      await onSave(item.scenario_id, enabled, JSON.stringify(merged, null, 2));
      toast.success(`Scenario "${item.name}" saved`);
      onSaved();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not save scenario');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-[#30363D] bg-[#000000] overflow-hidden">
      <div className="flex w-full items-center justify-between gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
        >
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-[#B1BAC4] transition-transform ${open ? 'rotate-180' : ''}`}
          />
          <span className="min-w-0">
            <span className="block text-lg font-semibold text-[#F0F6FC]">{item.name}</span>
            <span className="mt-1 flex flex-wrap items-center gap-2">
              <CompatibilityBadge status={item.compatibility.status} />
              <Pill tone="muted">{item.scenario_id}</Pill>
            </span>
          </span>
        </button>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          disabled={blocked}
          onClick={() => setEnabled((value) => !value)}
          className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors ${
            enabled
              ? 'border-[#56D364] bg-[#56D364]'
              : 'border-[#30363D] bg-[#161B22]'
          } ${blocked ? 'cursor-not-allowed opacity-40' : ''}`}
          title={blocked ? 'Unsupported by the backend' : enabled ? 'Disable scenario' : 'Enable scenario'}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-[#FFFFFF] transition-transform ${
              enabled ? 'translate-x-[22px]' : 'translate-x-0.5'
            }`}
          />
        </button>
      </div>

      {open && (
        <div className="border-t border-[#30363D] px-4 py-4 space-y-4">
          <p className="text-sm text-[#B1BAC4] leading-relaxed">{item.description}</p>

          {item.compatibility.reasons
            .filter((reason) =>
              !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(reason.code),
            ).length > 0 && (
            <ReasonList
              reasons={item.compatibility.reasons.filter(
                (reason) =>
                  !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(reason.code),
              )}
            />
          )}

          {item.compatibility.warnings
            .filter((warning) =>
              !['MISSING_EFFECT_MEASUREMENT', 'NO_CLEANUP_CONFIGURED'].includes(warning.code),
            )
            .map((warning) => (
              <p key={warning.code} className="text-sm text-[#E3B341] leading-relaxed">
                <span className="font-mono text-[10px]">{warning.code}: </span>
                {warning.message}
              </p>
            ))}

          {needsDependencyUrl && (
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                Upstream dependency URL
              </span>
              <input
                value={dependencyUrl}
                onChange={(event) => setDependencyUrl(event.target.value)}
                placeholder="https://sandbox.example/quote"
                className="mt-1 w-full px-3 py-2 text-sm bg-[#000000] border border-[#30363D] rounded-lg font-mono"
              />
              <span className="mt-1 block text-xs text-[#B1BAC4] leading-relaxed">
                The proxy forwards requests to this URL.
              </span>
            </label>
          )}

          <div className="flex items-center justify-end">
            <button
              type="button"
              onClick={() => setShowJson((value) => !value)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#30363D] px-2.5 py-1.5 text-xs text-[#C9D1D9]"
            >
              <Braces className="h-3.5 w-3.5" />
              {showJson ? 'Hide JSON' : 'Edit as JSON'}
            </button>
          </div>

          {showJson && (
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                Scenario configuration (JSON)
              </span>
              <textarea
                value={config}
                onChange={(event) => setConfig(event.target.value)}
                className="mt-1 h-48 w-full overflow-auto px-3 py-2 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg font-mono"
              />
            </label>
          )}

          {configError && <p className="text-xs text-[#FF7B72]">{configError}</p>}

          <div className="flex items-center justify-between gap-3 border-t border-[#30363D] pt-3">
            <span className="text-xs text-[#B1BAC4]">
              {dirty ? 'Unsaved changes' : 'Matches the backend selection'}
            </span>
            <button
              type="button"
              onClick={save}
              disabled={busy || !dirty}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#FFFFFF] px-3.5 py-2 text-xs font-semibold text-black disabled:opacity-40"
            >
              <Save className="h-3.5 w-3.5" />
              {busy ? 'Saving…' : 'Save scenario'}
            </button>
          </div>
        </div>
      )}
    </section>
  );
};

/** Small helper kept for checkpoint toggles that need a tick marker. */

export default ReliabilityTask;
