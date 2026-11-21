import React, { useState } from 'react';
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Inbox,
  Loader2,
  RotateCcw,
} from 'lucide-react';

/* ------------------------------------------------------------------ headers */

export const PageHeader: React.FC<{
  title: string;
  description?: string;
  eyebrow?: React.ReactNode;
  actions?: React.ReactNode;
}> = ({ title, description, eyebrow, actions }) => (
  <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-4 border-b border-[#E5E1D7]">
    <div className="min-w-0">
      {eyebrow && <div className="mb-1.5">{eyebrow}</div>}
      <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#343832] tracking-tight">{title}</h1>
      {description && <p className="text-xs md:text-sm text-[#777A72] mt-1 max-w-3xl">{description}</p>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>}
  </div>
);

/* -------------------------------------------------------------- async states */

export const LoadingState: React.FC<{ label?: string }> = ({ label = 'Loading…' }) => (
  <div className="flex items-center justify-center gap-2 py-12 text-xs text-[#777A72] font-mono">
    <Loader2 className="w-4 h-4 animate-spin" />
    {label}
  </div>
);

export const ErrorState: React.FC<{ message: string; onRetry?: () => void }> = ({
  message,
  onRetry,
}) => (
  <div className="p-5 bg-[#A46F70]/10 border border-[#A46F70]/30 rounded-xl flex items-start gap-3">
    <AlertCircle className="w-4 h-4 text-[#A46F70] mt-0.5 shrink-0" />
    <div className="min-w-0 flex-1">
      <p className="text-sm font-medium text-[#733e3f]">Request failed</p>
      <p className="text-xs text-[#733e3f]/80 mt-0.5 break-words">{message}</p>
    </div>
    {onRetry && (
      <button
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#733e3f] bg-white border border-[#A46F70]/30 rounded-lg hover:bg-[#A46F70]/10 transition-colors shrink-0"
      >
        <RotateCcw className="w-3.5 h-3.5" />
        Retry
      </button>
    )}
  </div>
);

export const EmptyState: React.FC<{
  title: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}> = ({ title, description, icon, action }) => (
  <div className="p-8 text-center border border-dashed border-[#E5E1D7] rounded-xl bg-[#FAF8F3]">
    <div className="w-10 h-10 rounded-full bg-[#EFEEE7] text-[#777A72] flex items-center justify-center mx-auto mb-3">
      {icon ?? <Inbox className="w-5 h-5" />}
    </div>
    <p className="text-sm font-medium text-[#343832]">{title}</p>
    {description && <p className="text-xs text-[#777A72] mt-1 max-w-md mx-auto leading-relaxed">{description}</p>}
    {action && <div className="mt-4 flex justify-center">{action}</div>}
  </div>
);

/* ------------------------------------------------------------------- badges */

type BadgeTone = 'sage' | 'rose' | 'blue' | 'beige' | 'muted';

const TONES: Record<BadgeTone, string> = {
  sage: 'bg-[#879B83]/15 text-[#3e563a] border-[#879B83]/30',
  rose: 'bg-[#A46F70]/15 text-[#733e3f] border-[#A46F70]/30',
  blue: 'bg-[#8297AC]/15 text-[#3b5168] border-[#8297AC]/30',
  beige: 'bg-[#D8C8AE]/30 text-[#6b5a43] border-[#D8C8AE]/60',
  muted: 'bg-[#777A72]/12 text-[#4e5149] border-[#777A72]/25',
};

function toneForStatus(status: string): BadgeTone {
  switch (status.toUpperCase()) {
    case 'SUCCEEDED':
    case 'ONLINE':
    case 'OBSERVING':
    case 'ACTIVE':
    case 'COMPLETED':
    case 'PASSED':
    case 'PASS':
    case 'APPROVED':
    case 'READY':
    case 'CLEANED':
    case 'VALIDATED':
      return 'sage';
    case 'FAILED':
    case 'ERROR':
    case 'OFFLINE':
    case 'CANCELLED':
    case 'NEEDS_CHANGES':
    case 'BLOCKED':
    case 'INVALID':
      return 'rose';
    case 'RUNNING':
    case 'DISCOVERED':
    case 'PENDING':
    case 'PREPARING':
    case 'PREPARING_FAULT':
    case 'VERIFYING':
    case 'VALIDATING':
    case 'PROVISIONING':
    case 'STARTING':
    case 'INJECTING':
    case 'OBSERVING_RECOVERY':
    case 'EVALUATING':
    case 'FINALIZING':
    case 'ARMED':
      return 'blue';
    case 'RETRYING':
    case 'DRAFT':
    case 'INCONCLUSIVE':
    case 'INVALID_RUN':
    case 'NEEDS_CONFIGURATION':
    case 'READY_FOR_REVIEW':
    case 'TRIGGERED':
      return 'beige';
    default:
      return 'muted';
  }
}

function labelForStatus(status: string): string {
  const words = status.replace(/_/g, ' ').toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const StatusBadge: React.FC<{ status: string | null | undefined; label?: string }> = ({
  status,
  label,
}) => {
  const value = status || 'UNKNOWN';
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-medium whitespace-nowrap ${TONES[toneForStatus(value)]}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
      {label ?? labelForStatus(value)}
    </span>
  );
};

export const Pill: React.FC<{ children: React.ReactNode; tone?: BadgeTone; title?: string }> = ({
  children,
  tone = 'muted',
  title,
}) => (
  <span
    title={title}
    className={`inline-flex items-center px-2 py-0.5 rounded border text-[10px] font-mono whitespace-nowrap ${TONES[tone]}`}
  >
    {children}
  </span>
);

/* --------------------------------------------------------------- pagination */

export const Pagination: React.FC<{
  total: number;
  skip: number;
  limit: number;
  onChange: (skip: number) => void;
}> = ({ total, skip, limit, onChange }) => {
  if (total === 0) return null;
  const from = total === 0 ? 0 : skip + 1;
  const to = Math.min(skip + limit, total);
  const canPrev = skip > 0;
  const canNext = skip + limit < total;

  return (
    <div className="flex items-center justify-between gap-3 pt-3 border-t border-[#E5E1D7]">
      <span className="text-[11px] text-[#777A72] font-mono">
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => onChange(Math.max(0, skip - limit))}
          disabled={!canPrev}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-[#E5E1D7] bg-white text-[#52564e] enabled:hover:bg-[#EFEEE7] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" /> Previous
        </button>
        <button
          onClick={() => onChange(skip + limit)}
          disabled={!canNext}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-[#E5E1D7] bg-white text-[#52564e] enabled:hover:bg-[#EFEEE7] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Next <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------- pieces */

export const CopyButton: React.FC<{ value: string; label?: string }> = ({ value, label }) => {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#EFEEE7] transition-colors shrink-0"
      title="Copy to clipboard"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-[#3e563a]" /> : <Copy className="w-3.5 h-3.5" />}
      {copied ? 'Copied' : label ?? 'Copy'}
    </button>
  );
};

export const CodeBlock: React.FC<{ code: string; language?: string; label?: string }> = ({
  code,
  language = 'bash',
  label,
}) => (
  <div className="rounded-lg border border-[#E5E1D7] overflow-hidden bg-[#FAF8F3]">
    <div className="flex items-center justify-between px-3 py-2 border-b border-[#E5E1D7] bg-[#FDFCFA]">
      <span className="text-[10px] uppercase tracking-wider font-mono text-[#777A72]">
        {label ?? language}
      </span>
      <CopyButton value={code} />
    </div>
    <pre className="p-3.5 overflow-x-auto text-[11.5px] leading-relaxed text-[#343832] font-mono whitespace-pre">
      {code}
    </pre>
  </div>
);

export const DetailRow: React.FC<{
  label: string;
  children: React.ReactNode;
  mono?: boolean;
  className?: string;
}> = ({ label, children, mono, className }) => (
  <div className={`p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7] min-w-0 ${className ?? ''}`}>
    <span className="text-[#777A72] block text-[11px]">{label}</span>
    <span
      className={`mt-0.5 block text-[#343832] break-words ${mono ? 'font-mono text-[11.5px]' : 'text-xs font-medium'}`}
    >
      {children}
    </span>
  </div>
);

export const SectionCard: React.FC<{
  title: string;
  description?: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}> = ({ title, description, icon, actions, children, className, bodyClassName }) => (
  <section className={`bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-2xs ${className ?? ''}`}>
    <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5 border-b border-[#E5E1D7]">
      <div className="flex items-center gap-2 min-w-0">
        {icon}
        <div className="min-w-0">
          <h2 className="font-serif font-bold text-base text-[#343832] truncate">{title}</h2>
          {description && <p className="text-[11px] text-[#777A72]">{description}</p>}
        </div>
      </div>
      {actions}
    </div>
    <div className={bodyClassName ?? 'p-5'}>{children}</div>
  </section>
);
