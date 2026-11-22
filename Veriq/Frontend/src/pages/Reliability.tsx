import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  ArrowRight,
  Boxes,
  Check,
  FlaskConical,
  ListChecks,
  Play,
  Plus,
  RefreshCw,
  ServerCog,
  Trash2,
  X,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useScopedApplication } from '../context/application-context';
import { useApiResource } from '../hooks/useApiResource';
import { api, ApiError } from '../api/client';
import type {
  AdapterType,
  ApplicationAdapter,
  RuntimeProfile,
  TaskTestContract,
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
import { formatDate, formatRelative, shortId } from '../lib/format';
import { parseJsonObject, prettyJson } from '../lib/json';

export const Reliability: React.FC = () => {
  const { appId } = useParams<{ appId: string }>();
  const { application } = useScopedApplication(appId);
  const navigate = useNavigate();

  const loadWorkspace = useCallback(async () => {
    if (!appId) throw new Error('No application selected');
    const [plans, tasks, contracts, adapterTypes, adapters, profile, capabilities] =
      await Promise.all([
        api.listTestPlans(appId),
        api.listApplicationTasks(appId, { limit: 1000 }),
        api.listContracts(appId),
        api.listApplicationAdapterTypes(appId),
        api.listAdapters(appId),
        api.getRuntimeProfile(appId),
        api.runnerCapabilities(appId),
      ]);
    return { plans, tasks, contracts, adapterTypes, adapters, profile, capabilities };
  }, [appId]);

  const { data, loading, error, reload } = useApiResource(loadWorkspace);

  const contractByTask = useMemo(() => {
    const map = new Map<string, TaskTestContract>();
    data?.contracts.forEach((contract) => map.set(contract.registered_task_id, contract));
    return map;
  }, [data?.contracts]);

  /* ------------------------------------------------------------- new plan */

  const [taskQuery, setTaskQuery] = useState('');
  const [planOpen, setPlanOpen] = useState(false);
  const [planName, setPlanName] = useState('');
  const [planDescription, setPlanDescription] = useState('');
  const [planTaskIds, setPlanTaskIds] = useState<string[]>([]);
  const [savingPlan, setSavingPlan] = useState(false);

  const toggleTask = (taskId: string) => {
    setPlanTaskIds((current) =>
      current.includes(taskId) ? current.filter((id) => id !== taskId) : [...current, taskId],
    );
  };

  const createPlan = async () => {
    if (!appId) return;
    if (!planName.trim() || planTaskIds.length === 0) {
      toast.error('Give the plan a name and select at least one task.');
      return;
    }
    setSavingPlan(true);
    try {
      const plan = await api.createTestPlan(appId, {
        name: planName.trim(),
        description: planDescription.trim() || null,
        task_ids: planTaskIds,
      });
      toast.success(`Test plan "${plan.name}" created`);
      setPlanOpen(false);
      setPlanName('');
      setPlanDescription('');
      setPlanTaskIds([]);
      navigate(`/applications/${appId}/reliability/${plan.id}`);
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not create test plan');
    } finally {
      setSavingPlan(false);
    }
  };

  /* ---------------------------------------------------------- adapter form */

  const [adapterOpen, setAdapterOpen] = useState(false);
  const [adapterName, setAdapterName] = useState('');
  const [adapterTypeSlug, setAdapterTypeSlug] = useState('');
  const [adapterTriggers, setAdapterTriggers] = useState<string[]>([]);
  const [adapterConfigRef, setAdapterConfigRef] = useState('');
  const [savingAdapter, setSavingAdapter] = useState(false);
  const [busyAdapterId, setBusyAdapterId] = useState<string | null>(null);

  const selectedAdapterType = data?.adapterTypes.find((type) => type.slug === adapterTypeSlug);

  const resetAdapterForm = () => {
    setAdapterName('');
    setAdapterTypeSlug('');
    setAdapterTriggers([]);
    setAdapterConfigRef('');
  };

  const submitAdapter = async () => {
    if (!appId) return;
    if (!adapterName.trim() || !adapterTypeSlug) {
      toast.error('Choose an adapter type and give the adapter a name.');
      return;
    }
    setSavingAdapter(true);
    try {
      await api.createAdapter(appId, {
        name: adapterName.trim(),
        adapter_type: adapterTypeSlug,
        enabled_triggers: adapterTriggers,
        configuration_ref: adapterConfigRef.trim() || null,
      });
      toast.success(`Adapter "${adapterName.trim()}" configured`);
      resetAdapterForm();
      setAdapterOpen(false);
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not configure adapter');
    } finally {
      setSavingAdapter(false);
    }
  };

  const runAdapterAction = async (
    adapter: ApplicationAdapter,
    action: 'validate' | 'delete',
  ) => {
    if (!appId) return;
    setBusyAdapterId(adapter.id);
    try {
      if (action === 'validate') {
        const updated = await api.validateAdapter(appId, adapter.id);
        toast.success(`Adapter "${updated.name}" is ${updated.status.toLowerCase()}`);
      } else {
        await api.deleteAdapter(appId, adapter.id);
        toast.info(`Adapter "${adapter.name}" removed`);
      }
      reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Adapter action failed');
    } finally {
      setBusyAdapterId(null);
    }
  };

  /* -------------------------------------------------------- runtime profile */

  const [profileType, setProfileType] = useState<'docker' | 'simulated'>('docker');
  const [profileImage, setProfileImage] = useState('');
  const [profileQueue, setProfileQueue] = useState('');
  const [profileCommand, setProfileCommand] = useState('');
  const [profileConcurrency, setProfileConcurrency] = useState('1');
  const [profileEnv, setProfileEnv] = useState('{}');
  const [savingProfile, setSavingProfile] = useState(false);

  const runtimeProfile = data?.profile.runtime_config ?? null;

  useEffect(() => {
    if (!runtimeProfile) return;
    setProfileType(runtimeProfile.runtime_type ?? 'docker');
    setProfileImage(runtimeProfile.image ?? '');
    setProfileQueue(runtimeProfile.queue ?? '');
    setProfileCommand((runtimeProfile.worker_command ?? []).join(' '));
    setProfileConcurrency(String(runtimeProfile.concurrency ?? 1));
    setProfileEnv(prettyJson(runtimeProfile.env ?? {}) || '{}');
  }, [runtimeProfile]);

  const saveProfile = async () => {
    if (!appId) return;
    if (!profileQueue.trim()) {
      toast.error('A queue name is required for the isolated worker.');
      return;
    }
    const parsedEnv = parseJsonObject(profileEnv);
    if (parsedEnv.error || parsedEnv.value === null) {
      toast.error(`Environment overrides: ${parsedEnv.error ?? 'invalid object'}`);
      return;
    }
    const env: Record<string, string> = {};
    for (const [key, value] of Object.entries(parsedEnv.value)) {
      env[key] = String(value);
    }
    const payload: RuntimeProfile = {
      runtime_type: profileType,
      image: profileImage.trim() || null,
      queue: profileQueue.trim(),
      concurrency: Number(profileConcurrency) || 1,
      worker_command: profileCommand.trim() ? profileCommand.trim().split(/\s+/) : null,
      env,
    };
    setSavingProfile(true);
    try {
      await api.putRuntimeProfile(appId, payload);
      toast.success('Runner profile saved');
      reload();
    } catch (cause) {
      toast.error(
        cause instanceof ApiError ? cause.detail : cause instanceof Error ? cause.message : 'Could not save profile',
      );
    } finally {
      setSavingProfile(false);
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

  const capabilities = data?.capabilities;

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        <PageHeader
          title="Reliability testing"
          description={`Plan an isolated failure test for ${application?.name ?? 'this application'}, approve the matrix, then run and observe it.`}
          eyebrow={
            <span className="text-[11px] text-[#B1BAC4] font-mono">
              planning · approval · runtime · verdict
            </span>
          }
          actions={
            <>
              <Link
                to={`/applications/${appId}/reliability/runs`}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors"
              >
                <Play className="w-3.5 h-3.5" /> Test runs
              </Link>
              <button
                onClick={reload}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
              </button>
              <button
                onClick={() => setPlanOpen(true)}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg shadow-2xs transition-all"
              >
                <Plus className="w-4 h-4" /> New test plan
              </button>
            </>
          }
        />

        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
          {[
            '1 · Configure task contract',
            '2 · Pick supported scenarios',
            '3 · Generate, validate and approve',
            '4 · Start, observe, read verdict',
          ].map((step) => (
            <div
              key={step}
              className="px-3 py-2 rounded-lg border border-[#30363D] bg-[#000000] text-[#C9D1D9] font-medium"
            >
              {step}
            </div>
          ))}
        </div>

        {error && <ErrorState message={error} onRetry={reload} />}

        {capabilities && !capabilities.runner_enabled && (
          <div className="p-4 bg-[#C9D1D9]/25 border border-[#C9D1D9]/60 rounded-xl text-xs text-[#C9D1D9] flex items-start gap-2.5">
            <ServerCog className="w-4 h-4 mt-0.5 shrink-0" />
            <div className="leading-relaxed">
              <p className="font-semibold">The reliability runner is disabled on this backend.</p>
              <p className="mt-0.5">
                Planning and approval still work, but starting a run will be rejected. Set{' '}
                <span className="font-mono">RUNNER_ENABLED</span> on the backend to execute tests.
              </p>
            </div>
          </div>
        )}

        {loading && !data ? (
          <LoadingState label="Loading planning workspace…" />
        ) : (
          <>
            <SectionCard
              title="Registered tasks"
              description="Select a task to configure its contract, scenarios and checkpoints"
              icon={<ListChecks className="w-4 h-4 text-[#C9D1D9]" />}
              actions={
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    value={taskQuery}
                    onChange={(event) => setTaskQuery(event.target.value)}
                    placeholder="Filter tasks…"
                    className="px-2.5 py-1.5 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg w-44"
                  />
                  <Link
                    to={`/applications/${appId}/tasks`}
                    className="text-xs font-medium text-[#C9D1D9] hover:text-[#F0F6FC] flex items-center gap-1"
                  >
                    Observability catalog <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              }
              bodyClassName="p-0"
            >
              {!data || data.tasks.items.length === 0 ? (
                <div className="p-5">
                  <EmptyState
                    icon={<ListChecks className="w-5 h-5" />}
                    title="No registered tasks"
                    description="Tasks are discovered through the VeriQ SDK. Integrate the SDK and start a worker before planning reliability tests."
                  />
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-[#000000] text-[10px] uppercase tracking-wider text-[#B1BAC4]">
                      <tr>
                        <th className="px-5 py-2.5 font-semibold">Task</th>
                        <th className="px-3 py-2.5 font-semibold">Observation</th>
                        <th className="px-3 py-2.5 font-semibold">Test contract</th>
                        <th className="px-3 py-2.5 font-semibold">Last seen</th>
                        <th className="px-3 py-2.5" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#30363D]">
                      {data.tasks.items
                        .filter((task) =>
                          task.task_name.toLowerCase().includes(taskQuery.trim().toLowerCase()),
                        )
                        .map((task) => {
                        const contract = contractByTask.get(task.id);
                        return (
                          <tr key={task.id} className="hover:bg-[#000000] transition-colors">
                            <td className="px-5 py-3">
                              <Link
                                to={`/applications/${appId}/reliability/tasks/${task.id}`}
                                className="font-mono text-[11px] text-[#F0F6FC] hover:text-[#C9D1D9]"
                              >
                                {task.task_name}
                              </Link>
                            </td>
                            <td className="px-3 py-3">
                              <StatusBadge status={task.status} />
                            </td>
                            <td className="px-3 py-3">
                              {contract ? (
                                <div className="flex items-center gap-2">
                                  <Pill tone="sage">v{contract.version}</Pill>
                                  <span className="text-[10px] text-[#B1BAC4]">
                                    {formatRelative(contract.updated_at)}
                                  </span>
                                </div>
                              ) : (
                                <span className="text-[11px] text-[#B1BAC4]">Not configured</span>
                              )}
                            </td>
                            <td className="px-3 py-3 text-[11px] text-[#B1BAC4] whitespace-nowrap">
                              {formatRelative(task.last_seen_at)}
                            </td>
                            <td className="px-3 py-3 text-right">
                              <Link
                                to={`/applications/${appId}/reliability/tasks/${task.id}`}
                                className="inline-flex items-center gap-1 text-[11px] font-medium text-[#C9D1D9] hover:text-[#F0F6FC]"
                              >
                                Configure <ArrowRight className="w-3.5 h-3.5" />
                              </Link>
                            </td>
                          </tr>
                        );
                      })}
                      {data.tasks.items.filter((task) =>
                        task.task_name.toLowerCase().includes(taskQuery.trim().toLowerCase()),
                      ).length === 0 && (
                        <tr>
                          <td colSpan={5} className="px-5 py-4 text-[11px] text-[#B1BAC4]">
                            No task matches “{taskQuery}”.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SectionCard
                title="Adapters"
                description="Configured adapters for this application"
                icon={<Boxes className="w-4 h-4 text-[#C9D1D9]" />}
                actions={
                  <button
                    onClick={() => setAdapterOpen((open) => !open)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
                  >
                    {adapterOpen ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
                    {adapterOpen ? 'Close' : 'Add adapter'}
                  </button>
                }
              >
                {adapterOpen && (
                  <div className="mb-4 p-4 rounded-lg border border-[#30363D] bg-[#000000] space-y-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <label className="block">
                        <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                          Name
                        </span>
                        <input
                          value={adapterName}
                          onChange={(event) => setAdapterName(event.target.value)}
                          className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]"
                          placeholder="checkout-http"
                        />
                      </label>
                      <label className="block">
                        <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                          Adapter type
                        </span>
                        <select
                          value={adapterTypeSlug}
                          onChange={(event) => {
                            setAdapterTypeSlug(event.target.value);
                            setAdapterTriggers([]);
                          }}
                          className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]"
                        >
                          <option value="">Select a supported type…</option>
                          {(data?.adapterTypes ?? []).map((type: AdapterType) => (
                            <option key={type.slug} value={type.slug}>
                              {type.name} ({type.category})
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    {selectedAdapterType && (
                      <>
                        <p className="text-[11px] text-[#B1BAC4] leading-relaxed">
                          {selectedAdapterType.description}
                        </p>
                        <div>
                          <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                            Enabled triggers
                          </span>
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {selectedAdapterType.supported_triggers.length === 0 ? (
                              <span className="text-[11px] text-[#B1BAC4]">
                                This type declares no fault triggers.
                              </span>
                            ) : (
                              selectedAdapterType.supported_triggers.map((trigger) => {
                                const selected = adapterTriggers.includes(trigger);
                                return (
                                  <button
                                    key={trigger}
                                    type="button"
                                    onClick={() =>
                                      setAdapterTriggers((current) =>
                                        selected
                                          ? current.filter((value) => value !== trigger)
                                          : [...current, trigger],
                                      )
                                    }
                                    className={`inline-flex items-center gap-1 px-2 py-1 rounded border text-[10px] font-mono ${
                                      selected
                                        ? 'bg-[#C9D1D9]/15 border-[#C9D1D9]/40 text-[#3e563a]'
                                        : 'bg-[#000000] border-[#30363D] text-[#B1BAC4]'
                                    }`}
                                  >
                                    {selected && <Check className="w-3 h-3" />}
                                    {trigger}
                                  </button>
                                );
                              })
                            )}
                          </div>
                        </div>
                        <label className="block">
                          <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                            Configuration reference (optional, never a credential)
                          </span>
                          <input
                            value={adapterConfigRef}
                            onChange={(event) => setAdapterConfigRef(event.target.value)}
                            className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]"
                            placeholder="secret-ref://team/checkout-http"
                          />
                        </label>
                      </>
                    )}
                    <div className="flex justify-end">
                      <button
                        onClick={submitAdapter}
                        disabled={savingAdapter}
                        className="px-3.5 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg disabled:opacity-60"
                      >
                        {savingAdapter ? 'Saving…' : 'Save adapter'}
                      </button>
                    </div>
                  </div>
                )}

                <details className="mb-3 rounded-lg border border-[#30363D] bg-[#000000] px-3 py-2">
                  <summary className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold cursor-pointer">
                    Supported adapter types ({data?.adapterTypes.length ?? 0})
                  </summary>
                  <div className="mt-2 space-y-1.5">
                    {data?.adapterTypes.map((type) => (
                      <div key={type.slug} className="text-[10px] text-[#B1BAC4] leading-relaxed">
                        <span className="font-mono text-[#C9D1D9]">{type.slug}</span> · {type.category}
                        {' · '}
                        {type.builtin ? 'built-in' : 'custom'}
                        <div>
                          capabilities: {type.capabilities.join(', ') || 'none'}
                        </div>
                        <div>
                          triggers: {type.supported_triggers.join(', ') || 'none'}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>

                {(data?.adapters.length ?? 0) === 0 ? (
                  <EmptyState
                    icon={<Boxes className="w-5 h-5" />}
                    title="No adapters configured"
                    description="Scenarios that need dependency failure injection report NEEDS_CONFIGURATION until a matching adapter is configured and validated."
                  />
                ) : (
                  <div className="space-y-2">
                    {data?.adapters.map((adapter) => (
                      <div
                        key={adapter.id}
                        className="p-3 rounded-lg border border-[#30363D] bg-[#000000] space-y-2"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-xs font-semibold text-[#F0F6FC] truncate">
                              {adapter.name}
                            </div>
                            <div className="text-[10px] text-[#B1BAC4] font-mono">
                              {adapter.adapter_type} · {adapter.category}
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <StatusBadge status={adapter.status} />
                            <button
                              onClick={() => runAdapterAction(adapter, 'validate')}
                              disabled={busyAdapterId === adapter.id}
                              className="px-2 py-1 text-[10px] font-medium rounded border border-[#30363D] bg-[#000000] text-[#C9D1D9] hover:bg-[#161B22] disabled:opacity-50"
                            >
                              Validate
                            </button>
                            <button
                              onClick={() => runAdapterAction(adapter, 'delete')}
                              disabled={busyAdapterId === adapter.id}
                              className="p-1 rounded text-[#F85149] hover:bg-[#F85149]/15 disabled:opacity-50"
                              title="Delete adapter"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {adapter.capabilities.map((capability) => (
                            <Pill key={capability} tone="muted">
                              {capability}
                            </Pill>
                          ))}
                        </div>
                        <div className="text-[10px] text-[#B1BAC4] font-mono">
                          triggers: {adapter.enabled_triggers.length > 0 ? adapter.enabled_triggers.join(', ') : 'none'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>

              <SectionCard
                title="Runner profile"
                description="How the isolated runner launches this application's worker"
                icon={<ServerCog className="w-4 h-4 text-[#C9D1D9]" />}
              >
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Runtime
                    </span>
                    <select
                      value={profileType}
                      onChange={(event) => setProfileType(event.target.value as 'docker' | 'simulated')}
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg"
                    >
                      <option value="docker">docker</option>
                      <option value="simulated">simulated</option>
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Queue
                    </span>
                    <input
                      value={profileQueue}
                      onChange={(event) => setProfileQueue(event.target.value)}
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      placeholder="veriq-tests"
                    />
                  </label>
                  <label className="block sm:col-span-2">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Image
                    </span>
                    <input
                      value={profileImage}
                      onChange={(event) => setProfileImage(event.target.value)}
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      placeholder="registry/app-image:tag"
                    />
                  </label>
                  <label className="block sm:col-span-2">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Worker command (optional, space separated)
                    </span>
                    <input
                      value={profileCommand}
                      onChange={(event) => setProfileCommand(event.target.value)}
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      placeholder="celery -A app.worker worker -Q {queue}"
                    />
                  </label>
                  <label className="block">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Concurrency
                    </span>
                    <input
                      value={profileConcurrency}
                      onChange={(event) => setProfileConcurrency(event.target.value)}
                      className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                      inputMode="numeric"
                    />
                  </label>
                  <label className="block sm:col-span-2">
                    <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                      Non-secret environment overrides (JSON)
                    </span>
                    <textarea
                      value={profileEnv}
                      onChange={(event) => setProfileEnv(event.target.value)}
                      rows={3}
                      className="mt-1 w-full px-3 py-2 text-[11px] bg-[#000000] border border-[#30363D] rounded-lg font-mono"
                    />
                  </label>
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[10px] text-[#B1BAC4]">
                    {runtimeProfile
                      ? `Saved ${formatRelative(application?.updated_at)} · credentials stay server-side`
                      : 'No runner profile saved yet'}
                  </span>
                  <button
                    onClick={saveProfile}
                    disabled={savingProfile}
                    className="px-3.5 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg disabled:opacity-60"
                  >
                    {savingProfile ? 'Saving…' : 'Save profile'}
                  </button>
                </div>
                {capabilities && (
                  <div className="mt-4 pt-3 border-t border-[#30363D] grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] block">
                        Runner
                      </span>
                      <Pill tone={capabilities.runner_enabled ? 'sage' : 'rose'}>
                        {capabilities.runner_enabled ? 'enabled' : 'disabled'}
                      </Pill>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] block">
                        Scenarios
                      </span>
                      <span className="text-xs font-mono text-[#F0F6FC]">
                        {capabilities.supported_scenarios.length} implemented
                      </span>
                    </div>
                    <div className="col-span-2 min-w-0">
                      <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] block">
                        Isolation
                      </span>
                      <span className="text-[11px] text-[#C9D1D9] break-words">{capabilities.isolation}</span>
                    </div>
                  </div>
                )}
              </SectionCard>
            </div>

            <SectionCard
              title="Test plans"
              description="A plan freezes a scenario matrix into an immutable revision for review"
              icon={<FlaskConical className="w-4 h-4 text-[#C9D1D9]" />}
              actions={
                <button
                  onClick={() => setPlanOpen(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
                >
                  <Plus className="w-3.5 h-3.5" /> New plan
                </button>
              }
              bodyClassName="p-0"
            >
              {(data?.plans.length ?? 0) === 0 ? (
                <div className="p-5">
                  <EmptyState
                    icon={<FlaskConical className="w-5 h-5" />}
                    title="No test plans"
                    description="Create a plan, generate its matrix, validate it, submit it for review and approve the current revision before running a test."
                    action={
                      <button
                        onClick={() => setPlanOpen(true)}
                        className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg"
                      >
                        <Plus className="w-3.5 h-3.5" /> New test plan
                      </button>
                    }
                  />
                </div>
              ) : (
                <div className="divide-y divide-[#30363D]">
                  {data?.plans.map((plan) => (
                    <Link
                      key={plan.id}
                      to={`/applications/${appId}/reliability/${plan.id}`}
                      className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 hover:bg-[#000000] transition-colors"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-[#F0F6FC] truncate">{plan.name}</div>
                        <div className="text-[11px] text-[#B1BAC4] mt-0.5 font-mono">
                          {shortId(plan.id, 10)} · revision {plan.current_revision}
                          {plan.approved_revision ? ` · approved r${plan.approved_revision}` : ''}
                          {' · '}
                          {plan.task_ids.length} task{plan.task_ids.length === 1 ? '' : 's'}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-[10px] text-[#B1BAC4] hidden sm:block">
                          {plan.approved_at ? `Approved ${formatDate(plan.approved_at)}` : 'Not approved'}
                        </span>
                        <StatusBadge status={plan.status} />
                        <ArrowRight className="w-4 h-4 text-[#B1BAC4]" />
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </SectionCard>
          </>
        )}
      </div>

      {planOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#F0F6FC]/40 backdrop-blur-xs">
          <div className="w-full max-w-xl bg-[#000000] rounded-xl border border-[#30363D] shadow-xl p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-serif font-bold text-base text-[#F0F6FC]">New test plan</h3>
                <p className="text-xs text-[#B1BAC4] mt-1">
                  Select the registered tasks whose enabled scenarios should be planned together.
                </p>
              </div>
              <button
                onClick={() => setPlanOpen(false)}
                className="p-1.5 text-[#B1BAC4] hover:text-[#F0F6FC] rounded-md"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <label className="block">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Name
                </span>
                <input
                  value={planName}
                  onChange={(event) => setPlanName(event.target.value)}
                  className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]"
                  placeholder="Checkout reliability suite"
                />
              </label>
              <label className="block">
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Description (optional)
                </span>
                <textarea
                  value={planDescription}
                  onChange={(event) => setPlanDescription(event.target.value)}
                  rows={2}
                  className="mt-1 w-full px-3 py-2 text-xs bg-[#000000] border border-[#30363D] rounded-lg"
                />
              </label>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[#B1BAC4] font-semibold">
                  Tasks
                </span>
                <div className="mt-1.5 max-h-48 overflow-y-auto rounded-lg border border-[#30363D] divide-y divide-[#30363D]">
                  {(data?.tasks.items ?? []).map((task) => {
                    const selected = planTaskIds.includes(task.id);
                    return (
                      <button
                        key={task.id}
                        type="button"
                        onClick={() => toggleTask(task.id)}
                        className={`w-full flex items-center gap-2.5 px-3 py-2 text-left text-[11px] font-mono ${
                          selected ? 'bg-[#C9D1D9]/10 text-[#F0F6FC]' : 'text-[#C9D1D9] hover:bg-[#000000]'
                        }`}
                      >
                        <span
                          className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                            selected ? 'bg-[#C9D1D9] border-[#C9D1D9] text-white' : 'border-[#C9D1D9] bg-[#000000]'
                          }`}
                        >
                          {selected && <Check className="w-3 h-3" />}
                        </span>
                        <span className="truncate">{task.task_name}</span>
                      </button>
                    );
                  })}
                  {(data?.tasks.items.length ?? 0) === 0 && (
                    <p className="px-3 py-3 text-[11px] text-[#B1BAC4]">No registered tasks available.</p>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-5 flex items-center justify-end gap-2.5">
              <button
                onClick={() => setPlanOpen(false)}
                className="px-4 py-2 text-xs font-medium text-[#B1BAC4] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
              >
                Cancel
              </button>
              <button
                onClick={createPlan}
                disabled={savingPlan}
                className="px-4 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg disabled:opacity-60"
              >
                {savingPlan ? 'Creating…' : 'Create plan'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
};

export default Reliability;
