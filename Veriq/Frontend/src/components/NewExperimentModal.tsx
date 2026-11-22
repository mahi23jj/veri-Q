import React, { useEffect, useState } from 'react';
import { AlertCircle, FlaskConical, X } from 'lucide-react';
import { api } from '../api/client';
import type { Experiment } from '../api/types';

interface NewExperimentModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Application that owns the experiment. Required by the backend. */
  applicationId: string | null;
  /** Registered task names for the datalist; free text is still allowed. */
  taskNames: string[];
  initialData?: Experiment | null;
  onSaved: (experiment: Experiment) => void;
}

export const NewExperimentModal: React.FC<NewExperimentModalProps> = ({
  isOpen,
  onClose,
  applicationId,
  taskNames,
  initialData,
  onSaved,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [taskName, setTaskName] = useState('');
  const [checkpointName, setCheckpointName] = useState('');
  const [timeoutSeconds, setTimeoutSeconds] = useState(60);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setName(initialData?.name ?? '');
    setDescription(initialData?.description ?? '');
    setTaskName(initialData?.task_name ?? '');
    setCheckpointName(initialData?.checkpoint_name ?? '');
    setTimeoutSeconds(initialData?.timeout_seconds ?? 60);
    setFieldErrors({});
    setSubmitError(null);
    setBusy(false);
  }, [isOpen, initialData]);

  if (!isOpen) return null;

  const editing = !!initialData;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const errors: Record<string, string> = {};
    const trimmedName = name.trim();
    const trimmedTask = taskName.trim();
    if (!trimmedName) errors.name = 'Experiment name is required';
    if (!trimmedTask) errors.taskName = 'Target task name is required';
    if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0 || timeoutSeconds > 3600) {
      errors.timeout = 'Timeout must be between 1 and 3600 seconds';
    }
    if (!editing && !applicationId) errors.name = 'Select an application first';
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setBusy(true);
    setSubmitError(null);
    try {
      const payload = {
        name: trimmedName,
        description: description.trim() || null,
        task_name: trimmedTask,
        checkpoint_name: checkpointName.trim() || null,
        timeout_seconds: Math.round(timeoutSeconds),
      };
      const saved = editing
        ? await api.updateExperiment(initialData!.id, payload)
        : await api.createExperiment({
            target_app_id: applicationId!,
            scenario: 'crash_after_commit',
            ...payload,
          });
      onSaved(saved);
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : 'Could not save experiment');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#F0F6FC]/40 backdrop-blur-xs">
      <div className="w-full max-w-lg max-h-[92vh] bg-[#000000] rounded-xl border border-[#30363D] shadow-xl overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-[#30363D] bg-[#000000] flex items-start justify-between gap-4">
          <div>
            <h2 className="font-serif font-bold text-lg text-[#F0F6FC]">
              {editing ? 'Edit Draft Experiment' : 'New Reliability Experiment'}
            </h2>
            <p className="text-xs text-[#B1BAC4] mt-0.5">
              Experiments are stored as a definition. The backend does not execute scenarios yet.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#B1BAC4] hover:text-[#F0F6FC] rounded-md hover:bg-[#161B22] transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4 overflow-y-auto">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1">
              Experiment name <span className="text-[#F85149]">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={200}
              autoFocus
              placeholder="e.g. Charge order survives worker crash"
              className={`w-full px-3.5 py-2 text-sm bg-[#000000] border ${
                fieldErrors.name ? 'border-[#F85149]' : 'border-[#30363D]'
              } rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]`}
            />
            {fieldErrors.name && <p className="text-xs text-[#F85149] mt-1">{fieldErrors.name}</p>}
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1">
              Target task <span className="text-[#F85149]">*</span>
            </label>
            <input
              type="text"
              list="experiment-task-options"
              value={taskName}
              onChange={(event) => setTaskName(event.target.value)}
              maxLength={255}
              placeholder="app.tasks.charge_order"
              className={`w-full px-3.5 py-2 text-sm font-mono bg-[#000000] border ${
                fieldErrors.taskName ? 'border-[#F85149]' : 'border-[#30363D]'
              } rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]`}
            />
            <datalist id="experiment-task-options">
              {taskNames.map((task) => (
                <option key={task} value={task} />
              ))}
            </datalist>
            {fieldErrors.taskName && (
              <p className="text-xs text-[#F85149] mt-1">{fieldErrors.taskName}</p>
            )}
            <p className="text-[11px] text-[#B1BAC4] mt-1">
              {taskNames.length > 0
                ? 'Suggestions come from the discovered task catalog; any Celery task name is accepted.'
                : 'No tasks discovered yet — type the fully qualified Celery task name.'}
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1">
                Scenario
              </label>
              <select
                value="crash_after_commit"
                disabled
                className="w-full px-3.5 py-2 text-sm bg-[#161B22] border border-[#30363D] rounded-lg text-[#C9D1D9]"
              >
                <option value="crash_after_commit">crash_after_commit</option>
              </select>
              <p className="text-[11px] text-[#B1BAC4] mt-1">Only scenario implemented by the backend.</p>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1">
                Timeout (seconds)
              </label>
              <input
                type="number"
                min={1}
                max={3600}
                value={timeoutSeconds}
                onChange={(event) => setTimeoutSeconds(Number(event.target.value))}
                className={`w-full px-3.5 py-2 text-sm bg-[#000000] border ${
                  fieldErrors.timeout ? 'border-[#F85149]' : 'border-[#30363D]'
                } rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]`}
              />
              {fieldErrors.timeout && (
                <p className="text-xs text-[#F85149] mt-1">{fieldErrors.timeout}</p>
              )}
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1">
              Checkpoint name
            </label>
            <input
              type="text"
              value={checkpointName}
              onChange={(event) => setCheckpointName(event.target.value)}
              maxLength={150}
              placeholder="e.g. payment_charged"
              className="w-full px-3.5 py-2 text-sm font-mono bg-[#000000] border border-[#30363D] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]"
            />
            <p className="text-[11px] text-[#B1BAC4] mt-1">
              Matches a <span className="font-mono">veriq.checkpoint(name)</span> call in the task.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] mb-1">
              Description
            </label>
            <textarea
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What reliability property should this experiment protect?"
              className="w-full px-3.5 py-2 text-sm bg-[#000000] border border-[#30363D] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C9D1D9]"
            />
          </div>

          {submitError && (
            <div className="p-3 bg-[#F85149]/10 border border-[#F85149]/30 rounded-lg text-xs text-[#FF7B72] flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span className="break-words">{submitError}</span>
            </div>
          )}

          <div className="p-3 bg-[#000000] border border-[#30363D] rounded-lg text-xs text-[#B1BAC4] flex items-start gap-2">
            <FlaskConical className="w-3.5 h-3.5 text-[#C9D1D9] mt-0.5 shrink-0" />
            <span>
              Saving creates a <span className="font-mono">DRAFT</span> definition. Only drafts can be
              edited or deleted, and creating one does not enqueue any task.
            </span>
          </div>

          <div className="pt-3 border-t border-[#30363D] flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="px-4 py-2 text-xs font-medium text-[#B1BAC4] hover:text-[#F0F6FC] disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="px-5 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] disabled:opacity-60 rounded-lg shadow-2xs transition-all"
            >
              {busy ? 'Saving…' : editing ? 'Update Draft' : 'Create Draft'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
