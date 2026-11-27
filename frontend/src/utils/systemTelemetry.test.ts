import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_TELEMETRY_HISTORY,
  appendTelemetryHistory,
  buildTelemetrySnapshot,
  classifyMetricTone,
  computeGaugeGeometry,
  computePingGaugeRatio,
  seedTelemetryHistory,
} from './systemTelemetry';

test('computeGaugeGeometry produces valid 240-degree arc length, dashOffset, and 9 calibration ticks', () => {
  const half = computeGaugeGeometry(44, 40, 30, 0.5);
  assert.ok(half.trackPath.startsWith('M '));
  assert.ok(half.arcLength > 120 && half.arcLength < 130);
  assert.ok(Math.abs(half.dashOffset - half.arcLength * 0.5) < 0.05);
  assert.equal(half.ticks.length, 9);
  assert.equal(half.ticks[0].active, true);
  assert.equal(half.ticks[8].active, false);
});

test('classifyMetricTone distinguishes nominal, elevated, and critical thresholds', () => {
  assert.equal(classifyMetricTone(30, 65, 85), 'nominal');
  assert.equal(classifyMetricTone(70, 65, 85), 'elevated');
  assert.equal(classifyMetricTone(90, 65, 85), 'critical');
});

test('buildTelemetrySnapshot reflects active voice/thinking workload and real heap values', () => {
  const idle = buildTelemetrySnapshot({
    assistantState: 'ready',
    bridgeStatus: 'disconnected',
    isListening: false,
    isUserSpeaking: false,
    audioLevel: 0,
    transcriptCount: 2,
    memoryCount: 4,
    measuredLoopLagMs: 1.2,
    measuredPingMs: 6,
    isOnline: true,
    cores: 8,
    heapUsedBytes: 52 * 1024 * 1024,
    heapLimitBytes: 2048 * 1024 * 1024,
  });

  const active = buildTelemetrySnapshot({
    assistantState: 'thinking',
    bridgeStatus: 'connected',
    isListening: true,
    isUserSpeaking: true,
    audioLevel: 0.75,
    transcriptCount: 6,
    memoryCount: 5,
    measuredLoopLagMs: 8.5,
    measuredPingMs: 11,
    isOnline: true,
    cores: 8,
    heapUsedBytes: 120 * 1024 * 1024,
    heapLimitBytes: 2048 * 1024 * 1024,
  });

  assert.ok(active.cpuPct > idle.cpuPct);
  assert.ok(active.memoryPct > idle.memoryPct);
  assert.equal(active.pingStatus, 'Bridge');
  assert.equal(idle.pingStatus, 'Live');
  assert.equal(idle.overallLabel, 'Nominal');
});

test('buildTelemetrySnapshot marks halted state and offline ping cleanly', () => {
  const halted = buildTelemetrySnapshot({
    assistantState: 'stopped',
    bridgeStatus: 'disconnected',
    isListening: false,
    isUserSpeaking: false,
    audioLevel: 0,
    transcriptCount: 1,
    memoryCount: 1,
    measuredLoopLagMs: 0.4,
    measuredPingMs: null,
    isOnline: false,
    cores: 4,
  });

  assert.equal(halted.overallLabel, 'Halted');
  assert.equal(halted.pingStatus, 'Offline');
  assert.ok(computePingGaugeRatio(0, false) > 0.9);
  assert.ok(computePingGaugeRatio(8, true) < 0.15);
});

test('seedTelemetryHistory and appendTelemetryHistory keep bounded monotonic indices', () => {
  const sample = buildTelemetrySnapshot({
    assistantState: 'ready',
    bridgeStatus: 'disconnected',
    isListening: false,
    isUserSpeaking: false,
    audioLevel: 0,
    transcriptCount: 1,
    memoryCount: 2,
    measuredLoopLagMs: 1,
    measuredPingMs: 12,
    isOnline: true,
    cores: 4,
  });

  let series = seedTelemetryHistory(sample, 10);
  assert.equal(series.length, 10);
  assert.equal(series[0].index, 0);
  assert.equal(series[9].index, 9);

  for (let i = 0; i < MAX_TELEMETRY_HISTORY + 5; i += 1) {
    series = appendTelemetryHistory(series, {
      ...sample,
      cpuPct: (i * 3) % 100,
    });
  }

  assert.equal(series.length, MAX_TELEMETRY_HISTORY);
  assert.equal(series[0].index, 0);
  assert.equal(series[MAX_TELEMETRY_HISTORY - 1].index, MAX_TELEMETRY_HISTORY - 1);
  assert.equal(series[MAX_TELEMETRY_HISTORY - 1].cpuPct, ((MAX_TELEMETRY_HISTORY + 4) * 3) % 100);
});

import { evaluateSystemServiceHealth } from './systemTelemetry';

test('evaluateSystemServiceHealth classifies optimal, degraded, and offline states cleanly', () => {
  const optimal = evaluateSystemServiceHealth({
    isOnline: true,
    apiReachable: true,
    latencyMs: 14,
    assistantState: 'ready',
    bridgeStatus: 'disconnected',
    providerLabel: 'Local Ollama · qwen2.5:14b',
  });
  assert.equal(optimal.latencyLabel, '14ms');
  assert.equal(optimal.apiHealth, 'Optimal');
  assert.equal(optimal.apiBadgeText, 'OK');
  assert.equal(optimal.aiStatusLabel, 'Ready');
  assert.equal(optimal.aiEngineLabel, 'qwen2.5:14b');
  assert.equal(optimal.overallTone, 'nominal');

  const slow = evaluateSystemServiceHealth({
    isOnline: true,
    apiReachable: true,
    latencyMs: 210,
    assistantState: 'thinking',
    bridgeStatus: 'connected',
    providerLabel: 'Local Ollama · qwen2.5:14b',
  });
  assert.equal(slow.apiHealth, 'Degraded');
  assert.equal(slow.apiBadgeText, 'SLOW');
  assert.equal(slow.aiStatusLabel, 'Thinking');
  assert.equal(slow.aiEngineLabel, 'PyBridge WS');
  assert.equal(slow.overallTone, 'elevated');

  const offline = evaluateSystemServiceHealth({
    isOnline: false,
    apiReachable: false,
    latencyMs: null,
    assistantState: 'stopped',
    bridgeStatus: 'disconnected',
    providerLabel: 'Local Ollama',
  });
  assert.equal(offline.latencyLabel, 'OFF');
  assert.equal(offline.apiHealth, 'Offline');
  assert.equal(offline.apiBadgeText, 'DOWN');
  assert.equal(offline.aiStatusLabel, 'Halted');
  assert.equal(offline.overallTone, 'critical');
});


