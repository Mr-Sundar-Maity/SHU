import test from 'node:test';
import assert from 'node:assert/strict';
import {
  HOLO_KEYPAD_GRID_KEYS,
  HOLO_KEYPAD_PREFIX_KEYS,
  applyKeypadInput,
  backspaceKeypadInput,
  formatKeypadSubmission,
} from './holoKeypad';

test('holoKeypad defines a complete 12-key 3D grid and 3 prefix keys', () => {
  assert.equal(HOLO_KEYPAD_GRID_KEYS.length, 12);
  assert.equal(HOLO_KEYPAD_PREFIX_KEYS.length, 3);
  const digits = HOLO_KEYPAD_GRID_KEYS.filter((k) => k.kind === 'digit').map((k) => k.value);
  assert.deepEqual(digits, ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']);
});

test('applyKeypadInput, backspaceKeypadInput, and formatKeypadSubmission handle numeric task IDs', () => {
  let buf = '';
  buf = applyKeypadInput(buf, '3');
  buf = applyKeypadInput(buf, '0');
  buf = applyKeypadInput(buf, '1');
  assert.equal(buf, '301');
  assert.equal(formatKeypadSubmission(buf), 'Task #301');

  buf = backspaceKeypadInput(buf);
  assert.equal(buf, '30');

  const prefixed = applyKeypadInput('', 'wf-301');
  assert.equal(formatKeypadSubmission(prefixed), 'wf-301');
  assert.equal(formatKeypadSubmission('   '), '');
});
