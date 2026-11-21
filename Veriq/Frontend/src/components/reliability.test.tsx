import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { CompatibilityBadge, LifecycleProgress, VerdictBadge } from './reliability';

describe('reliability display', () => {
  it('renders the backend verdict without deriving a new one', () => {
    expect(renderToStaticMarkup(<VerdictBadge verdict="PASS" />)).toContain('PASS');
    expect(renderToStaticMarkup(<VerdictBadge verdict="INVALID_RUN" />)).toContain('INVALID RUN');
    expect(renderToStaticMarkup(<VerdictBadge verdict={null} />)).toContain('No verdict yet');
  });

  it('renders compatibility states readable', () => {
    expect(renderToStaticMarkup(<CompatibilityBadge status="COMPATIBLE" />)).toContain('COMPATIBLE');
    expect(
      renderToStaticMarkup(<CompatibilityBadge status="NEEDS_CONFIGURATION" />),
    ).toContain('NEEDS CONFIGURATION');
  });

  it('marks the current lifecycle stage and keeps terminal states distinct', () => {
    const injecting = renderToStaticMarkup(<LifecycleProgress state="INJECTING" />);
    expect(injecting).toContain('INJECTING');
    expect(injecting).toContain('OBSERVING RECOVERY');

    const failed = renderToStaticMarkup(<LifecycleProgress state="FAILED" />);
    expect(failed).toContain('FAILED');
  });
});
