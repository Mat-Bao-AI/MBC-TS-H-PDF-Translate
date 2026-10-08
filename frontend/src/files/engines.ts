import type { FileItem, Meta } from '../api/files';
import type { EngineInfo, EngineMode, ModelInfo, SettingsInfo } from '../api/settings';

export type EngineChoice = { mode: EngineMode; engine: string; model: string };

export const engineLabel = (id: string, engines: EngineInfo[] | undefined) =>
  engines?.find((engine) => engine.id === id)?.label ?? id;

export const modelLabel = (id: string | null, models: ModelInfo[] | undefined) =>
  (id && models?.find((model) => model.id === id)?.label) || id || '';

/** Nhãn ngắn: phần trước " — " ("Gemini 3.5 Flash-Lite — rẻ, nhanh (khuyến nghị)" → "Gemini 3.5 Flash-Lite"). */
export const shortModelLabel = (id: string | null, models: ModelInfo[] | undefined) =>
  modelLabel(id, models).split(' — ')[0];

/** "Gemini 3.5 Flash-Lite" / "Google Cloud Translation"; null với Google miễn phí (không thêm gì). */
export function engineCaption(item: Pick<FileItem, 'engine' | 'model'>, meta: Meta | null): string | null {
  if (item.engine === 'google_free') return null;
  if (item.engine === 'gemini') return shortModelLabel(item.model, meta?.gemini_models) || engineLabel(item.engine, meta?.engines);
  return engineLabel(item.engine, meta?.engines);
}

export const isAvailable = (settings: SettingsInfo, engineId: string) =>
  settings.engines.find((engine) => engine.id === engineId)?.available === true;

/**
 * Model hợp lệ trong danh mục hiện tại: giữ `candidate` nếu còn trong `settings.gemini_models`;
 * nếu không (bị bỏ khỏi danh mục, hoặc chưa chọn gì) thì lùi về mặc định đã lưu (nếu còn hợp lệ)
 * rồi tới model đầu tiên. Dùng cho cả lựa chọn ban đầu lẫn khi chuyển từ Dịch thuần sang Dịch AI.
 */
export function resolveModel(settings: SettingsInfo, candidate?: string | null): string {
  const models = settings.gemini_models;
  if (candidate && models.some((m) => m.id === candidate)) return candidate;
  return settings.default_model && models.some((m) => m.id === settings.default_model)
    ? settings.default_model
    : models[0]?.id ?? '';
}

/** Lựa chọn ban đầu theo mặc định đã lưu; mặc định trỏ tới engine không còn key → lùi về Dịch thuần · Google miễn phí. */
export function initialChoice(settings: SettingsInfo): EngineChoice {
  const model = resolveModel(settings);
  const info = settings.engines.find((engine) => engine.id === settings.default_engine);
  if (!info || info.available === false) return { mode: 'plain', engine: 'google_free', model };
  return info.mode === 'ai' ? { mode: 'ai', engine: 'gemini', model } : { mode: 'plain', engine: info.id, model };
}

/**
 * Lựa chọn chọn sẵn của hộp "Dịch lại" theo engine/model của chính tệp (spec 2026-10-05 §6): gemini → Dịch bằng AI +
 * model đó (không còn trong danh sách của key → model mặc định, như `resolveModel`); engine thuần → Dịch thuần + engine
 * đó. Engine của tệp không còn dùng được (key đã xoá) → Dịch thuần · Google miễn phí như `initialChoice`: không chọn sẵn
 * một ô bị khoá, không âm thầm gửi engine trả phí không có key.
 */
export function choiceFor(settings: SettingsInfo, engine: string, model: string | null): EngineChoice {
  const resolved = resolveModel(settings, model);
  const info = settings.engines.find((candidate) => candidate.id === engine);
  if (!info || info.available === false) return { mode: 'plain', engine: 'google_free', model: resolved };
  return info.mode === 'ai' ? { mode: 'ai', engine: 'gemini', model: resolved } : { mode: 'plain', engine: info.id, model: resolved };
}

/**
 * Đổi "Dịch thuần"/"Dịch bằng AI" (hộp thoại tải lên lẫn Cài đặt): engine phải khớp mode mới, không được
 * giữ engine cũ — đang ở AI ('gemini') mà bấm "Dịch thuần" thì phải về một engine thuần dùng được (engine
 * thuần đang chọn nếu còn key, không thì Google miễn phí), không âm thầm dùng key AI trả phí. `model` giữ
 * nguyên khi sang "Dịch thuần" để chuyển lại AI thì ô chọn model vẫn đúng chỗ cũ.
 */
export function switchMode(settings: SettingsInfo, choice: EngineChoice, mode: EngineMode): EngineChoice {
  if (mode === 'plain') {
    const current = settings.engines.find((engine) => engine.mode === 'plain' && engine.id === choice.engine);
    return { ...choice, mode, engine: current && current.available !== false ? current.id : 'google_free' };
  }
  return { ...choice, mode, engine: 'gemini', model: resolveModel(settings, choice.model) };
}

export const chosenEngine = (choice: EngineChoice): { engine: string; model: string | null } =>
  choice.mode === 'ai'
    ? { engine: 'gemini', model: choice.model }
    // Phòng thủ: `choice.engine` không bao giờ được là 'gemini' khi mode là 'plain' (engine AI duy nhất
    // là 'gemini') — nếu lọt tới đây (lỗi state ở UI), lùi về Google miễn phí thay vì âm thầm dùng key AI.
    : { engine: choice.engine === 'gemini' ? 'google_free' : choice.engine, model: null };

export const modelOptions = (models: ModelInfo[]): Record<string, string> =>
  Object.fromEntries(models.map((model) => [model.id, model.label]));
