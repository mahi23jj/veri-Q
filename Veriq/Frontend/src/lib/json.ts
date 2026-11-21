/** JSON-editor helpers used by reliability planning forms. */

export function parseJsonObject(text: string): { value: Record<string, unknown> | null; error: string | null } {
  const trimmed = text.trim();
  if (!trimmed) return { value: {}, error: null };
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { value: null, error: 'Expected a JSON object.' };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch (cause) {
    return {
      value: null,
      error: cause instanceof Error ? `Invalid JSON: ${cause.message}` : 'Invalid JSON.',
    };
  }
}

export function parseJsonArray(text: string): { value: unknown[] | null; error: string | null } {
  const trimmed = text.trim();
  if (!trimmed) return { value: [], error: null };
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) return { value: null, error: 'Expected a JSON array.' };
    return { value: parsed, error: null };
  } catch (cause) {
    return {
      value: null,
      error: cause instanceof Error ? `Invalid JSON: ${cause.message}` : 'Invalid JSON.',
    };
  }
}

export function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
