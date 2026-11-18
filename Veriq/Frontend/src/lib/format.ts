/** Date, duration and status formatting helpers shared by dashboard pages. */

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'medium',
});

const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parse(value);
  return date ? dateTimeFormatter.format(date) : '—';
}

export function formatDate(value: string | null | undefined): string {
  const date = parse(value);
  return date ? dateFormatter.format(date) : '—';
}

export function formatTime(value: string | null | undefined): string {
  const date = parse(value);
  return date ? timeFormatter.format(date) : '—';
}

/** Compact relative time, e.g. "just now", "4 min ago", "2 days ago". */
export function formatRelative(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return 'Never';

  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const suffix = seconds < 0 ? 'ago' : 'from now';

  if (abs < 10) return 'just now';
  if (abs < 60) return `${abs}s ${suffix}`;
  if (abs < 3600) return `${Math.round(abs / 60)} min ${suffix}`;
  if (abs < 86400) return `${Math.round(abs / 3600)} hr ${suffix}`;
  if (abs < 2592000) return `${Math.round(abs / 86400)} day${abs >= 172800 ? 's' : ''} ${suffix}`;
  return formatDate(date.toISOString());
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat().format(value);
}

/** Shorten a UUID for dense table cells while keeping it recognizable. */
export function shortId(value: string | null | undefined, length = 8): string {
  if (!value) return '—';
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

export function stringifyPayload(payload: Record<string, unknown> | null | undefined): string {
  if (!payload) return '';
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}
