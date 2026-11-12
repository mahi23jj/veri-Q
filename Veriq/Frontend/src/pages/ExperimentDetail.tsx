import React, { useState, useEffect } from 'react';
import { Layout } from '../components/Layout';
import { useParams, useSearchParams, Link } from 'react-router-dom';
import { INITIAL_EXPERIMENTS, INITIAL_RUNS } from '../mockData';
import type { ExperimentRun, TimelineEvent, InvariantResult } from '../types';
import { VerdictBadge } from '../components/VerdictBadge';
import {
  FlaskConical,
  Play,
  RotateCcw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Clock,
  Layers,
  Server,
  Terminal,
  ShieldAlert,
  ArrowLeft,
  Sparkles
} from 'lucide-react';
import { toast } from 'react-toastify';

export const ExperimentDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const queryRunId = searchParams.get('runId');

  const experiment = INITIAL_EXPERIMENTS.find(e => e.id === id) || INITIAL_EXPERIMENTS[0];

  // Runs for this experiment
  const experimentRuns = INITIAL_RUNS.filter(r => r.experimentId === experiment.id);
  const initialRun = queryRunId
    ? experimentRuns.find(r => r.id === queryRunId) || experimentRuns[0] || INITIAL_RUNS[0]
    : experimentRuns[0] || INITIAL_RUNS[0];

  const [activeRun, setActiveRun] = useState<ExperimentRun>(initialRun);
  const [expandedEvents, setExpandedEvents] = useState<Record<string, boolean>>({
    'ev-4': true,
    'ev-5': true,
    'ev-p3': true,
    'ev-p4': true
  });
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationProgressStep, setSimulationProgressStep] = useState(0);

  // Sync if queryRunId changes
  useEffect(() => {
    if (queryRunId) {
      const match = experimentRuns.find(r => r.id === queryRunId);
      if (match) setActiveRun(match);
    }
  }, [queryRunId, experimentRuns]);

  const toggleEvent = (eventId: string) => {
    setExpandedEvents(prev => ({ ...prev, [eventId]: !prev[eventId] }));
  };

  // Simulated Lifecycle Execution (Clear local-only mock interaction)
  const handleStartExperiment = () => {
    if (isSimulating) return;
    setIsSimulating(true);
    setSimulationProgressStep(1);

    toast.info('Starting simulated test harness execution...');

    const timer1 = setTimeout(() => {
      setSimulationProgressStep(2); // Injected checkpoint & SIGKILL
    }, 900);

    const timer2 = setTimeout(() => {
      setSimulationProgressStep(3); // Broker redelivery & verifier
    }, 1900);

    const timer3 = setTimeout(() => {
      setIsSimulating(false);
      setSimulationProgressStep(0);

      // Create a simulated new run result in memory
      const simulatedNewRun: ExperimentRun = {
        id: `run-${Math.floor(1000 + Math.random() * 9000)}`,
        experimentId: experiment.id,
        experimentName: experiment.name,
        applicationId: experiment.applicationId,
        applicationName: experiment.applicationName,
        runNumber: activeRun.runNumber + 1,
        startTime: new Date().toLocaleTimeString(),
        duration: '1.24s',
        status: 'completed',
        verdict: 'passed',
        workerNode: 'worker-inv-stg-04',
        attemptNumber: 2,
        maxAttempts: 3,
        logicalOperationId: `tx_alloc_${Math.random().toString(36).substring(2, 8)}`,
        events: [
          {
            id: `sim-ev-1`,
            timestamp: '00:00.010',
            type: 'setup',
            source: 'orchestrator',
            title: 'Mock sandbox harness initialized',
            description: 'Created ephemeral Redis namespace and attached telemetry hook.',
            outcome: 'ok'
          },
          {
            id: `sim-ev-2`,
            timestamp: '00:00.120',
            type: 'checkpoint',
            source: 'worker-node-1',
            title: `Checkpoint reached: ${experiment.checkpoint}`,
            description: 'Operation state committed to database ledger prior to queue acknowledgment.',
            outcome: 'ok'
          },
          {
            id: `sim-ev-3`,
            timestamp: '00:00.125',
            type: 'failure_injection',
            source: 'orchestrator',
            title: 'Simulated fault injected: Worker crashed (SIGKILL)',
            description: 'Process terminated cleanly before task ACK packet left network buffer.',
            outcome: 'injected_fault'
          },
          {
            id: `sim-ev-4`,
            timestamp: '00:00.890',
            type: 'redelivery',
            source: 'queue-broker',
            title: 'Task redelivered to retry worker',
            description: 'Worker 2 detected transaction ID in deduplication store and skipped duplicate debit.',
            outcome: 'ok'
          },
          {
            id: `sim-ev-5`,
            timestamp: '00:01.210',
            type: 'verification',
            source: 'verifier',
            title: 'Audit verified: Invariant held',
            description: 'Stock deductions = 1, exactly matching expected business requirement.',
            outcome: 'ok'
          }
        ],
        invariants: [
          {
            id: 'sim-inv-1',
            name: 'State Mutation Idempotency',
            description: 'Business ledger must strictly mutate once despite worker crash and redelivery.',
            expected: 'Single database write recorded',
            actual: 'Single database write recorded',
            passed: true,
            explanation: 'Deduplication lock guarded against the second delivery execution.'
          }
        ]
      };

      setActiveRun(simulatedNewRun);
      toast.success('Simulated execution completed: Invariants verified!');
    }, 2800);

    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
    };
  };

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        {/* Back Link & Header */}
        <div>
          <Link
            to="/experiments"
            className="inline-flex items-center gap-1.5 text-xs text-[#777A72] hover:text-[#343832] transition-colors mb-3"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Back to Experiments list
          </Link>

          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-[#E5E1D7]">
            <div>
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#343832] tracking-tight">
                  {experiment.name}
                </h1>
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-[#EFEEE7] text-[#52564e]">
                  {experiment.applicationName}
                </span>
              </div>
              <p className="text-xs md:text-sm text-[#777A72] mt-1 max-w-3xl leading-relaxed">
                {experiment.description}
              </p>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2.5 shrink-0">
              <button
                onClick={handleStartExperiment}
                disabled={isSimulating}
                className="inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] disabled:opacity-60 rounded-lg shadow-2xs transition-all active:scale-[0.98]"
              >
                <Play className="w-4 h-4 fill-white" />
                {isSimulating ? 'Simulating Fault...' : 'Start Experiment (Simulated)'}
              </button>
            </div>
          </div>
        </div>

        {/* Simulation Banner Notice (Clearly labeled as local simulated lifecycle) */}
        {isSimulating && (
          <div className="p-4 bg-[#879B83]/15 border border-[#879B83]/30 rounded-xl flex items-center justify-between animate-pulse">
            <div className="flex items-center gap-3">
              <Sparkles className="w-5 h-5 text-[#3e563a]" />
              <div className="text-xs text-[#343832]">
                <span className="font-semibold block">Simulated Execution In-Flight</span>
                <span className="text-[#61655b]">
                  {simulationProgressStep === 1 && 'Step 1/3: Enqueueing task and attaching fault probe...'}
                  {simulationProgressStep === 2 && 'Step 2/3: Reaching checkpoint & simulating SIGKILL crash...'}
                  {simulationProgressStep === 3 && 'Step 3/3: Redelivering task & verifying business invariants...'}
                </span>
              </div>
            </div>
            <div className="font-mono text-xs text-[#3e563a] font-medium">Mock Harness Sandbox</div>
          </div>
        )}

        {/* Top Summary Bar & Run Selector */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-stretch">
          {/* Config Summary Card */}
          <div className="lg:col-span-8 bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-5 shadow-2xs space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-[#E5E1D7]">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#777A72]">
                Fault Scenario Configuration
              </span>
              <span className="text-[11px] font-mono text-[#8297AC]">Timeout: {experiment.timeoutSeconds}s</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
              <div className="p-2.5 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7]">
                <span className="text-[10px] text-[#777A72] uppercase font-semibold block">Failure Scenario</span>
                <span className="font-medium text-[#343832] mt-0.5 block">{experiment.failureScenario}</span>
              </div>

              <div className="p-2.5 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7]">
                <span className="text-[10px] text-[#777A72] uppercase font-semibold block">Checkpoint Hook</span>
                <span className="font-mono text-[11px] text-[#343832] mt-0.5 block">{experiment.checkpoint}</span>
              </div>

              <div className="p-2.5 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7]">
                <span className="text-[10px] text-[#777A72] uppercase font-semibold block">Idempotency Template</span>
                <span className="font-mono text-[11px] text-[#343832] mt-0.5 block">{experiment.logicalOperationIdTemplate}</span>
              </div>
            </div>

            <div className="text-[11px] text-[#777A72] font-mono pt-1">
              Task Hook: <span className="text-[#343832]">{experiment.task}</span>
            </div>
          </div>

          {/* Selectable Run History for this experiment */}
          <div className="lg:col-span-4 bg-[#FAF8F3] rounded-xl border border-[#E5E1D7] p-4 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-2 border-b border-[#E5E1D7]">
                <span className="text-xs font-semibold uppercase tracking-wider text-[#777A72]">
                  Run History ({experimentRuns.length})
                </span>
                <span className="text-[10px] text-[#777A72]">Select to inspect</span>
              </div>

              <div className="space-y-1.5 mt-2.5 max-h-36 overflow-y-auto pr-1">
                {experimentRuns.map(run => {
                  const isCurrent = activeRun.id === run.id;
                  return (
                    <button
                      key={run.id}
                      onClick={() => setActiveRun(run)}
                      className={`w-full text-left p-2 rounded-lg text-xs flex items-center justify-between transition-colors ${
                        isCurrent
                          ? 'bg-[#879B83]/20 border border-[#879B83]/40 font-semibold'
                          : 'bg-white border border-[#E5E1D7] hover:bg-[#EFEEE7]'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-medium text-[#343832]">Run #{run.runNumber}</span>
                        <span className="text-[10px] text-[#777A72] font-mono">{run.duration}</span>
                      </div>
                      <VerdictBadge verdict={run.verdict} size="sm" />
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="pt-2 text-[10px] text-[#777A72] text-center border-t border-[#E5E1D7]/70">
              Mock worker telemetry trace
            </div>
          </div>
        </div>

        {/* Active Run Overview Card */}
        <section className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-5 shadow-2xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[#E5E1D7]">
            <div className="flex items-center gap-3">
              <span className="font-serif font-bold text-lg text-[#343832]">
                Run #{activeRun.runNumber} ({activeRun.id})
              </span>
              <VerdictBadge verdict={activeRun.verdict} size="md" />
            </div>

            <div className="flex flex-wrap items-center gap-3 text-xs text-[#777A72] font-mono">
              <span>Started: {activeRun.startTime}</span>
              <span>&bull;</span>
              <span>Duration: {activeRun.duration}</span>
              <span>&bull;</span>
              <span>Attempt: {activeRun.attemptNumber}/{activeRun.maxAttempts}</span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 text-xs">
            <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7]">
              <span className="text-[10px] uppercase font-semibold text-[#777A72] block">Assigned Worker Node</span>
              <span className="font-mono text-sm text-[#343832] mt-0.5 block">{activeRun.workerNode}</span>
            </div>

            <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7]">
              <span className="text-[10px] uppercase font-semibold text-[#777A72] block">Logical Operation ID</span>
              <span className="font-mono text-sm text-[#343832] mt-0.5 block">{activeRun.logicalOperationId}</span>
            </div>
          </div>
        </section>

        {/* Prominent Invariant Verification Results */}
        <section className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-6 shadow-2xs">
          <div className="flex items-center justify-between pb-3 border-b border-[#E5E1D7]">
            <div>
              <h2 className="font-serif font-bold text-lg text-[#343832]">
                Business Invariant Verification
              </h2>
              <p className="text-xs text-[#777A72] mt-0.5">
                Evaluated against the target datastore and third-party mocks after failure injection and redelivery.
              </p>
            </div>
            <VerdictBadge verdict={activeRun.verdict} size="md" />
          </div>

          <div className="mt-4 space-y-4">
            {activeRun.invariants.length === 0 ? (
              <div className="p-6 text-center text-xs text-[#777A72] italic">
                No invariants evaluated for this run.
              </div>
            ) : (
              activeRun.invariants.map(inv => (
                <div
                  key={inv.id}
                  className={`p-4 rounded-xl border transition-all ${
                    inv.passed
                      ? 'bg-[#879B83]/10 border-[#879B83]/30'
                      : 'bg-[#A46F70]/10 border-[#A46F70]/30'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2.5">
                      {inv.passed ? (
                        <CheckCircle2 className="w-5 h-5 text-[#3e563a] shrink-0 mt-0.5" />
                      ) : (
                        <XCircle className="w-5 h-5 text-[#733e3f] shrink-0 mt-0.5" />
                      )}
                      <div>
                        <h3 className="font-serif font-bold text-sm text-[#343832]">{inv.name}</h3>
                        <p className="text-xs text-[#52564e] mt-0.5">{inv.description}</p>
                      </div>
                    </div>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-mono font-semibold uppercase ${
                        inv.passed ? 'bg-[#879B83]/20 text-[#3e563a]' : 'bg-[#A46F70]/20 text-[#733e3f]'
                      }`}
                    >
                      {inv.passed ? 'Passed' : 'Violation'}
                    </span>
                  </div>

                  <div className="mt-3.5 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs bg-white/70 p-3 rounded-lg border border-[#E5E1D7]/70">
                    <div>
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-[#777A72] block">
                        Expected Invariant
                      </span>
                      <span className="font-mono text-xs text-[#343832] mt-0.5 block">{inv.expected}</span>
                    </div>

                    <div>
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-[#777A72] block">
                        Actual Observed Outcome
                      </span>
                      <span className={`font-mono text-xs mt-0.5 block ${inv.passed ? 'text-[#3e563a]' : 'text-[#733e3f]'}`}>
                        {inv.actual}
                      </span>
                    </div>
                  </div>

                  {/* Plain Language Explanation */}
                  <div className="mt-3 text-xs text-[#464a42] leading-relaxed flex items-start gap-2">
                    <span className="font-semibold shrink-0 text-[#343832]">Analysis:</span>
                    <span>{inv.explanation}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        {/* Chronological Expandable Execution Timeline */}
        <section className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-6 shadow-2xs">
          <div className="flex items-center justify-between pb-4 border-b border-[#E5E1D7]">
            <div>
              <h2 className="font-serif font-bold text-lg text-[#343832]">Execution Timeline</h2>
              <p className="text-xs text-[#777A72] mt-0.5">
                Microsecond trace covering task submission, checkpoint, fault injection, and retry redelivery.
              </p>
            </div>
            <button
              onClick={() => {
                const allExpanded = Object.keys(expandedEvents).length === activeRun.events.length;
                if (allExpanded) {
                  setExpandedEvents({});
                } else {
                  const all: Record<string, boolean> = {};
                  activeRun.events.forEach(e => (all[e.id] = true));
                  setExpandedEvents(all);
                }
              }}
              className="text-xs text-[#5f745b] hover:text-[#343832] font-medium"
            >
              Toggle all details
            </button>
          </div>

          <div className="mt-6 relative pl-6 border-l-2 border-[#E5E1D7] space-y-6">
            {activeRun.events.map((ev, idx) => {
              const isExpanded = !!expandedEvents[ev.id];
              return (
                <div key={ev.id} className="relative group">
                  {/* Timeline Dot */}
                  <div
                    className={`absolute -left-[31px] top-1.5 w-4 h-4 rounded-full border-2 border-white flex items-center justify-center ${
                      ev.type === 'failure_injection'
                        ? 'bg-[#A46F70]'
                        : ev.type === 'checkpoint'
                        ? 'bg-[#8297AC]'
                        : ev.outcome === 'warning'
                        ? 'bg-[#D8C8AE]'
                        : 'bg-[#879B83]'
                    }`}
                  />

                  <div className="bg-[#FAF8F3] border border-[#E5E1D7] rounded-xl p-4 transition-all hover:border-[#D8C8AE]">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-[#777A72]">{ev.timestamp}</span>
                        <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-white text-[#52564e] border border-[#E5E1D7]">
                          {ev.source}
                        </span>
                        <span className="font-semibold text-sm text-[#343832]">{ev.title}</span>
                      </div>

                      <div className="flex items-center gap-2">
                        {ev.type === 'failure_injection' && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-[#A46F70]/20 text-[#733e3f] font-mono font-bold uppercase">
                            Fault Injected
                          </span>
                        )}
                        {ev.payload && (
                          <button
                            onClick={() => toggleEvent(ev.id)}
                            className="text-xs text-[#5f745b] hover:text-[#343832] flex items-center gap-1 font-medium"
                          >
                            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                            {isExpanded ? 'Hide payload' : 'Inspect payload'}
                          </button>
                        )}
                      </div>
                    </div>

                    <p className="text-xs text-[#61655b] mt-1.5 leading-relaxed">{ev.description}</p>

                    {/* Expandable Payload */}
                    {isExpanded && ev.payload && (
                      <div className="mt-3 pt-3 border-t border-[#E5E1D7]">
                        <span className="text-[10px] uppercase font-semibold text-[#777A72] block mb-1">
                          Diagnostic Payload
                        </span>
                        <pre className="p-2.5 bg-[#343832] text-[#F7F5EF] rounded-lg text-[11px] font-mono overflow-x-auto">
                          {JSON.stringify(ev.payload, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </Layout>
  );
};

export default ExperimentDetail;