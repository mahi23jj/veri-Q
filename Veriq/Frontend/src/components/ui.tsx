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
  <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-4 border-b border-[#30363D]">
    <div className="min-w-0">
      {eyebrow && <div className="mb-1.5">{eyebrow}</div>}
      <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#F0F6FC] tracking-tight">{title}</h1>
      {description && <p className="text-xs md:text-sm text-[#B1BAC4] mt-1 max-w-3xl">{description}</p>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>}
  </div>
);

/* -------------------------------------------------------------- async states */

export const LoadingState: React.FC<{ label?: string }> = ({ label = 'Loading…' }) => (
  <div className="flex items-center justify-center gap-2 py-12 text-xs text-[#B1BAC4] font-mono">
    <Loader2 className="w-4 h-4 animate-spin" />
    {label}
  </div>
);

export const ErrorState: React.FC<{ message: string; onRetry?: () => void }> = ({
  message,
  onRetry,
}) => (
  <div className="p-5 bg-[#F85149]/10 border border-[#F85149]/30 rounded-xl flex items-start gap-3">
    <AlertCircle className="w-4 h-4 text-[#F85149] mt-0.5 shrink-0" />
    <div className="min-w-0 flex-1">
      <p className="text-sm font-medium text-[#FF7B72]">Request failed</p>
      <p className="text-xs text-[#FF7B72]/80 mt-0.5 break-words">{message}</p>
    </div>
    {onRetry && (
      <button
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#FF7B72] bg-[#000000] border border-[#F85149]/30 rounded-lg hover:bg-[#F85149]/10 transition-colors shrink-0"
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
  <div className="p-8 text-center border border-dashed border-[#30363D] rounded-xl bg-[#000000]">
    <div className="w-10 h-10 rounded-full bg-[#161B22] text-[#B1BAC4] flex items-center justify-center mx-auto mb-3">
      {icon ?? <Inbox className="w-5 h-5" />}
    </div>
    <p className="text-sm font-medium text-[#F0F6FC]">{title}</p>
    {description && <p className="text-xs text-[#B1BAC4] mt-1 max-w-md mx-auto leading-relaxed">{description}</p>}
    {action && <div className="mt-4 flex justify-center">{action}</div>}
  </div>
);

/* ------------------------------------------------------------------- badges */

type BadgeTone = 'sage' | 'rose' | 'blue' | 'beige' | 'muted';

const TONES: Record<BadgeTone, string> = {
  sage: 'bg-[#56D364]/15 text-[#56D364] border-[#56D364]/30',
  rose: 'bg-[#F85149]/15 text-[#FF7B72] border-[#F85149]/30',
  blue: 'bg-[#D29922]/15 text-[#E3B341] border-[#D29922]/30',
  beige: 'bg-[#D29922]/15 text-[#E3B341] border-[#D29922]/30',
  muted: 'bg-[#B1BAC4]/12 text-[#B1BAC4] border-[#B1BAC4]/25',
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
    <div className="flex items-center justify-between gap-3 pt-3 border-t border-[#30363D]">
      <span className="text-[11px] text-[#B1BAC4] font-mono">
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => onChange(Math.max(0, skip - limit))}
          disabled={!canPrev}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-[#30363D] bg-[#000000] text-[#C9D1D9] enabled:hover:bg-[#161B22] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" /> Previous
        </button>
        <button
          onClick={() => onChange(skip + limit)}
          disabled={!canNext}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-[#30363D] bg-[#000000] text-[#C9D1D9] enabled:hover:bg-[#161B22] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors shrink-0"
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
  <div className="rounded-lg border border-[#30363D] overflow-hidden bg-[#000000]">
    <div className="flex items-center justify-between px-3 py-2 border-b border-[#30363D] bg-[#000000]">
      <span className="text-[10px] uppercase tracking-wider font-mono text-[#B1BAC4]">
        {label ?? language}
      </span>
      <CopyButton value={code} />
    </div>
    <pre className="p-3.5 overflow-x-auto text-[11.5px] leading-relaxed text-[#F0F6FC] font-mono whitespace-pre">
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
  <div className={`p-3 bg-[#000000] rounded-lg border border-[#30363D] min-w-0 ${className ?? ''}`}>
    <span className="text-[#B1BAC4] block text-[11px]">{label}</span>
    <span
      className={`mt-0.5 block text-[#F0F6FC] break-words ${mono ? 'font-mono text-[11.5px]' : 'text-xs font-medium'}`}
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
  <section className={`bg-[#000000] rounded-xl border border-[#30363D] shadow-2xs ${className ?? ''}`}>
    <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5 border-b border-[#30363D]">
      <div className="flex items-center gap-2 min-w-0">
        {icon}
        <div className="min-w-0">
          <h2 className="font-serif font-bold text-base text-[#F0F6FC] truncate">{title}</h2>
          {description && <p className="text-[11px] text-[#B1BAC4]">{description}</p>}
        </div>
      </div>
      {actions}
    </div>
    <div className={bodyClassName ?? 'p-5'}>{children}</div>
  </section>
);
