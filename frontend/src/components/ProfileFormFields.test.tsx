import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GamutProvider, theme } from '@codecademy/gamut-styles';
import { describe, expect, it, vi } from 'vitest';
import { STYLE_DEFAULTS } from '../files/profiles';
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
});
