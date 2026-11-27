import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PEAK_HOLD_WINDOW_MS,
  computeRhythmicPulse,
  computeRmsFromTimeDomain,
  fillHologramWaveLoop,
  updatePerBarPeakHold,
  updateRollingPeakHistory,
  updateSpeechGate,
  type PeakSample,
} from './waveformMath';

test('computeRmsFromTimeDomain returns 0 for silent midpoint buffer', () => {
  const silent = new Uint8Array(64).fill(128);
  assert.equal(computeRmsFromTimeDomain(silent), 0);
});

test('computeRmsFromTimeDomain increases with waveform deviation', () => {
  const loud = new Uint8Array(64);
  for (let i = 0; i < loud.length; i += 1) {
    loud[i] = i % 2 === 0 ? 190 : 66;
  }
  const rms = computeRmsFromTimeDomain(loud);
  assert.ok(rms > 0.5 && rms <= 1);
});

test('updateSpeechGate holds speaking state across brief word pauses', () => {
  const active = updateSpeechGate({ speaking: false, lastVoiceMs: 0 }, 0.2, 1000);
  assert.equal(active.speaking, true);

  // Brief silence at 1350ms (within 700ms hold window) stays speaking
  const held = updateSpeechGate(active, 0.005, 1350, 0.035, 700);
  assert.equal(held.speaking, true);

  // Past hold window at 1800ms closes gate
  const closed = updateSpeechGate(held, 0.005, 1800, 0.035, 700);
  assert.equal(closed.speaking, false);
});

test('fillHologramWaveLoop closes the 3D loop seamlessly', () => {
  const count = 32;
  const out = new Float32Array((count + 1) * 3);
  const samples = new Uint8Array(64).fill(148);
  fillHologramWaveLoop(out, count, 1.2, samples, 1.5, 0.6);

  assert.equal(out[0], out[count * 3]);
  assert.equal(out[1], out[count * 3 + 1]);
  assert.equal(out[2], out[count * 3 + 2]);
});

test('computeRhythmicPulse scales depth and opacity with amplitude', () => {
  const peakPhase = Math.PI / 2;
  const lowPulse = computeRhythmicPulse(0.1, peakPhase, false);
  const highPulse = computeRhythmicPulse(0.9, peakPhase, false);

  assert.ok(highPulse.scale > lowPulse.scale);
  assert.ok(highPulse.opacity >= lowPulse.opacity);
  assert.ok(highPulse.waveIntensity > lowPulse.waveIntensity);

  const reduced = computeRhythmicPulse(0.8, peakPhase, true);
  assert.equal(reduced.lift, 0);
});

test('updateRollingPeakHistory holds max frequency amplitude for 2 seconds then prunes expired peaks', () => {
  let samples: PeakSample[] = [];
  let res = updateRollingPeakHistory(samples, 0.86, 1000, PEAK_HOLD_WINDOW_MS);
  samples = res.samples;
  assert.equal(res.peakAmplitude, 0.86);

  // Within 2s window (at 2400ms), lower live amplitude still holds 0.86 peak
  res = updateRollingPeakHistory(samples, 0.24, 2400, PEAK_HOLD_WINDOW_MS);
  samples = res.samples;
  assert.equal(res.peakAmplitude, 0.86);

  // Past 2s window (at 3500ms), 1000ms peak is pruned and peak reflects newer samples
  res = updateRollingPeakHistory(samples, 0.32, 3500, PEAK_HOLD_WINDOW_MS);
  assert.equal(res.peakAmplitude, 0.32);
  assert.ok(res.peakDb < 0 && res.peakDb > -20);
});

test('updatePerBarPeakHold holds 3D spectrum bar caps for 2 seconds before decaying', () => {
  const peakVals = new Float32Array(4);
  const peakTimes = new Float64Array(4);

  const latched = updatePerBarPeakHold(peakVals, peakTimes, 0, 1.4, 1000, 0.016, 2000);
  assert.ok(Math.abs(latched - 1.4) < 1e-6);

  // Still inside 2s window at 2500ms -> holds 1.4 (within float32 precision)
  const held = updatePerBarPeakHold(peakVals, peakTimes, 0, 0.4, 2500, 0.016, 2000);
  assert.equal(held, latched);

  // Past 2s window at 3200ms -> decays smoothly toward 0.4
  const decayed = updatePerBarPeakHold(peakVals, peakTimes, 0, 0.4, 3200, 0.2, 2000);
  assert.ok(decayed < held && decayed >= 0.4);
});

