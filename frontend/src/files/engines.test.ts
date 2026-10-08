import { describe, expect, it } from 'vitest';
import { META, SETTINGS, SETTINGS_WITH_GEMINI, settingsWith } from '../test/fixtures';
import { choiceFor, chosenEngine, engineCaption, initialChoice, isAvailable, shortModelLabel, switchMode } from './engines';

describe('engineCaption', () => {
  it('names the engine and model, and stays silent for Google free', () => {
    expect(engineCaption({ engine: 'google_free', model: null }, META)).toBeNull();
    expect(engineCaption({ engine: 'google_cloud', model: null }, META)).toBe('Google Cloud Translation');
    // Chú thích dùng nhãn ngắn: phần trước " — " (lời khuyên "rẻ, nhanh…" chỉ có ích ở ô chọn model).
    expect(engineCaption({ engine: 'gemini', model: 'gemini-3.5-flash-lite' }, META)).toBe('Gemini 3.5 Flash-Lite');
    expect(engineCaption({ engine: 'gemini', model: 'gemini-3.5-flash' }, META)).toBe('Gemini 3.5 Flash');
    expect(engineCaption({ engine: 'gemini', model: 'gemini-9-unknown' }, META)).toBe('gemini-9-unknown');
    expect(engineCaption({ engine: 'gemini', model: 'gemini-3.5-flash-lite' }, null)).toBe('gemini-3.5-flash-lite');
  });
});

describe('isAvailable', () => {
  it('treats an engine missing from settings.engines as unavailable', () => {
    expect(isAvailable(settingsWith({ engines: SETTINGS.engines.filter((engine) => engine.id !== 'gemini') }), 'gemini')).toBe(false);
  });
});

describe('initialChoice', () => {
  it('follows the saved default and falls back to plain when the default has no usable key', () => {
    expect(initialChoice(SETTINGS)).toEqual({ mode: 'plain', engine: 'google_free', model: 'gemini-3.5-flash-lite' });
    expect(initialChoice(SETTINGS_WITH_GEMINI)).toEqual({ mode: 'ai', engine: 'gemini', model: 'gemini-3.5-flash-lite' });
    // Mặc định gemini nhưng key không còn dùng được (available: false) → Dịch thuần; model vẫn giữ để ô chọn có giá trị.
    const rotated = settingsWith({ default_engine: 'gemini', default_model: 'gemini-3.8-flash' });
    expect(initialChoice(rotated)).toEqual({ mode: 'plain', engine: 'google_free', model: 'gemini-3.8-flash' });
    const unknownModel = settingsWith({ ...SETTINGS_WITH_GEMINI, default_model: 'gemini-9-gone' });
    expect(initialChoice(unknownModel)).toEqual({ mode: 'ai', engine: 'gemini', model: 'gemini-3.5-flash-lite' });
    expect(chosenEngine({ mode: 'ai', engine: 'gemini', model: 'gemini-3.8-flash' })).toEqual({ engine: 'gemini', model: 'gemini-3.8-flash' });
    expect(chosenEngine({ mode: 'plain', engine: 'google_cloud', model: 'gemini-3.8-flash' })).toEqual({ engine: 'google_cloud', model: null });
    // Phòng thủ: nếu `choice.engine` vẫn là 'gemini' trong khi mode là 'plain' (không nên xảy ra, nhưng
    // một lỗi UI đã từng để lọt), không bao giờ trả về engine AI cho một yêu cầu "plain".
    expect(chosenEngine({ mode: 'plain', engine: 'gemini', model: 'gemini-3.8-flash' })).toEqual({ engine: 'google_free', model: null });
  });
});

describe('shortModelLabel', () => {
  it('keeps the part before " — "', () => {
    expect(shortModelLabel('gemini-3.1-pro-preview', META.gemini_models)).toBe('Gemini 3.1 Pro (preview)');
    expect(shortModelLabel('gemini-9-unknown', META.gemini_models)).toBe('gemini-9-unknown');
  });
});

describe('switchMode', () => {
  const withCloud = settingsWith({
    ...SETTINGS_WITH_GEMINI,
    engines: SETTINGS.engines.map((engine) => ({ ...engine, available: true })),
  });

  it('picks a usable plain engine when leaving AI mode, never keeps gemini', () => {
    const ai = initialChoice(SETTINGS_WITH_GEMINI);
    expect(switchMode(SETTINGS_WITH_GEMINI, ai, 'plain')).toEqual({ mode: 'plain', engine: 'google_free', model: ai.model });
    expect(switchMode(withCloud, { mode: 'plain', engine: 'google_cloud', model: 'gemini-3.5-flash-lite' }, 'plain').engine)
      .toBe('google_cloud');
    // Engine thuần đang chọn không còn key → lùi về Google miễn phí.
    expect(switchMode(SETTINGS_WITH_GEMINI, { mode: 'plain', engine: 'google_cloud', model: 'x' }, 'plain').engine)
      .toBe('google_free');
  });

  it('enters AI mode with a model from the current list', () => {
    expect(switchMode(SETTINGS_WITH_GEMINI, { mode: 'plain', engine: 'google_free', model: 'gemini-9-gone' }, 'ai'))
      .toEqual({ mode: 'ai', engine: 'gemini', model: 'gemini-3.5-flash-lite' });
  });
});

describe('choiceFor', () => {
  it("preselects AI with the file's model while the key still offers it, otherwise the default model", () => {
    expect(choiceFor(SETTINGS_WITH_GEMINI, 'gemini', 'gemini-3.8-flash')).toEqual({ mode: 'ai', engine: 'gemini', model: 'gemini-3.8-flash' });
    // 3.1 Pro không có trong danh sách của key (SETTINGS_WITH_GEMINI chỉ có Flash-Lite + 3.8 Flash) → model mặc định
    expect(choiceFor(SETTINGS_WITH_GEMINI, 'gemini', 'gemini-3.1-pro-preview'))
      .toEqual({ mode: 'ai', engine: 'gemini', model: 'gemini-3.5-flash-lite' });
  });

  it("preselects plain mode with the file's own plain engine", () => {
    const withCloud = settingsWith({ engines: SETTINGS.engines.map((engine) => ({ ...engine, available: true })) });
    expect(choiceFor(withCloud, 'google_cloud', null)).toEqual({ mode: 'plain', engine: 'google_cloud', model: 'gemini-3.5-flash-lite' });
    expect(choiceFor(SETTINGS, 'google_free', null)).toEqual({ mode: 'plain', engine: 'google_free', model: 'gemini-3.5-flash-lite' });
  });

  it("falls back to Google free when the file's engine has no usable key any more", () => {
    // không chọn sẵn một ô bị khoá (key đã xoá); model giữ để chuyển sang AI sau này vẫn đúng chỗ
    expect(choiceFor(SETTINGS, 'gemini', 'gemini-3.8-flash')).toEqual({ mode: 'plain', engine: 'google_free', model: 'gemini-3.8-flash' });
    expect(choiceFor(SETTINGS, 'google_cloud', null).engine).toBe('google_free');
  });
});
