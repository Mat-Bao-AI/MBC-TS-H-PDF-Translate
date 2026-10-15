import { describe, expect, it } from 'vitest';
import { t } from '../i18n/t';
import { PRESETS, SEEDED_PROFILES } from '../test/fixtures';
import {
  ENUM_FIELDS, NAME_MAX, STYLE_DEFAULTS, STYLE_OPTIONS, cloneName, findProfile, isFromPreset, overridesAgainst, pickFields, profileOptions, styleOf, valueLabel,
} from './profiles';

describe('files/profiles', () => {
  it('finds a seeded profile through its old preset reference, and nothing for a reference that matches no profile', () => {
    expect(findProfile(SEEDED_PROFILES, 'preset:technical')?.name).toBe('Tài liệu kỹ thuật');
    expect(findProfile(SEEDED_PROFILES, SEEDED_PROFILES[0].id)?.preset_slug).toBe('quick');
    expect(findProfile(PRESETS, 'preset:technical')?.id).toBe('preset:technical');
    expect(findProfile(SEEDED_PROFILES, 'preset:nope')).toBeNull();
    expect(findProfile(SEEDED_PROFILES, 'p00000000009')).toBeNull();
    expect(findProfile(SEEDED_PROFILES, null)).toBeNull();
    expect(isFromPreset(SEEDED_PROFILES[0])).toBe(true);
    expect(isFromPreset(PRESETS[0])).toBe(false);
  });

  it('lists "no profile" first, then every profile with a (Mẫu) suffix for presets', () => {
    const options = profileOptions(PRESETS);
    expect(Object.keys(options)[0]).toBe('');
    expect(options['']).toBe(t('profiles.none'));
    expect(options['preset:technical']).toBe(`Tài liệu kỹ thuật (${t('profiles.preset')})`);
  });

  it('sends only the fields that differ from the profile, or only the touched ones without a profile', () => {
    const base = styleOf(PRESETS[2]);
    expect(overridesAgainst(base, { ...base, tone: 'friendly', terms: 'keep' })).toEqual({ tone: 'friendly' });
    expect(overridesAgainst(base, base)).toEqual({});
    expect(pickFields({ ...STYLE_DEFAULTS, tone: 'simple' }, ['tone'])).toEqual({ tone: 'simple' });
  });

  it('names a copy "<name> (bản sao)" within the 60-character limit by shortening the source name, never the suffix', () => {
    const suffix = t('profiles.cloneName', { name: '' });
    expect(cloneName('Hợp đồng')).toBe(t('profiles.cloneName', { name: 'Hợp đồng' }));
    const long = cloneName('A'.repeat(NAME_MAX));
    expect([...long]).toHaveLength(NAME_MAX);
    expect(long.endsWith(suffix)).toBe(true);
    expect(cloneName(`${'B'.repeat(NAME_MAX - suffix.length - 1)} C`)).toBe(t('profiles.cloneName', { name: 'B'.repeat(NAME_MAX - suffix.length - 1) }));
    const emoji = cloneName('😀'.repeat(NAME_MAX)); // không cắt đôi một cặp surrogate
    expect([...emoji]).toHaveLength(NAME_MAX);
    expect(emoji).not.toMatch(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/);
  });

  it('labels every option of every field in Vietnamese', () => {
    for (const field of ENUM_FIELDS) {
      for (const value of STYLE_OPTIONS[field]) expect(valueLabel(field, value)).not.toBe(value);
    }
  });
});
