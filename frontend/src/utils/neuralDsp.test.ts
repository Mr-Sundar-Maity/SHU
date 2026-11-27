import test from 'node:test';
import assert from 'node:assert/strict';
import {
  computeNeuralDspSnapshot,
  computeWaveTracePoints,
  extractShortLocale,
  extractShortProvider,
  updatePeakHoldBands,
} from './neuralDsp';

test('extractShortProvider and extractShortLocale parse settings labels concisely', () => {
  assert.equal(extractShortProvider('Local Ollama · qwen2.5:14b'), 'qwen2.5:14b');
  assert.equal(extractShortLocale('English (en-US)'), 'en-US');
  assert.equal(extractShortLocale('Bengali (bn-IN)'), 'bn-IN');
});

test('updatePeakHoldBands preserves peaks above decaying floor', () => {
  const initial = updatePeakHoldBands([0.8, 0.2, 0.6], [0.5, 0.5, 0.62]);
  assert.equal(initial[0], 0.8);
  assert.ok(initial[1] > 0.4 && initial[1] < 0.5);
  assert.equal(initial[2], 0.6);
});

test('computeNeuralDspSnapshot derives accurate pipeline stages and acoustic metrics', () => {
  const snap = computeNeuralDspSnapshot({
    assistantState: 'thinking',
    isListening: true,
    isMuted: false,
    isUserSpeaking: true,
    quietMode: false,
    audioLevel: 0.45,
    sampleRateHz: 48000,
    fftSize: 256,
    bridgeStatus: 'connected',
    provider: 'Local Ollama · qwen2.5:14b',
    voiceLanguage: 'English (en-US)',
    phase: 1.2,
  });

  assert.equal(snap.sampleRateKhz, '48.0kHz');
  assert.equal(snap.fftBins, 128);
  assert.equal(snap.rmsPct, 45);
  assert.equal(snap.providerShort, 'qwen2.5:14b');
  assert.equal(snap.localeShort, 'en-US');
  assert.equal(snap.pipelineMode, 'Synthesizing');
  assert.equal(snap.stages.find((s) => s.id === 'mic')?.stateLabel, 'Hot');
  assert.equal(snap.stages.find((s) => s.id === 'vad')?.stateLabel, 'Speech');
  assert.equal(snap.stages.find((s) => s.id === 'llm')?.stateLabel, 'Infer');
  assert.equal(snap.stages.find((s) => s.id === 'tts')?.stateLabel, 'Standby');
});

test('computeNeuralDspSnapshot reflects muted, quiet, and stopped states', () => {
  const snap = computeNeuralDspSnapshot({
    assistantState: 'stopped',
    isListening: false,
    isMuted: true,
    isUserSpeaking: false,
    quietMode: true,
    audioLevel: 0,
    bridgeStatus: 'disconnected',
    provider: 'Python Bridge Custom Runtime',
    voiceLanguage: 'Hindi (hi-IN)',
    phase: 0,
  });

  assert.equal(snap.latencyMs, 0);
  assert.equal(snap.pipelineMode, 'Halted');
  assert.equal(snap.stages.find((s) => s.id === 'mic')?.status, 'muted');
  assert.equal(snap.stages.find((s) => s.id === 'vad')?.status, 'halted');
  assert.equal(snap.stages.find((s) => s.id === 'llm')?.status, 'halted');
  assert.equal(snap.stages.find((s) => s.id === 'tts')?.stateLabel, 'Quiet');
});

test('computeWaveTracePoints returns valid SVG paths', () => {
  const trace = computeWaveTracePoints(0.8, 0.5, 'listening', true);
  assert.ok(trace.primaryPath.startsWith('M0 '));
  assert.ok(trace.harmonicPath.startsWith('M0 '));
  assert.ok(trace.primaryPath.includes('L240 '));
});
