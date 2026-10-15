import type { MouseEvent } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { followLink } from './RouterAnchor';

function click(init: Partial<MouseEvent> = {}) {
  const preventDefault = vi.fn();
  const navigate = vi.fn();
  followLink({ defaultPrevented: false, button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, preventDefault, ...init } as unknown as MouseEvent, navigate, '/x');
  return { preventDefault, navigate };
}

describe('followLink', () => {
  it('navigates client-side on a plain left click', () => {
    const { preventDefault, navigate } = click();
    expect(preventDefault).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith('/x');
  });

  it.each([
    ['middle button', { button: 1 }], ['ctrl', { ctrlKey: true }], ['meta', { metaKey: true }],
    ['shift', { shiftKey: true }], ['alt', { altKey: true }], ['already handled', { defaultPrevented: true }],
  ])('leaves a %s click to the browser', (_name, init) => {
    const { preventDefault, navigate } = click(init);
    expect(preventDefault).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });
});
