import React from 'react';
import { AlertTriangle, Check, CircleDot, ShieldAlert, ShieldCheck, ShieldQuestion } from 'lucide-react';
import { Pill } from './ui';
import { LIFECYCLE_STEPS, TERMINAL_LIFECYCLE_STATES } from '../lib/reliability';

/* ------------------------------------------------------------------ badges */

export const CompatibilityBadge: React.FC<{ status: string | null | undefined }> = ({ status }) => {
  const value = status || 'UNKNOWN';
  const tone =
    value === 'COMPATIBLE'
      ? 'sage'
      : value === 'NEEDS_CONFIGURATION'
        ? 'beige'
        : value === 'UNSUPPORTED'
          ? 'rose'
          : 'muted';
  return <Pill tone={tone}>{value.replace(/_/g, ' ')}</Pill>;
};

const VERDICT_TONES: Record<string, 'sage' | 'rose' | 'beige' | 'muted'> = {
  PASS: 'sage',
  FAIL: 'rose',
  INCONCLUSIVE: 'beige',
  INVALID_RUN: 'beige',
  ERROR: 'rose',
};

const VERDICT_ICONS: Record<string, React.ReactNode> = {
  PASS: <ShieldCheck className="w-3.5 h-3.5" />,
  FAIL: <ShieldAlert className="w-3.5 h-3.5" />,
  INCONCLUSIVE: <ShieldQuestion className="w-3.5 h-3.5" />,
  INVALID_RUN: <AlertTriangle className="w-3.5 h-3.5" />,
  ERROR: <AlertTriangle className="w-3.5 h-3.5" />,
};

/** The backend's verdict, never derived in the frontend. */
export const VerdictBadge: React.FC<{ verdict: string | null | undefined; large?: boolean }> = ({
  verdict,
  large,
}) => {
  if (!verdict) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-[#30363D] bg-[#000000] text-[11px] font-medium text-[#B1BAC4]">
        <CircleDot className="w-3.5 h-3.5" /> No verdict yet
      </span>
    );
  }
  const tone = VERDICT_TONES[verdict] ?? 'muted';
  const classes: Record<string, string> = {
    sage: 'bg-[#56D364]/15 text-[#56D364] border-[#56D364]/40',
    rose: 'bg-[#F85149]/15 text-[#FF7B72] border-[#F85149]/40',
    beige: 'bg-[#D29922]/15 text-[#E3B341] border-[#D29922]/40',
    muted: 'bg-[#B1BAC4]/12 text-[#4e5149] border-[#B1BAC4]/25',
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${
        large ? 'px-3 py-1.5 text-xs' : 'px-2.5 py-1 text-[11px]'
      } ${classes[tone]}`}
    >
      {VERDICT_ICONS[verdict] ?? null}
      {verdict.replace(/_/g, ' ')}
    </span>
  );
};

export const FaultStateBadge: React.FC<{ state: string }> = ({ state }) => {
  const tone =
    state === 'ACTIVE' || state === 'TRIGGERED'
      ? 'rose'
      : state === 'ARMED' || state === 'PREPARING'
        ? 'blue'
        : state === 'FAILED'
          ? 'rose'
          : state === 'SKIPPED'
            ? 'muted'
            : 'sage';
  return <Pill tone={tone}>{state}</Pill>;
};

/* --------------------------------------------------------------- lifecycle */

export const LifecycleProgress: React.FC<{ state: string }> = ({ state }) => {
  const terminated = TERMINAL_LIFECYCLE_STATES.includes(state) && state !== 'COMPLETED';
  const currentIndex = LIFECYCLE_STEPS.indexOf(state as (typeof LIFECYCLE_STEPS)[number]);
  return (
    <div className="space-y-1.5">
      {LIFECYCLE_STEPS.map((step, index) => {
        const done = currentIndex >= 0 ? index < currentIndex : state === 'COMPLETED';
        const current = step === state;
        return (
          <div
            key={step}
            className={`flex items-center gap-2 text-[11px] font-mono ${
              current
                ? terminated
                  ? 'text-[#FF7B72] font-semibold'
                  : 'text-[#F0F6FC] font-semibold'
                : done
                  ? 'text-[#C9D1D9]'
                  : 'text-[#a5a79f]'
            }`}
          >
            <span
              className={`w-4 h-4 rounded-full border flex items-center justify-center shrink-0 ${
                current
                  ? terminated
                    ? 'bg-[#F85149]/20 border-[#F85149]'
                    : 'bg-[#C9D1D9]/25 border-[#C9D1D9]'
                  : done
                    ? 'bg-[#C9D1D9]/15 border-[#C9D1D9]/50'
                    : 'border-[#30363D]'
              }`}
            >
              {done && <Check className="w-2.5 h-2.5" />}
              {current && <span className="w-1.5 h-1.5 rounded-full bg-current" />}
            </span>
            {step.replace(/_/g, ' ')}
          </div>
        );
      })}
      {terminated && (
        <div className="flex items-center gap-2 text-[11px] font-mono text-[#FF7B72] font-semibold pt-1">
          <span className="w-4 h-4 rounded-full border border-[#F85149] bg-[#F85149]/20 flex items-center justify-center shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
          </span>
          {state}
        </div>
      )}
    </div>
  );
};
