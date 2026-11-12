import React, { useState } from 'react';
import { Layout } from '../components/Layout';
import { INITIAL_EXPERIMENTS, INITIAL_RUNS, INITIAL_ACTIVITIES, INITIAL_APPLICATIONS } from '../mockData';
import { VerdictBadge } from '../components/VerdictBadge';
import { NewExperimentModal } from '../components/NewExperimentModal';
import { Link, useNavigate } from 'react-router-dom';
import {
  FlaskConical,
  CheckCircle2,
  XCircle,
  Play,
  ArrowRight,
  Sparkles,
  Server,
  Layers,
  Clock,
  ChevronRight
} from 'lucide-react';
import { toast } from 'react-toastify';
import type { Experiment } from '../types';

export const Home: React.FC = () => {
  const navigate = useNavigate();
  const [experiments, setExperiments] = useState(INITIAL_EXPERIMENTS);
  const [runs] = useState(INITIAL_RUNS);
  const [activities] = useState(INITIAL_ACTIVITIES);
  const [applications, setApplications] = useState(INITIAL_APPLICATIONS);
  const [isNewExperimentModalOpen, setIsNewExperimentModalOpen] = useState(false);

  // Metrics
  const totalExperiments = experiments.length;
  const totalRuns = runs.length;
  const passedRuns = runs.filter(r => r.verdict === 'passed').length;
  const failedRuns = runs.filter(r => r.verdict === 'failed').length;

  const handleSaveExperiment = (newExp: Partial<Experiment>, isDraft: boolean) => {
    const created: Experiment = {
      id: `exp-${Date.now()}`,
      name: newExp.name || 'Untitled Experiment',
      applicationId: newExp.applicationId || applications[0].id,
      applicationName: newExp.applicationName || applications[0].name,
      task: newExp.task || 'task.process',
      status: isDraft ? 'draft' : 'active',
      failureScenario: newExp.failureScenario || 'Crash after commit',
      checkpoint: newExp.checkpoint || 'DB_TRANSACTION_COMMITTED',
      logicalOperationIdTemplate: newExp.logicalOperationIdTemplate || 'op_{uuid}',
      timeoutSeconds: newExp.timeoutSeconds || 15,
      environment: newExp.environment || 'staging',
      description: newExp.description || '',
      totalRuns: 0,
      createdAt: new Date().toISOString().split('T')[0]
    };

    setExperiments([created, ...experiments]);
    toast.success(isDraft ? 'Experiment draft saved' : 'New reliability experiment created');
  };

  return (
    <Layout onOpenNewExperiment={() => setIsNewExperimentModalOpen(true)}>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-8">
        {/* Top Header & Context Banner */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[#E5E1D7]">
          <div>
            <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#343832] tracking-tight">
              Reliability Overview
            </h1>
            <p className="text-xs md:text-sm text-[#777A72] mt-1">
              Verify idempotent behavior, recovery checkpoints, and business invariants under controlled failure.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsNewExperimentModalOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all active:scale-[0.98]"
            >
              <FlaskConical className="w-4 h-4" />
              New Experiment
            </button>
          </div>
        </div>

        {/* Metric Cards Row */}
        <section aria-labelledby="metrics-summary">
          <h2 id="metrics-summary" className="sr-only">Reliability Metrics Summary</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-5 bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-2xs transition-all hover:border-[#D8C8AE]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-[#777A72]">
                  Total Experiments
                </span>
                <FlaskConical className="w-4 h-4 text-[#8297AC]" />
              </div>
              <div className="mt-3 flex items-baseline gap-2">
                <span className="font-serif font-bold text-2xl md:text-3xl text-[#343832]">
                  {totalExperiments}
                </span>
                <span className="text-[11px] text-[#777A72]">configured definitions</span>
              </div>
            </div>

            <div className="p-5 bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-2xs transition-all hover:border-[#D8C8AE]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-[#777A72]">
                  Total Test Runs
                </span>
                <Clock className="w-4 h-4 text-[#8297AC]" />
              </div>
              <div className="mt-3 flex items-baseline gap-2">
                <span className="font-serif font-bold text-2xl md:text-3xl text-[#343832]">
                  {totalRuns}
                </span>
                <span className="text-[11px] text-[#777A72]">sandbox executions</span>
              </div>
            </div>

            <div className="p-5 bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-2xs transition-all hover:border-[#D8C8AE]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-[#777A72]">
                  Passed Runs
                </span>
                <CheckCircle2 className="w-4 h-4 text-[#879B83]" />
              </div>
              <div className="mt-3 flex items-baseline gap-2">
                <span className="font-serif font-bold text-2xl md:text-3xl text-[#3e563a]">
                  {passedRuns}
                </span>
                <span className="text-[11px] text-[#879B83] font-medium">Invariants held</span>
              </div>
            </div>

            <div className="p-5 bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-2xs transition-all hover:border-[#D8C8AE]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-[#777A72]">
                  Failed Invariants
                </span>
                <XCircle className="w-4 h-4 text-[#A46F70]" />
              </div>
              <div className="mt-3 flex items-baseline gap-2">
                <span className="font-serif font-bold text-2xl md:text-3xl text-[#733e3f]">
                  {failedRuns}
                </span>
                <span className="text-[11px] text-[#A46F70] font-medium">Anomalies caught</span>
              </div>
            </div>
          </div>
        </section>

        {/* Middle Two-Column Grid: Recent Experiments + Compact Workspace Summary */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Recent Experiments (2 Cols) */}
          <section className="lg:col-span-2 bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-5 shadow-2xs flex flex-col">
            <div className="flex items-center justify-between pb-3.5 border-b border-[#E5E1D7]">
              <div>
                <h2 className="font-serif font-bold text-base text-[#343832]">Active Experiments</h2>
                <p className="text-xs text-[#777A72]">Recent test targets across background workers</p>
              </div>
              <Link
                to="/experiments"
                className="text-xs font-medium text-[#5f745b] hover:text-[#343832] flex items-center gap-1 transition-colors"
              >
                View all experiments <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>

            <div className="divide-y divide-[#E5E1D7] mt-1 flex-1">
              {experiments.slice(0, 4).map((exp) => (
                <div
                  key={exp.id}
                  onClick={() => navigate(`/experiments/${exp.id}`)}
                  className="py-3.5 px-2 hover:bg-[#FAF8F3] -mx-2 rounded-lg cursor-pointer transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-sm text-[#343832] truncate">{exp.name}</h3>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#EFEEE7] text-[#61655b]">
                        {exp.applicationName}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-[#777A72] mt-1">
                      <span className="font-mono text-[11px] truncate max-w-xs">{exp.task}</span>
                      <span>&bull;</span>
                      <span className="text-[11px] text-[#52564e]">{exp.failureScenario}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0 self-start sm:self-auto">
                    {exp.lastRun ? (
                      <VerdictBadge verdict={exp.lastRun.verdict} size="sm" />
                    ) : (
                      <span className="text-xs text-[#777A72] italic">No runs yet</span>
                    )}
                    <ChevronRight className="w-4 h-4 text-[#777A72]" />
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Compact Workspace Summary & Worker Pool */}
          <section className="bg-[#FAF8F3] rounded-xl border border-[#E5E1D7] p-5 shadow-2xs flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 pb-3 border-b border-[#E5E1D7]">
                <Server className="w-4 h-4 text-[#8297AC]" />
                <h2 className="font-serif font-bold text-base text-[#343832]">Worker Pool Context</h2>
              </div>

              <div className="mt-4 space-y-3.5 text-xs text-[#52564e]">
                <div className="p-3 bg-white rounded-lg border border-[#E5E1D7]">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-[#343832]">Registered Applications</span>
                    <span className="font-mono font-semibold text-sm">{applications.length}</span>
                  </div>
                  <p className="text-[11px] text-[#777A72] mt-1">
                    Celery, BullMQ, Sidekiq instrumented targets
                  </p>
                </div>

                <div className="p-3 bg-white rounded-lg border border-[#E5E1D7]">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-[#343832]">Supported Fault Model</span>
                    <span className="text-xs font-mono text-[#879B83] font-semibold">Crash-after-commit</span>
                  </div>
                  <p className="text-[11px] text-[#777A72] mt-1">
                    Forces worker death post-checkpoint, testing broker re-delivery guarantees.
                  </p>
                </div>

                <div className="p-3 bg-white rounded-lg border border-[#E5E1D7]">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-[#343832]">Audit Verifiers</span>
                    <span className="text-xs text-[#879B83] font-medium">Idempotency & State</span>
                  </div>
                  <p className="text-[11px] text-[#777A72] mt-1">
                    Checks database mutation counts & external provider dispatch receipts.
                  </p>
                </div>
              </div>
            </div>

            <div className="pt-4 mt-4 border-t border-[#E5E1D7]">
              <Link
                to="/applications"
                className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] hover:bg-[#EFEEE7] rounded-lg transition-colors"
              >
                <Layers className="w-3.5 h-3.5 text-[#777A72]" />
                Manage Application Targets
              </Link>
            </div>
          </section>
        </div>

        {/* Chronological Activity Feed */}
        <section className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-6 shadow-2xs">
          <div className="flex items-center justify-between pb-4 border-b border-[#E5E1D7]">
            <div>
              <h2 className="font-serif font-bold text-base text-[#343832]">Reliability Activity Log</h2>
              <p className="text-xs text-[#777A72]">Chronological events across experiments and mock runs</p>
            </div>
            <Link
              to="/history"
              className="text-xs font-medium text-[#5f745b] hover:text-[#343832] flex items-center gap-1"
            >
              Full execution history <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="mt-4 space-y-4">
            {activities.map((act) => (
              <div key={act.id} className="flex items-start gap-3.5 text-xs">
                <div className="w-2 h-2 rounded-full bg-[#879B83] mt-1.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-sm text-[#343832]">{act.title}</span>
                    {act.badge && act.badge.verdict && (
                      <VerdictBadge verdict={act.badge.verdict} size="sm" />
                    )}
                    <span className="text-[11px] text-[#777A72] ml-auto">{act.timestamp}</span>
                  </div>
                  <p className="text-[#61655b] mt-0.5 leading-relaxed">{act.description}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <NewExperimentModal
        isOpen={isNewExperimentModalOpen}
        onClose={() => setIsNewExperimentModalOpen(false)}
        applications={applications}
        onSave={handleSaveExperiment}
      />
    </Layout>
  );
};

export default Home;