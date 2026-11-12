import React, { useState } from 'react';
import type { Application } from '../types';
import { X, ShieldAlert } from 'lucide-react';

interface RegisterAppModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRegister: (app: Omit<Application, 'id' | 'experimentCount' | 'createdAt' | 'status'>) => void;
  initialData?: Application | null;
}

export const RegisterAppModal: React.FC<RegisterAppModalProps> = ({
  isOpen,
  onClose,
  onRegister,
  initialData
}) => {
  const [name, setName] = useState(initialData?.name || '');
  const [description, setDescription] = useState(initialData?.description || '');
  const [environment, setEnvironment] = useState<'production' | 'staging' | 'development' | 'canary'>(
    initialData?.environment || 'staging'
  );
  const [framework, setFramework] = useState(initialData?.framework || 'Celery 5.3 (Redis)');
  const [importPath, setImportPath] = useState(initialData?.importPath || '');
  const [defaultTask, setDefaultTask] = useState(initialData?.defaultTask || '');
  const [errors, setErrors] = useState<Record<string, string>>({});

  if (!isOpen) return null;

  const validate = () => {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = 'Application name is required';
    if (!importPath.trim()) errs.importPath = 'Import path is required (e.g., package.tasks)';
    if (!framework.trim()) errs.framework = 'Framework specification is required';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    onRegister({
      name: name.trim(),
      description: description.trim(),
      environment,
      framework: framework.trim(),
      importPath: importPath.trim(),
      defaultTask: defaultTask.trim() || undefined
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#343832]/40 backdrop-blur-xs">
      <div className="w-full max-w-lg bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-xl overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-[#E5E1D7] bg-[#FAF8F3] flex items-center justify-between">
          <div>
            <h2 className="font-serif font-bold text-lg text-[#343832]">
              {initialData ? 'Edit Application' : 'Register Application Target'}
            </h2>
            <p className="text-xs text-[#777A72] mt-0.5">
              Hook QueueProof into your background worker harness without secret keys.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#777A72] hover:text-[#343832] rounded-md hover:bg-[#EFEEE7] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Application Name <span className="text-[#A46F70]">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Billing Dispatcher"
              className={`w-full px-3.5 py-2 text-sm bg-white border ${
                errors.name ? 'border-[#A46F70]' : 'border-[#E5E1D7]'
              } rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]`}
            />
            {errors.name && <p className="text-xs text-[#A46F70] mt-1">{errors.name}</p>}
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Environment
            </label>
            <select
              value={environment}
              onChange={(e) => setEnvironment(e.target.value as any)}
              className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
            >
              <option value="staging">staging</option>
              <option value="development">development</option>
              <option value="canary">canary</option>
              <option value="production">production</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Task Framework & Broker <span className="text-[#A46F70]">*</span>
            </label>
            <input
              type="text"
              value={framework}
              onChange={(e) => setFramework(e.target.value)}
              placeholder="e.g. Celery 5.3 (Redis) or BullMQ (IORedis)"
              className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Module / Worker Import Path <span className="text-[#A46F70]">*</span>
            </label>
            <input
              type="text"
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              placeholder="e.g. services.billing.tasks:process_subscription"
              className="w-full px-3.5 py-2 text-sm font-mono bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
            />
            {errors.importPath && <p className="text-xs text-[#A46F70] mt-1">{errors.importPath}</p>}
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Optional Default Task Identifier
            </label>
            <input
              type="text"
              value={defaultTask}
              onChange={(e) => setDefaultTask(e.target.value)}
              placeholder="e.g. process_subscription"
              className="w-full px-3.5 py-2 text-sm font-mono bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Description
            </label>
            <textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="High-level purpose and business domain of this service..."
              className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
            />
          </div>

          <div className="p-3 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg text-xs text-[#777A72]">
            <div className="font-semibold text-[#343832] flex items-center gap-1.5 mb-0.5">
              <ShieldAlert className="w-3.5 h-3.5 text-[#8297AC]" />
              Zero Credentials Needed
            </div>
            QueueProof uses transparent local instrumentation hooks. No production secrets or API keys are required.
          </div>

          <div className="pt-3 border-t border-[#E5E1D7] flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-[#777A72] hover:text-[#343832]"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all"
            >
              {initialData ? 'Update Application' : 'Register Application'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};