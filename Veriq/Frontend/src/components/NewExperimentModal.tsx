import React, { useState } from 'react';
import type { Application, Experiment } from '../types';
import { X, AlertCircle, CheckCircle, Info } from 'lucide-react';

interface NewExperimentModalProps {
  isOpen: boolean;
  onClose: () => void;
  applications: Application[];
  onSave: (experiment: Partial<Experiment>, isDraft: boolean) => void;
  initialData?: Partial<Experiment> | null;
}

export const NewExperimentModal: React.FC<NewExperimentModalProps> = ({
  isOpen,
  onClose,
  applications,
  onSave,
  initialData
}) => {
  const [name, setName] = useState(initialData?.name || '');
  const [appId, setAppId] = useState(initialData?.applicationId || (applications[0]?.id ?? ''));
  const [task, setTask] = useState(initialData?.task || '');
  const [logicalOpId, setLogicalOpId] = useState(initialData?.logicalOperationIdTemplate || 'tx_order_{uuid}');
  const [checkpoint, setCheckpoint] = useState(initialData?.checkpoint || 'DB_TRANSACTION_COMMITTED');
  const [failureScenario] = useState('Crash after commit');
  const [timeout, setTimeoutVal] = useState(initialData?.timeoutSeconds || 15);
  const [environment, setEnvironment] = useState(initialData?.environment || 'staging');
  const [description, setDescription] = useState(initialData?.description || '');
  const [errors, setErrors] = useState<Record<string, string>>({});

  if (!isOpen) return null;

  const validate = () => {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = 'Experiment name is required';
    if (!appId) errs.appId = 'Please select a target application';
    if (!task.trim()) errs.task = 'Task path or function name is required';
    if (!checkpoint.trim()) errs.checkpoint = 'Checkpoint label is required';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleApplicationChange = (newAppId: string) => {
    setAppId(newAppId);
    const selected = applications.find(a => a.id === newAppId);
    if (selected && !task) {
      setTask(selected.importPath || selected.defaultTask || '');
    }
  };

  const handleSubmit = (asDraft: boolean) => {
    if (!asDraft && !validate()) return;

    const selectedApp = applications.find(a => a.id === appId);
    onSave(
      {
        name: name.trim() || 'Untitled Draft Experiment',
        applicationId: appId,
        applicationName: selectedApp?.name || 'Unknown Application',
        task: task.trim() || 'unspecified_task',
        checkpoint: checkpoint.trim() || 'DB_TRANSACTION_COMMITTED',
        logicalOperationIdTemplate: logicalOpId,
        failureScenario,
        timeoutSeconds: Number(timeout) || 15,
        environment,
        description: description.trim() || 'Simulated crash after commit checkpoint'
      },
      asDraft
    );
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#343832]/40 backdrop-blur-xs">
      <div className="w-full max-w-2xl bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-xl overflow-hidden flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#E5E1D7] bg-[#FAF8F3] flex items-center justify-between">
          <div>
            <h2 className="font-serif font-bold text-lg text-[#343832]">
              {initialData?.id ? 'Edit Experiment Draft' : 'Configure Reliability Experiment'}
            </h2>
            <p className="text-xs text-[#777A72] mt-0.5">
              Simulate crash faults and evaluate post-redelivery business invariants.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#777A72] hover:text-[#343832] rounded-md hover:bg-[#EFEEE7] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-5">
          {/* Failure Scenario Banner (Initial focus: Crash after commit) */}
          <div className="p-3.5 bg-[#FAF8F3] rounded-lg border border-[#D8C8AE]/50 flex items-start gap-3">
            <Info className="w-4 h-4 text-[#8297AC] shrink-0 mt-0.5" />
            <div className="text-xs text-[#52564e]">
              <span className="font-semibold text-[#343832]">Scenario: Crash after commit</span>
              <p className="mt-0.5">
                QueueProof interrupts the worker process immediately following the specified checkpoint, before the queue broker receives job ACK. This tests if operations stay idempotent after task redelivery.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                Experiment Name <span className="text-[#A46F70]">*</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Crash after inventory ledger commit"
                className={`w-full px-3.5 py-2 text-sm bg-white border ${
                  errors.name ? 'border-[#A46F70] focus:ring-[#A46F70]' : 'border-[#E5E1D7] focus:ring-[#879B83]'
                } rounded-lg focus:outline-none focus:ring-2`}
              />
              {errors.name && <p className="text-xs text-[#A46F70] mt-1">{errors.name}</p>}
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                Target Application <span className="text-[#A46F70]">*</span>
              </label>
              <select
                value={appId}
                onChange={(e) => handleApplicationChange(e.target.value)}
                className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
              >
                {applications.map((app) => (
                  <option key={app.id} value={app.id}>
                    {app.name} ({app.framework})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                Environment
              </label>
              <select
                value={environment}
                onChange={(e) => setEnvironment(e.target.value)}
                className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
              >
                <option value="staging">staging</option>
                <option value="development">development</option>
                <option value="canary">canary</option>
              </select>
            </div>

            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                Task Path / Definition <span className="text-[#A46F70]">*</span>
              </label>
              <input
                type="text"
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="e.g. services.inventory.tasks:commit_stock_reservation"
                className={`w-full px-3.5 py-2 text-sm font-mono bg-white border ${
                  errors.task ? 'border-[#A46F70]' : 'border-[#E5E1D7]'
                } rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]`}
              />
              {errors.task && <p className="text-xs text-[#A46F70] mt-1">{errors.task}</p>}
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                Checkpoint Hook Name <span className="text-[#A46F70]">*</span>
              </label>
              <input
                type="text"
                value={checkpoint}
                onChange={(e) => setCheckpoint(e.target.value)}
                placeholder="DB_TRANSACTION_COMMITTED"
                className="w-full px-3.5 py-2 text-sm font-mono bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
              />
              <span className="text-[11px] text-[#777A72] mt-1 block">Simulation fault fires at this exact hook.</span>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                Logical Operation ID Template
              </label>
              <input
                type="text"
                value={logicalOpId}
                onChange={(e) => setLogicalOpId(e.target.value)}
                placeholder="tx_alloc_{uuid}"
                className="w-full px-3.5 py-2 text-sm font-mono bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
              />
              <span className="text-[11px] text-[#777A72] mt-1 block">Carried across retries for idempotency verification.</span>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                Timeout (seconds)
              </label>
              <input
                type="number"
                min="5"
                max="120"
                value={timeout}
                onChange={(e) => setTimeoutVal(Number(e.target.value))}
                className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
              />
            </div>

            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1.5">
                Hypothesis / Failure Description
              </label>
              <textarea
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe what state might corrupt if the worker crashes before queue ACK..."
                className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
              />
            </div>
          </div>

          {/* Configuration Summary Card */}
          <div className="p-3.5 bg-[#EFEEE7]/60 rounded-lg border border-[#E5E1D7] text-xs space-y-1">
            <div className="font-semibold text-[#343832] flex items-center gap-1.5">
              <CheckCircle className="w-3.5 h-3.5 text-[#879B83]" />
              Simulation Lifecycle Preview
            </div>
            <p className="text-[#61655b]">
              Enqueue task <span className="font-mono text-[11px]">{task || 'task_name'}</span> &rarr; Execute till <span className="font-mono text-[11px]">{checkpoint}</span> &rarr; Force SIGKILL &rarr; Redeliver via broker &rarr; Audit ledger for duplicate mutations.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#E5E1D7] bg-[#FAF8F3] flex items-center justify-between">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-xs font-medium text-[#777A72] hover:text-[#343832] transition-colors"
          >
            Cancel
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleSubmit(true)}
              className="px-4 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] hover:bg-[#EFEEE7] rounded-lg transition-colors"
            >
              Save as Draft
            </button>
            <button
              type="button"
              onClick={() => handleSubmit(false)}
              className="px-5 py-2 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all"
            >
              Create Experiment
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};