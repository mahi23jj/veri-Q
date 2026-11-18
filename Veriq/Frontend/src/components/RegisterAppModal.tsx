import React, { useEffect, useState } from 'react';
import { AlertCircle, ShieldAlert, X } from 'lucide-react';
import { api } from '../api/client';
import type { TargetApplicationWithKey } from '../api/types';

interface RegisterAppModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (created: TargetApplicationWithKey) => void;
}

export const RegisterAppModal: React.FC<RegisterAppModalProps> = ({
  isOpen,
  onClose,
  onCreated,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [environment, setEnvironment] = useState<'development' | 'test'>('test');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setName('');
    setDescription('');
    setEnvironment('test');
    setFieldErrors({});
    setSubmitError(null);
    setBusy(false);
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const errors: Record<string, string> = {};
    const trimmedName = name.trim();
    if (!trimmedName) errors.name = 'Application name is required';
    if (trimmedName.length > 150) errors.name = 'Application name must be 150 characters or fewer';
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setBusy(true);
    setSubmitError(null);
    try {
      const created = await api.createApplication({
        name: trimmedName,
        description: description.trim() || null,
        environment,
      });
      onCreated(created);
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : 'Could not register application');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#343832]/40 backdrop-blur-xs">
      <div className="w-full max-w-lg bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-xl overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-[#E5E1D7] bg-[#FAF8F3] flex items-start justify-between gap-4">
          <div>
            <h2 className="font-serif font-bold text-lg text-[#343832]">Register Target Application</h2>
            <p className="text-xs text-[#777A72] mt-0.5">
              Create the application, copy its one-time API key, then connect the SDK.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#777A72] hover:text-[#343832] rounded-md hover:bg-[#EFEEE7] transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Application name <span className="text-[#A46F70]">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Billing Dispatcher"
              maxLength={150}
              autoFocus
              className={`w-full px-3.5 py-2 text-sm bg-white border ${
                fieldErrors.name ? 'border-[#A46F70]' : 'border-[#E5E1D7]'
              } rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]`}
            />
            {fieldErrors.name && <p className="text-xs text-[#A46F70] mt-1">{fieldErrors.name}</p>}
            <p className="text-[11px] text-[#777A72] mt-1">
              Names must be unique; the backend rejects duplicates with HTTP 409.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Environment
            </label>
            <select
              value={environment}
              onChange={(event) => setEnvironment(event.target.value as 'development' | 'test')}
              className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
            >
              <option value="test">test</option>
              <option value="development">development</option>
            </select>
            <p className="text-[11px] text-[#777A72] mt-1">
              The backend currently accepts <span className="font-mono">development</span> and{' '}
              <span className="font-mono">test</span> only.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Description
            </label>
            <textarea
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="High-level purpose of this background-job service..."
              className="w-full px-3.5 py-2 text-sm bg-white border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#879B83]"
            />
          </div>

          {submitError && (
            <div className="p-3 bg-[#A46F70]/10 border border-[#A46F70]/30 rounded-lg text-xs text-[#733e3f] flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span className="break-words">{submitError}</span>
            </div>
          )}

          <div className="p-3 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg text-xs text-[#777A72]">
            <div className="font-semibold text-[#343832] flex items-center gap-1.5 mb-0.5">
              <ShieldAlert className="w-3.5 h-3.5 text-[#8297AC]" />
              What happens next
            </div>
            The response includes an API key that is shown only once. VeriQ stores only its hash, so the
            key cannot be retrieved later — only rotated.
          </div>

          <div className="pt-3 border-t border-[#E5E1D7] flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="px-4 py-2 text-xs font-medium text-[#777A72] hover:text-[#343832] disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="px-5 py-2 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] disabled:opacity-60 rounded-lg shadow-2xs transition-all"
            >
              {busy ? 'Registering…' : 'Register Application'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
