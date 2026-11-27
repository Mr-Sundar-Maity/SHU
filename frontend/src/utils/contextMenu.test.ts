import test from 'node:test';
import assert from 'node:assert/strict';
import { clampContextMenuPosition } from './contextMenu';

test('clampContextMenuPosition keeps menu inside viewport edges', () => {
  const inside = clampContextMenuPosition(400, 300, 230, 210, 1440, 900);
  assert.deepEqual(inside, { left: 400, top: 300 });

  const clampedCorner = clampContextMenuPosition(1420, 880, 230, 210, 1440, 900, 12);
  assert.deepEqual(clampedCorner, { left: 1198, top: 678 });

  const clampedMin = clampContextMenuPosition(-10, 2, 230, 210, 390, 844, 12);
  assert.deepEqual(clampedMin, { left: 12, top: 12 });
});
