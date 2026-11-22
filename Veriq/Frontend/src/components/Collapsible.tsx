import React, { useId, useState } from 'react';
import { ChevronDown, HelpCircle } from 'lucide-react';

/**
 * Progressive-disclosure panel used by observability views.
 *
 * The header is a real button with `aria-expanded` / `aria-controls`, and the
 * panel stays in the DOM (hidden) so assistive technology and find-in-page keep
 * a stable target.
 */
export const CollapsibleSection: React.FC<{
  title: string;
  description?: string;
  icon?: React.ReactNode;
  /** Always-visible summary shown next to the chevron (counts, state…). */
  meta?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}> = ({ title, description, icon, meta, defaultOpen = false, children }) => {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();

  return (
    <section className="rounded-xl border border-[#22272E] bg-[#0B0F14]">
      <h2>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls={panelId}
          className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left transition-colors hover:bg-[#12161C] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#58A6FF]/60"
        >
          <span className="flex min-w-0 items-center gap-2.5">
            {icon}
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-[#F0F6FC]">{title}</span>
              {description && (
                <span className="mt-0.5 block text-[11px] leading-relaxed text-[#8B949E]">
                  {description}
                </span>
              )}
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-2.5">
            {meta}
            <ChevronDown
              aria-hidden="true"
              className={`h-4 w-4 text-[#8B949E] transition-transform ${open ? 'rotate-180' : ''}`}
            />
          </span>
        </button>
      </h2>
      <div
        id={panelId}
        hidden={!open}
        className="border-t border-[#1C2128] px-4 py-3.5"
      >
        {children}
      </div>
    </section>
  );
};

/** Small `(?)` affordance that replaces explanatory body copy. */
export const InfoHint: React.FC<{ text: string; label?: string }> = ({
  text,
  label = 'Details',
}) => (
  <span
    role="img"
    tabIndex={0}
    aria-label={`${label}: ${text}`}
    title={text}
    className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full text-[#8B949E] transition-colors hover:text-[#F0F6FC] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#58A6FF]/60"
  >
    <HelpCircle aria-hidden="true" className="h-3.5 w-3.5" />
  </span>
);
