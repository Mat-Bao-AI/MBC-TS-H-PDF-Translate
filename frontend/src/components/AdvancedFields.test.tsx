import { describe, expect, it } from 'vitest';
import type { StyleField } from '../api/settings';
import { styleOf } from '../files/profiles';
import { MY_PROFILE, PRESETS, SEEDED_PROFILES, settingsWith, snapshot } from '../test/fixtures';
import { initialAdvanced, toAdvancedChoice } from './AdvancedFields';

describe('AdvancedFields helpers', () => {
  const settings = settingsWith({ advance_mode: true, default_profile: 'preset:quick' });

  it('starts from the default profile on upload; a profile alone is worth sending, nothing at all is not', () => {
    const state = initialAdvanced(settings);
    expect(state.profile).toBe('preset:quick');
    expect(state.custom).toBe(false);
    expect(toAdvancedChoice(state, settings)).toEqual({ profile: 'preset:quick', style: null, context: null });
    expect(toAdvancedChoice(initialAdvanced(settingsWith({ advance_mode: true })), settings)).toBeNull();
  });

  it('starts a basic file (no snapshot) at no profile, never at the default profile (spec §8)', () => {
    const state = initialAdvanced(settings, null);
    expect(state.profile).toBeNull();
    expect(state.custom).toBe(false);
    expect(toAdvancedChoice(state, settings)).toBeNull();
  });

  it('with a profile only the fields that differ travel; without one only the touched fields; nothing while customize is off', () => {
    const withProfile = initialAdvanced(settings);
    const changed = { ...withProfile, custom: true, style: { ...withProfile.style, tone: 'simple', terms: withProfile.style.terms }, touched: new Set<StyleField>(['tone', 'terms']) };
    expect(toAdvancedChoice(changed, settings)).toEqual({ profile: 'preset:quick', style: { tone: 'simple' }, context: null });
    const noProfile = initialAdvanced(settingsWith({ advance_mode: true }));
    const touched = { ...noProfile, custom: true, style: { ...noProfile.style, tone: 'simple' }, touched: new Set<StyleField>(['tone']) };
    expect(toAdvancedChoice(touched, settings)).toEqual({ profile: null, style: { tone: 'simple' }, context: null });
    expect(toAdvancedChoice({ ...touched, custom: false }, settings)).toBeNull();
    expect(toAdvancedChoice({ ...touched, custom: false, context: '  Ngữ cảnh  ' }, settings)).toEqual({ profile: null, style: null, context: 'Ngữ cảnh' });
  });

  it('rebuilds the state from a snapshot, and turns a vanished profile into overrides of every field', () => {
    const kept = initialAdvanced(settings, snapshot({ style: { ...snapshot().style, tone: 'friendly' }, overrides: ['tone'], document_context: 'API' }));
    expect(kept.profile).toBe('preset:technical');
    expect(kept.custom).toBe(true);
    expect([...kept.touched]).toEqual(['tone']);
    expect(kept.context).toBe('API');
    expect(toAdvancedChoice(kept, settings)).toEqual({ profile: 'preset:technical', style: { tone: 'friendly' }, context: 'API' });
    const gone = initialAdvanced(settings, snapshot({ profile: { id: 'p00000000009', name: 'Đã xoá', kind: 'custom' } }));
    expect(gone.profile).toBeNull();
    expect(gone.custom).toBe(true);
    expect(toAdvancedChoice(gone, settings)).toEqual({ profile: null, style: snapshot().style, context: null });
    expect(initialAdvanced(settings, snapshot({ profile: null, style: null, overrides: [], document_context: 'Chỉ ngữ cảnh' })).custom).toBe(false);
    expect(initialAdvanced(settings, snapshot()).profile).toBe('preset:technical'); // không theo hồ sơ mặc định khi có snapshot
  });

  it('prefills a still-existing profile with its CURRENT values plus only the snapshot overrides', () => {
    // Hồ sơ riêng đã sửa sau lượt dịch: snapshot còn mang giá trị cũ của nó.
    const edited = settingsWith({ advance_mode: true, profiles: [...PRESETS, MY_PROFILE] });
    const before = { ...styleOf(MY_PROFILE), fidelity: 'literal', audience: 'expert', custom_instructions: 'Bản cũ.' };
    const profile = { id: MY_PROFILE.id, name: MY_PROFILE.name, kind: 'custom' as const };
    const plain = initialAdvanced(edited, snapshot({ profile, style: before, overrides: [] }));
    expect(plain.custom).toBe(false);
    expect(plain.style).toEqual(styleOf(MY_PROFILE));
    expect(toAdvancedChoice(plain, edited)).toEqual({ profile: MY_PROFILE.id, style: null, context: null });
    expect(toAdvancedChoice({ ...plain, custom: true }, edited)).toEqual({ profile: MY_PROFILE.id, style: null, context: null });
    const tone = initialAdvanced(edited, snapshot({ profile, style: { ...before, tone: 'simple' }, overrides: ['tone'] }));
    expect(tone.custom).toBe(true);
    expect([...tone.touched]).toEqual(['tone']);
    expect(tone.style).toEqual({ ...styleOf(MY_PROFILE), tone: 'simple' });
    expect(toAdvancedChoice(tone, edited)).toEqual({ profile: MY_PROFILE.id, style: { tone: 'simple' }, context: null });
  });

  it('keeps the preset style when the user starts customising', () => {
    const state = initialAdvanced(settings);
    expect(state.style.terms).toBe(PRESETS[0].terms);
  });

  it('maps a pre-1b snapshot reference preset:<slug> onto the seeded row and its overrides, not "no profile"', () => {
    const seeded = settingsWith({ advance_mode: true, profiles: SEEDED_PROFILES });
    const row = SEEDED_PROFILES.find((profile) => profile.preset_slug === 'technical')!;
    const state = initialAdvanced(seeded, snapshot({ style: { ...snapshot().style, tone: 'friendly' }, overrides: ['tone'] }));
    expect(state.profile).toBe(row.id);
    expect(state.custom).toBe(true);
    expect([...state.touched]).toEqual(['tone']);
    expect(state.style).toEqual({ ...styleOf(row), tone: 'friendly' });
    expect(toAdvancedChoice(state, seeded)).toEqual({ profile: row.id, style: { tone: 'friendly' }, context: null });
  });
});
