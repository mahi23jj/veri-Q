import { describe, expect, it } from 'vitest';
import { parseJsonArray, parseJsonObject, prettyJson } from './json';

describe('parseJsonObject', () => {
  it('accepts an object and treats blank input as an empty object', () => {
    expect(parseJsonObject('{"timeout_ms": 250}')).toEqual({
      value: { timeout_ms: 250 },
      error: null,
    });
    expect(parseJsonObject('   ')).toEqual({ value: {}, error: null });
  });

  it('rejects arrays and scalars because the backend expects an object', () => {
    expect(parseJsonObject('[1,2]').error).toMatch(/Expected a JSON object/);
    expect(parseJsonObject('42').error).toMatch(/Expected a JSON object/);
  });

  it('returns a parse error instead of throwing', () => {
    expect(parseJsonObject('{ nope').error).toMatch(/Invalid JSON/);
  });
});

describe('parseJsonArray', () => {
  it('accepts arrays, treats blanks as empty and rejects objects', () => {
    expect(parseJsonArray('[{"id":"a"}]')).toEqual({ value: [{ id: 'a' }], error: null });
    expect(parseJsonArray('')).toEqual({ value: [], error: null });
    expect(parseJsonArray('{"id":"a"}').error).toMatch(/Expected a JSON array/);
  });
});

describe('prettyJson', () => {
  it('pretty prints objects and blanks null values', () => {
    expect(prettyJson({ a: 1 })).toBe('{\n  "a": 1\n}');
    expect(prettyJson(null)).toBe('');
    expect(prettyJson(undefined)).toBe('');
  });
});
