import React from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, KeyRound, X } from 'lucide-react';
import { CopyButton } from './ui';

interface ApiKeyModalProps {
  isOpen: boolean;
  applicationName: string;
  apiKey: string;
  /** True when the key came from rotation rather than initial creation. */
  rotated?: boolean;
  onClose: () => void;
}

export const ApiKeyModal: React.FC<ApiKeyModalProps> = ({
  isOpen,
  applicationName,
  apiKey,
  rotated = false,
  onClose,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#F0F6FC]/40 backdrop-blur-xs">
      <div className="w-full max-w-xl bg-[#000000] rounded-xl border border-[#30363D] shadow-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-[#30363D] bg-[#000000] flex items-start justify-between gap-4">
          <div>
            <h2 className="font-serif font-bold text-lg text-[#F0F6FC]">
              {rotated ? 'New API key issued' : 'Application registered'}
            </h2>
            <p className="text-xs text-[#B1BAC4] mt-0.5">{applicationName}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#B1BAC4] hover:text-[#F0F6FC] rounded-md hover:bg-[#161B22] transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div className="p-3 bg-[#C9D1D9]/30 border border-[#C9D1D9]/70 rounded-lg text-xs text-[#C9D1D9] flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            <div>
              <span className="font-semibold block">This key is displayed only once.</span>
              {rotated
                ? 'The previous key no longer works. Copy the new key now; it cannot be retrieved later.'
                : 'Copy the key now and store it as a secret in your application environment. It cannot be retrieved later — only rotated.'}
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5" /> SDK API key
              </span>
              <CopyButton value={apiKey} label="Copy key" />
            </div>
            <code className="block w-full px-3.5 py-3 text-xs font-mono break-all bg-[#000000] border border-[#30363D] rounded-lg text-[#F0F6FC]">
              {apiKey}
            </code>
          </div>

          <div className="text-xs text-[#B1BAC4] leading-relaxed space-y-1">
            <p className="font-semibold text-[#F0F6FC]">Use it in the target application:</p>
            <p>
              Set it as <span className="font-mono bg-[#161B22] px-1 rounded">VERIQ_API_KEY</span> and
              point <span className="font-mono bg-[#161B22] px-1 rounded">VERIQ_API_URL</span> at this
              backend. Never commit it to source control or bake it into an image.
            </p>
          </div>

          <div className="pt-3 border-t border-[#30363D] flex flex-wrap items-center justify-end gap-2">
            <Link
              to="/integration"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] hover:bg-[#161B22] rounded-lg transition-colors"
            >
              Open SDK integration guide
            </Link>
            <button
              onClick={onClose}
              className="px-5 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg shadow-2xs transition-all"
            >
              I have copied the key
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
