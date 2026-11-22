import React from 'react';
import { AlertTriangle } from 'lucide-react';

interface ConfirmationDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isDestructive?: boolean;
  isBusy?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

export const ConfirmationDialog: React.FC<ConfirmationDialogProps> = ({
  isOpen,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isDestructive = true,
  isBusy = false,
  onConfirm,
  onCancel
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#F0F6FC]/40 backdrop-blur-xs">
      <div className="w-full max-w-md bg-[#000000] rounded-xl border border-[#30363D] shadow-xl p-6">
        <div className="flex items-start gap-4">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
            isDestructive ? 'bg-[#F85149]/20 text-[#F85149]' : 'bg-[#C9D1D9]/20 text-[#C9D1D9]'
          }`}>
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-serif font-bold text-base text-[#F0F6FC]">{title}</h3>
            <p className="text-xs text-[#B1BAC4] mt-1.5 leading-relaxed">{message}</p>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-2.5">
          <button
            onClick={onCancel}
            disabled={isBusy}
            className="px-4 py-2 text-xs font-medium text-[#B1BAC4] hover:text-[#F0F6FC] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] disabled:opacity-50 transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            disabled={isBusy}
            className={`px-4 py-2 text-xs font-semibold rounded-lg text-white disabled:opacity-60 transition-all ${
              isDestructive
                ? 'bg-[#F85149] hover:bg-[#DA3633]'
                : 'bg-[#C9D1D9] hover:bg-[#C9D1D9]'
            }`}
          >
            {isBusy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};