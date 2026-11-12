import React, { useState } from 'react';
import { Layout } from '../components/Layout';
import { INITIAL_APPLICATIONS, INITIAL_EXPERIMENTS, INITIAL_RUNS } from '../mockData';
import type { Application } from '../types';
import { RegisterAppModal } from '../components/RegisterAppModal';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import { VerdictBadge } from '../components/VerdictBadge';
import { Link } from 'react-router-dom';
import {
  Boxes,
  Plus,
  Server,
  FolderGit2,
  Calendar,
  Layers,
  Edit2,
  Trash2,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  ChevronRight
} from 'lucide-react';
import { toast } from 'react-toastify';

export const Applications: React.FC = () => {
  const [apps, setApps] = useState<Application[]>(INITIAL_APPLICATIONS);
  const [selectedApp, setSelectedApp] = useState<Application | null>(INITIAL_APPLICATIONS[0]);
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);
  const [editingApp, setEditingApp] = useState<Application | null>(null);
  const [deletingApp, setDeletingApp] = useState<Application | null>(null);

  const handleRegisterOrUpdate = (appData: Omit<Application, 'id' | 'experimentCount' | 'createdAt' | 'status'>) => {
    if (editingApp) {
      const updated = apps.map(a => a.id === editingApp.id ? { ...a, ...appData } : a);
      setApps(updated);
      if (selectedApp?.id === editingApp.id) {
        setSelectedApp({ ...selectedApp, ...appData });
      }
      toast.success('Application updated successfully');
      setEditingApp(null);
    } else {
      const newApp: Application = {
        id: `app-${Date.now()}`,
        ...appData,
        experimentCount: 0,
        createdAt: new Date().toISOString().split('T')[0],
        status: 'healthy'
      };
      setApps([...apps, newApp]);
      setSelectedApp(newApp);
      toast.success('Application registered successfully');
    }
  };

  const confirmDelete = () => {
    if (!deletingApp) return;
    const remaining = apps.filter(a => a.id !== deletingApp.id);
    setApps(remaining);
    if (selectedApp?.id === deletingApp.id) {
      setSelectedApp(remaining[0] || null);
    }
    toast.info(`Application "${deletingApp.name}" removed`);
    setDeletingApp(null);
  };

  // Associated experiments and runs for selected app
  const associatedExperiments = selectedApp
    ? INITIAL_EXPERIMENTS.filter(e => e.applicationId === selectedApp.id)
    : [];
  const associatedRuns = selectedApp
    ? INITIAL_RUNS.filter(r => r.applicationId === selectedApp.id)
    : [];

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#E5E1D7]">
          <div>
            <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#343832] tracking-tight">
              Target Applications
            </h1>
            <p className="text-xs md:text-sm text-[#777A72] mt-1">
              Registered background worker pools and microservices subject to reliability verification.
            </p>
          </div>
          <button
            onClick={() => {
              setEditingApp(null);
              setIsRegisterOpen(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all active:scale-[0.98]"
          >
            <Plus className="w-4 h-4" />
            Register Application
          </button>
        </div>

        {/* Master-Detail Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Applications List (5 cols) */}
          <div className="lg:col-span-5 space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[#777A72] px-1">
              Registered Services ({apps.length})
            </h2>

            {apps.map((app) => {
              const isSelected = selectedApp?.id === app.id;
              return (
                <div
                  key={app.id}
                  onClick={() => setSelectedApp(app)}
                  className={`p-4 rounded-xl border cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-[#FDFCFA] border-[#879B83] shadow-xs ring-1 ring-[#879B83]/30'
                      : 'bg-[#FDFCFA] border-[#E5E1D7] hover:border-[#D8C8AE] hover:bg-[#FAF8F3]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="font-serif font-bold text-base text-[#343832]">{app.name}</h3>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#EFEEE7] text-[#52564e]">
                          {app.framework}
                        </span>
                        <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-[#879B83]/15 text-[#3e563a] font-medium">
                          {app.environment}
                        </span>
                      </div>
                    </div>
                    <span className="text-xs font-mono bg-[#FAF8F3] px-2 py-1 rounded border border-[#E5E1D7] text-[#777A72]">
                      {app.experimentCount} exps
                    </span>
                  </div>

                  <p className="text-xs text-[#777A72] mt-2.5 line-clamp-2 leading-relaxed">
                    {app.description}
                  </p>

                  <div className="mt-3 pt-3 border-t border-[#E5E1D7]/70 flex items-center justify-between text-[11px] text-[#777A72]">
                    <span className="font-mono truncate max-w-[200px]">{app.importPath}</span>
                    <span>Created {app.createdAt}</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Application Detail View (7 cols) */}
          <div className="lg:col-span-7">
            {selectedApp ? (
              <div className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-2xs overflow-hidden">
                {/* Header */}
                <div className="p-6 border-b border-[#E5E1D7] bg-[#FAF8F3] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2.5">
                      <h2 className="font-serif font-bold text-xl text-[#343832]">{selectedApp.name}</h2>
                      <span className="w-2 h-2 rounded-full bg-[#879B83]" title="Harness connected" />
                    </div>
                    <p className="text-xs text-[#777A72] mt-1">{selectedApp.description}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        setEditingApp(selectedApp);
                        setIsRegisterOpen(true);
                      }}
                      className="p-2 text-[#777A72] hover:text-[#343832] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#EFEEE7] transition-colors"
                      title="Edit application configuration"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => setDeletingApp(selectedApp)}
                      className="p-2 text-[#A46F70] hover:text-[#733e3f] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#A46F70]/10 transition-colors"
                      title="Delete application"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Configuration Breakdown */}
                <div className="p-6 border-b border-[#E5E1D7] space-y-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-[#777A72]">
                    Target Configuration
                  </h3>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7]">
                      <span className="text-[#777A72] block text-[11px]">Worker Runtime Framework</span>
                      <span className="font-mono font-medium text-[#343832] mt-0.5 block">{selectedApp.framework}</span>
                    </div>

                    <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7]">
                      <span className="text-[#777A72] block text-[11px]">Assigned Environment</span>
                      <span className="font-medium text-[#343832] mt-0.5 block uppercase tracking-wider">{selectedApp.environment}</span>
                    </div>

                    <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7] sm:col-span-2">
                      <span className="text-[#777A72] block text-[11px]">Primary Task Import Hook</span>
                      <span className="font-mono text-[#343832] mt-0.5 block break-all">{selectedApp.importPath}</span>
                    </div>

                    {selectedApp.defaultTask && (
                      <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7] sm:col-span-2">
                        <span className="text-[#777A72] block text-[11px]">Default Task Function</span>
                        <span className="font-mono text-[#343832] mt-0.5 block">{selectedApp.defaultTask}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Associated Experiments */}
                <div className="p-6 border-b border-[#E5E1D7]">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-[#777A72]">
                      Associated Experiments ({associatedExperiments.length})
                    </h3>
                    <Link
                      to={`/experiments?app=${selectedApp.id}`}
                      className="text-xs text-[#5f745b] hover:text-[#343832] font-medium"
                    >
                      Filter in Experiments &rarr;
                    </Link>
                  </div>

                  {associatedExperiments.length === 0 ? (
                    <div className="p-4 text-center border border-dashed border-[#E5E1D7] rounded-lg text-xs text-[#777A72]">
                      No experiment definitions configured for this service yet.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {associatedExperiments.map(exp => (
                        <Link
                          key={exp.id}
                          to={`/experiments/${exp.id}`}
                          className="flex items-center justify-between p-3 rounded-lg border border-[#E5E1D7] hover:border-[#D8C8AE] hover:bg-[#FAF8F3] transition-colors"
                        >
                          <div>
                            <div className="font-medium text-xs text-[#343832]">{exp.name}</div>
                            <div className="text-[11px] font-mono text-[#777A72] mt-0.5">{exp.task}</div>
                          </div>
                          <div className="flex items-center gap-2">
                            {exp.lastRun && <VerdictBadge verdict={exp.lastRun.verdict} size="sm" />}
                            <ChevronRight className="w-4 h-4 text-[#777A72]" />
                          </div>
                        </Link>
                      ))}
                    </div>
                  )}
                </div>

                {/* Recent Runs for this App */}
                <div className="p-6">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-3">
                    Recent Verification Runs
                  </h3>

                  {associatedRuns.length === 0 ? (
                    <div className="p-4 text-center border border-dashed border-[#E5E1D7] rounded-lg text-xs text-[#777A72]">
                      No runs recorded yet.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {associatedRuns.slice(0, 3).map(run => (
                        <Link
                          key={run.id}
                          to={`/experiments/${run.experimentId}?runId=${run.id}`}
                          className="flex items-center justify-between p-2.5 rounded-lg bg-[#FAF8F3] border border-[#E5E1D7] text-xs hover:border-[#D8C8AE] transition-colors"
                        >
                          <div className="flex items-center gap-2.5">
                            <span className="font-mono font-medium text-[#343832]">{run.id}</span>
                            <span className="text-[#777A72]">Run #{run.runNumber}</span>
                            <span className="text-[11px] text-[#777A72]">{run.startTime}</span>
                          </div>
                          <VerdictBadge verdict={run.verdict} size="sm" />
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-8 text-center bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] text-sm text-[#777A72]">
                Select an application from the left to inspect configuration and runs.
              </div>
            )}
          </div>
        </div>
      </div>

      <RegisterAppModal
        isOpen={isRegisterOpen}
        onClose={() => {
          setIsRegisterOpen(false);
          setEditingApp(null);
        }}
        onRegister={handleRegisterOrUpdate}
        initialData={editingApp}
      />

      <ConfirmationDialog
        isOpen={!!deletingApp}
        title="Remove Application"
        message={`Are you sure you want to deregister "${deletingApp?.name}"? Associated test definitions will be unlinked.`}
        confirmLabel="Remove Application"
        onConfirm={confirmDelete}
        onCancel={() => setDeletingApp(null)}
      />
    </Layout>
  );
};

export default Applications;