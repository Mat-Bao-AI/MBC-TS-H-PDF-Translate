import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GamutProvider, theme } from '@codecademy/gamut-styles';
import { describe, expect, it, vi } from 'vitest';
import { ENUM_FIELDS, STYLE_DEFAULTS, fieldLabel } from '../files/profiles';
import { t } from '../i18n/t';
import { ProfileFormFields } from './ProfileFormFields';

describe('ProfileFormFields', () => {
  it('renders the name, the eight selects and the counted free text, reporting every change to the parent', async () => {
    const onNameChange = vi.fn();
    const onStyleChange = vi.fn();
    const style = { ...STYLE_DEFAULTS, custom_instructions: 'ab' };
    render(
      <GamutProvider theme={theme}>
        <ProfileFormFields idPrefix="x" name="A" style={style} onNameChange={onNameChange} onStyleChange={onStyleChange} />
      </GamutProvider>,
    );
    const user = userEvent.setup();
    expect(screen.getByLabelText(t('profiles.form.name'))).toHaveValue('A');
    expect(screen.getByLabelText(t('profiles.field.terms'))).toHaveValue('translate');
    expect(screen.getByText(t('profiles.form.counter', { n: 2, max: 1000 }))).toBeInTheDocument();
    await user.type(screen.getByLabelText(t('profiles.form.name')), 'B');
    expect(onNameChange).toHaveBeenLastCalledWith('AB');
    await user.selectOptions(screen.getByLabelText(t('profiles.field.tone')), 'friendly');
    expect(onStyleChange).toHaveBeenLastCalledWith({ ...style, tone: 'friendly' });
    await user.type(screen.getByLabelText(t('profiles.field.custom_instructions')), 'c');
    expect(onStyleChange).toHaveBeenLastCalledWith({ ...style, custom_instructions: 'abc' });
  });

  it('packs the fields tightly: no group keeps the default loose margin or padding below it', () => {
    const { container } = render(
      <GamutProvider theme={theme}>
        <ProfileFormFields idPrefix="x" name="A" style={STYLE_DEFAULTS} onNameChange={vi.fn()} onStyleChange={vi.fn()} />
      </GamutProvider>,
    );
    const labels = [t('profiles.form.name'), ...ENUM_FIELDS.map(fieldLabel), fieldLabel('custom_instructions')];
    expect(labels).toHaveLength(10);
    for (const label of labels) {
      for (let el: HTMLElement | null = screen.getByLabelText(label); el && el !== container; el = el.parentElement) {
        const style = getComputedStyle(el);
        expect(style.marginBottom, `${label}: margin-bottom`).not.toBe('24px'); // FormGroup mặc định "loose"
        expect(style.paddingBottom, `${label}: padding-bottom`).not.toBe('8px');
      }
    }
  });
});
