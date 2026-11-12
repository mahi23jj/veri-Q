import React, { useState, useMemo } from 'react';
import { Layout } from '../components/Layout';
import { INITIAL_EXPERIMENTS, INITIAL_APPLICATIONS } from '../mockData';
import type { Experiment, ExperimentStatus } from '../types';
import { VerdictBadge } from '../components/VerdictBadge';
import { NewExperimentModal } from '../components/NewExperimentModal';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  FlaskConical,
  Search,
  Filter,
  Plus,
  Play,
  Edit2,
  Trash2,
  ExternalLink,
  ChevronRight,
  Layers,
  Clock
} from 'lucide-react';
import { toast } from 'react-toastify';

export const Experiments: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const appFilter = searchParams.get('app');
  const actionParam = searchParams.get('action');

  const [experiments, setExperiments] = useState<Experiment[]>(INITIAL_EXPERIMENTS);
  const [applications] = useState(INITIAL_APPLICATIONS);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | ExperimentStatus>('all');
  const [isModalOpen, setIsModalOpen] = useState(actionParam === 'create');
  const [editingDraft, setEditingDraft] = useState<Experiment | null>(null);
  const [deletingExperiment, setDeletingExperiment] = useState<Experiment | null>(null);

  // Filtered experiments
  const filteredExperiments = useMemo(() => {
    return experiments.filter(exp => {
      if (appFilter && exp.applicationId !== appFilter) return false;
      if (statusFilter !== 'all' && exp.status !== statusFilter) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = exp.name.toLowerCase().includes(q);
        const matchesTask = exp.task.toLowerCase().includes(q);
        const matchesApp = exp.applicationName.toLowerCase().includes(q);
        if (!matchesName && !matchesTask && !matchesApp) return false;
      }
      return true;
    });
  }, [experiments, appFilter, statusFilter, searchQuery]);

  const handleSave = (expData: Partial<Experiment>, isDraft: boolean) => {
    if (editingDraft) {
      const updated = experiments.map(e =>
        e.id === editingDraft.id
          ? {
              ...e,
              ...expData,
              status: isDraft ? ('draft' as const) : ('active' as const)
            }
          : e
      );
      setExperiments(updated);
      toast.success(isDraft ? 'Draft updated' : 'Experiment activated');
      setEditingDraft(null);
    } else {
      const newExp: Experiment = {
        id: `exp-${Date.now()}`,
        name: expData.name || 'Untitled Experiment',
        applicationId: expData.applicationId || applications[0].id,
        applicationName: expData.applicationName || applications[0].name,
        task: expData.task || 'unspecified_task',
        status: isDraft ? 'draft' : 'active',
        failureScenario: expData.failureScenario || 'Crash after commit',
        checkpoint: expData.checkpoint || 'DB_TRANSACTION_COMMITTED',
        logicalOperationIdTemplate: expData.logicalOperationIdTemplate || 'op_{uuid}',
        timeoutSeconds: expData.timeoutSeconds || 15,
        environment: expData.environment || 'staging',
        description: expData.description || '',
        totalRuns: 0,
        createdAt: new Date().toISOString().split('T')[0]
      };
      setExperiments([newExp, ...experiments]);
      toast.success(isDraft ? 'Experiment draft saved' : 'New reliability experiment configured');
    }
  };

  const confirmDelete = () => {
    if (!deletingExperiment) return;
    setExperiments(experiments.filter(e => e.id !== deletingExperiment.id));
    toast.info(`Experiment "${deletingExperiment.name}" removed`);
    setDeletingExperiment(null);
  };

  return (
    <Layout onOpenNewExperiment={() => { setEditingDraft(null); setIsModalOpen(true); }}>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#E5E1D7]">
          <div>
            <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#343832] tracking-tight">
              Experiments
            </h1>
            <p className="text-xs md:text-sm text-[#777A72] mt-1">
              Controlled failure definitions targeting background job checkpoints and boundary conditions.
            </p>
          </div>
          <button
            onClick={() => {
              setEditingDraft(null);
              setIsModalOpen(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all active:scale-[0.98]"
          >
            <Plus className="w-4 h-4" />
            New Experiment
          </button>
        </div>

        {/* Filter & Search Bar */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-[#FDFCFA] p-3 rounded-xl border border-[#E5E1D7]">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-[#777A72] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by experiment name, task, or application..."
              className="w-full pl-9 pr-3.5 py-1.5 text-xs bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-1 focus:ring-[#879B83]"
            />
          </div>

          <div className="flex items-center gap-2 overflow-x-auto">
            <span className="text-[11px] font-semibold uppercase text-[#777A72] mr-1 hidden sm:inline">
              Status:
            </span>
            {(['all', 'active', 'draft', 'archived'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setStatusFilter(tab)}
                className={`px-3 py-1 text-xs rounded-lg capitalize transition-colors font-medium ${
                  statusFilter === tab
                    ? 'bg-[#879B83]/15 text-[#343832] font-semibold border border-[#879B83]/30'
                    : 'text-[#777A72] hover:bg-[#EFEEE7] hover:text-[#343832]'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>

        {/* Experiments Table */}
        <div className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-2xs overflow-hidden">
          {filteredExperiments.length === 0 ? (
            <div className="p-12 text-center">
              <FlaskConical className="w-8 h-8 text-[#8297AC] mx-auto mb-3 opacity-60" />
              <h3 className="font-serif font-bold text-base text-[#343832]">No experiments match</h3>
              <p className="text-xs text-[#777A72] mt-1 max-w-sm mx-auto">
                Try modifying your search query or status filter to see experiment configurations.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-[#FAF8F3] border-b border-[#E5E1D7] text-[#777A72] uppercase font-semibold text-[10px] tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Experiment Name</th>
                    <th className="py-3 px-4">Application & Task</th>
                    <th className="py-3 px-4">Scenario Hook</th>
                    <th className="py-3 px-4">Last Run Verdict</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E5E1D7]">
                  {filteredExperiments.map(exp => (
                    <tr
                      key={exp.id}
                      className="hover:bg-[#FAF8F3]/80 transition-colors group cursor-pointer"
                      onClick={() => navigate(`/experiments/${exp.id}`)}
                    >
                      <td className="py-3.5 px-4">
                        <div className="font-semibold text-[#343832] text-sm group-hover:text-[#5f745b] transition-colors">
                          {exp.name}
                        </div>
                        <div className="text-[11px] text-[#777A72] mt-0.5 line-clamp-1">
                          {exp.description}
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="font-medium text-[#343832]">{exp.applicationName}</div>
                        <div className="font-mono text-[10px] text-[#777A72] mt-0.5 max-w-xs truncate">
                          {exp.task}
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="text-[#343832] font-medium">{exp.failureScenario}</div>
                        <div className="font-mono text-[10px] text-[#8297AC] mt-0.5">
                          @{exp.checkpoint}
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        {exp.lastRun ? (
                          <div>
                            <VerdictBadge verdict={exp.lastRun.verdict} size="sm" />
                            <div className="text-[10px] text-[#777A72] mt-1 font-mono">
                              {exp.lastRun.date}
                            </div>
                          </div>
                        ) : (
                          <span className="text-xs text-[#777A72] italic">Not executed</span>
                        )}
                      </td>

                      <td className="py-3.5 px-4">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-full text-[10px] uppercase font-mono font-medium ${
                            exp.status === 'active'
                              ? 'bg-[#879B83]/15 text-[#3e563a]'
                              : exp.status === 'draft'
                              ? 'bg-[#D8C8AE]/30 text-[#675438]'
                              : 'bg-stone-100 text-stone-600'
                          }`}
                        >
                          {exp.status}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1.5">
                          <Link
                            to={`/experiments/${exp.id}`}
                            className="p-1.5 text-[#5f745b] hover:bg-[#879B83]/15 rounded-md transition-colors"
                            title="Inspect experiment"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </Link>

                          {exp.status === 'draft' && (
                            <>
                              <button
                                onClick={() => {
                                  setEditingDraft(exp);
                                  setIsModalOpen(true);
                                }}
                                className="p-1.5 text-[#777A72] hover:text-[#343832] hover:bg-[#EFEEE7] rounded-md transition-colors"
                                title="Edit draft configuration"
                              >
                                <Edit2 className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => setDeletingExperiment(exp)}
                                className="p-1.5 text-[#A46F70] hover:bg-[#A46F70]/15 rounded-md transition-colors"
                                title="Delete draft experiment"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <NewExperimentModal
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setEditingDraft(null);
        }}
        applications={applications}
        onSave={handleSave}
        initialData={editingDraft}
      />

      <ConfirmationDialog
        isOpen={!!deletingExperiment}
        title="Delete Draft Experiment"
        message={`Are you sure you want to permanently delete draft "${deletingExperiment?.name}"?`}
        confirmLabel="Delete Draft"
        onConfirm={confirmDelete}
        onCancel={() => setDeletingExperiment(null)}
      />
    </Layout>
  );
};

export default Experiments;