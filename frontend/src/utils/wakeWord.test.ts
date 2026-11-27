import test from 'node:test';
import assert from 'node:assert/strict';
import { detectAcousticWakeBurst, detectWakeWordPattern } from './wakeWord';

test('detectWakeWordPattern detects standalone wake phrase and trailing commands', () => {
  const onlyWake = detectWakeWordPattern('hey shu');
  assert.equal(onlyWake.matched, true);
  assert.equal(onlyWake.wakePhrase, 'Hey SHU');
  assert.equal(onlyWake.trailingCommand, '');

  const withCmd = detectWakeWordPattern('Okay Shu, remind me to stretch in 10 minutes');
  assert.equal(withCmd.matched, true);
  assert.equal(withCmd.wakePhrase, 'Okay SHU');
  assert.equal(withCmd.trailingCommand, 'remind me to stretch in 10 minutes');

  const nonWake = detectWakeWordPattern('check my scheduled reminders');
  assert.equal(nonWake.matched, false);
  assert.equal(nonWake.wakePhrase, null);
});

test('detectAcousticWakeBurst triggers once on vocal onset after quiet baseline and respects cooldown', () => {
  let state = { sawQuietBaseline: false, lastTriggeredMs: 0 };

  const baseline = detectAcousticWakeBurst(0.02, state, 1000, 5000);
  assert.equal(baseline.triggered, false);
  state = baseline.nextState;
  assert.equal(state.sawQuietBaseline, true);

  const onset = detectAcousticWakeBurst(0.24, state, 1300, 5000);
  assert.equal(onset.triggered, true);
  state = onset.nextState;

  // Immediate subsequent loud frame does not re-trigger during cooldown
  const repeat = detectAcousticWakeBurst(0.28, state, 2000, 5000);
  assert.equal(repeat.triggered, false);

  // After cooldown + quiet baseline, triggers again cleanly
  state = detectAcousticWakeBurst(0.01, state, 6200, 5000).nextState;
  const secondOnset = detectAcousticWakeBurst(0.22, state, 6500, 5000);
  assert.equal(secondOnset.triggered, true);
});
