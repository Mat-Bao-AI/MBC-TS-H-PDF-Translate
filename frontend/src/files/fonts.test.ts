import { describe, expect, it } from 'vitest';
import { t } from '../i18n/t';
import { META, fileItem } from '../test/fixtures';
import { fileCaption, fontLabel, fontOptions, fontUsedCaption, otherProfile, retranslateCaption } from './fonts';

describe('fonts', () => {
  it('labels the three profiles in display order', () => {
    expect(fontOptions()).toEqual({ auto: t('font.auto'), sans: t('font.sans'), serif: t('font.serif') });
    expect(Object.keys(fontOptions())).toEqual(['auto', 'sans', 'serif']);
    expect(fontLabel('comic')).toBe('comic');
  });

  it('captions the font actually used and nothing when it is unknown', () => {
    expect(fontUsedCaption('sans')).toBe(t('font.used.sans'));
    expect(fontUsedCaption('serif')).toBe(t('font.used.serif'));
    expect(fontUsedCaption(null)).toBeNull();
    expect(fontUsedCaption('comic')).toBeNull();
  });

  it('preselects the other profile for a rebuild', () => {
    expect(otherProfile('sans')).toBe('serif');
    expect(otherProfile('serif')).toBe('sans');
    expect(otherProfile(null)).toBe('sans');
  });

  it('builds the file caption from language, engine and font', () => {
    const base = t('file.translatedTo', { language: 'Tiếng Việt' });
    expect(fileCaption(fileItem(), 'Tiếng Việt', META)).toBe(base);
    expect(fileCaption(fileItem({ font_used: 'sans' }), 'Tiếng Việt', META)).toBe(`${base} · ${t('font.used.sans')}`);
    expect(fileCaption(fileItem({ engine: 'gemini', model: 'gemini-3.5-flash-lite', font_used: 'serif' }), 'Tiếng Việt', META))
      .toBe(`${base} · Gemini 3.5 Flash-Lite · ${t('font.used.serif')}`);
  });
  it('describes where a retranslate is going: language, model or engine, font', () => {
    expect(retranslateCaption({ language: 'en', engine: 'gemini', model: 'gemini-3.8-flash', font: 'serif' }, 'Tiếng Anh', META))
      .toBe(`Tiếng Anh · Gemini 3.8 Flash · ${t('font.serif')}`);
    // Khác dòng mô tả của tệp: Google miễn phí vẫn được gọi tên — người dùng cần biết lượt này chạy bằng gì.
    expect(retranslateCaption({ language: 'vi', engine: 'google_free', model: null, font: 'auto' }, 'Tiếng Việt', META))
      .toBe(`Tiếng Việt · Google miễn phí · ${t('font.auto')}`);
  });
});
