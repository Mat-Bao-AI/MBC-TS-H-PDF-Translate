import { expect, it } from 'vitest';
import { DataGrid } from '@codecademy/gamut/dist/DataList/DataGrid';

// FileTable dùng đường dẫn sâu vì Gamut không xuất DataGrid ở gốc: nâng Gamut đổi chỗ thì test này đỏ rõ ràng.
it('Gamut still ships DataGrid at the deep import path used by FileTable', () => {
  expect(typeof DataGrid).toBe('function');
});
