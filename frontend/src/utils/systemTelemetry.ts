import type { AssistantState, BridgeConnectionStatus } from '../types/shu';

export type TelemetryTone = 'nominal' | 'elevated' | 'critical';

export interface TelemetrySample {
  cpuPct: number;
  memoryPct: number;
  memoryUsedMb: number;
  memoryLimitMb: number;
  pingMs: number;
  pingStatus: 'Live' | 'Bridge' | 'Offline' | 'Degraded';
  cores: number;
  loopLagMs: number;
  overallTone: TelemetryTone;
  overallLabel: 'Nominal' | 'Elevated' | 'Critical' | 'Halted';
  updatedAt: string;
}

export interface TelemetryProbeInputs {
  assistantState: AssistantState;
  bridgeStatus: BridgeConnectionStatus;
  isListening: boolean;
  isUserSpeaking: boolean;
  audioLevel: number;
  transcriptCount: number;
  memoryCount: number;
  measuredLoopLagMs: number;
  measuredPingMs: number | null;
  isOnline: boolean;
  cores: number;
  heapUsedBytes?: number;
  heapLimitBytes?: number;
  prevCpuPct?: number;
  prevMemoryPct?: number;
}

export const GAUGE_START_ANGLE = 150;
export const GAUGE_END_ANGLE = 390;
export const GAUGE_SWEEP_DEG = GAUGE_END_ANGLE - GAUGE_START_ANGLE; // 240 deg

export function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function smoothMetric(prev: number | undefined, next: number, alpha = 0.35): number {
  if (prev === undefined || !Number.isFinite(prev)) return next;
  return prev + (next - prev) * alpha;
}

export function classifyMetricTone(
  value: number,
  elevatedThreshold: number,
  criticalThreshold: number
): TelemetryTone {
  if (value >= criticalThreshold) return 'critical';
  if (value >= elevatedThreshold) return 'elevated';
  return 'nominal';
}

export function polarToCartesian(
  cx: number,
  cy: number,
  radius: number,
  angleDeg: number
): { x: number; y: number } {
  const rad = (angleDeg * Math.PI) / 180;
  return {
    x: Number((cx + radius * Math.cos(rad)).toFixed(2)),
    y: Number((cy + radius * Math.sin(rad)).toFixed(2)),
  };
}

export function describeGaugeArc(
  cx: number,
  cy: number,
  radius: number,
  startAngleDeg = GAUGE_START_ANGLE,
  endAngleDeg = GAUGE_END_ANGLE
): string {
  const start = polarToCartesian(cx, cy, radius, startAngleDeg);
  const end = polarToCartesian(cx, cy, radius, endAngleDeg);
  const sweep = endAngleDeg - startAngleDeg;
  const largeArcFlag = Math.abs(sweep) > 180 ? 1 : 0;
  const sweepFlag = sweep >= 0 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArcFlag} ${sweepFlag} ${end.x} ${end.y}`;
}

export function computeGaugeGeometry(
  cx: number,
  cy: number,
  radius: number,
  ratio: number
): {
  trackPath: string;
  arcLength: number;
  dashOffset: number;
  tip: { x: number; y: number };
  ticks: Array<{ x1: number; y1: number; x2: number; y2: number; active: boolean }>;
} {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(ratio) ? ratio : 0));
  const arcLength = Number(((GAUGE_SWEEP_DEG / 360) * 2 * Math.PI * radius).toFixed(3));
  const dashOffset = Number((arcLength * (1 - clamped)).toFixed(3));
  const tipAngle = GAUGE_START_ANGLE + clamped * GAUGE_SWEEP_DEG;
  const tip = polarToCartesian(cx, cy, radius, tipAngle);

  const tickCount = 9;
  const ticks = Array.from({ length: tickCount }, (_, idx) => {
    const t = idx / (tickCount - 1);
    const angle = GAUGE_START_ANGLE + t * GAUGE_SWEEP_DEG;
    const inner = polarToCartesian(cx, cy, radius - 5.5, angle);
    const outer = polarToCartesian(cx, cy, radius - 2.5, angle);
    return {
      x1: inner.x,
      y1: inner.y,
      x2: outer.x,
      y2: outer.y,
      active: t <= clamped + 0.01,
    };
  });

  return {
    trackPath: describeGaugeArc(cx, cy, radius, GAUGE_START_ANGLE, GAUGE_END_ANGLE),
    arcLength,
    dashOffset,
    tip,
    ticks,
  };
}

/**
 * Computes a normalized [0..1] gauge fill ratio for ping latency (0..120ms scale)
 * so healthy low-ping stays compact/nominal while higher latency fills into elevated/critical zones.
 */
export function computePingGaugeRatio(pingMs: number, isOnline: boolean): number {
  if (!isOnline || pingMs <= 0) return 0.96;
  return Math.max(0.06, Math.min(1, pingMs / 120));
}

export function buildTelemetrySnapshot(
  input: TelemetryProbeInputs,
  now: Date = new Date()
): TelemetrySample {
  const loopLagMs = Math.max(0, Math.round(input.measuredLoopLagMs * 10) / 10);

  // Derive realistic CPU load from genuine event-loop lag + active SHU subsystems
  let rawCpu = 8 + Math.min(48, loopLagMs * 1.8);
  if (input.isListening) rawCpu += 7;
  if (input.isUserSpeaking) rawCpu += 10 + Math.round(input.audioLevel * 18);
  if (input.assistantState === 'thinking') rawCpu += 22;
  if (input.assistantState === 'speaking') rawCpu += 12;
  if (input.assistantState === 'stopped') rawCpu = Math.max(2, Math.min(8, loopLagMs * 0.6 + 3));

  const cpuPct = clampPercent(smoothMetric(input.prevCpuPct, rawCpu, 0.4));

  // Derive Memory usage from real JS Heap telemetry when available (Chromium performance.memory)
  let memoryUsedMb: number;
  let memoryLimitMb: number;
  let rawMemoryPct: number;

  if (
    typeof input.heapUsedBytes === 'number' &&
    typeof input.heapLimitBytes === 'number' &&
    input.heapLimitBytes > 0
  ) {
    memoryUsedMb = Math.max(1, Math.round(input.heapUsedBytes / (1024 * 1024)));
    memoryLimitMb = Math.max(memoryUsedMb, Math.round(input.heapLimitBytes / (1024 * 1024)));
    // Scale against working-set ceiling so typical ~40-90MB SPA heap registers as meaningful utilization
    const effectivePoolMb = Math.min(memoryLimitMb, Math.max(256, Math.round(memoryLimitMb * 0.12)));
    rawMemoryPct = Math.min(98, Math.max(6, (memoryUsedMb / effectivePoolMb) * 100));
  } else {
    memoryLimitMb = 512;
    memoryUsedMb = Math.min(
      memoryLimitMb,
      46 + input.transcriptCount * 2 + input.memoryCount * 3 + (input.isListening ? 14 : 0)
    );
    rawMemoryPct = (memoryUsedMb / memoryLimitMb) * 100;
  }

  const memoryPct = clampPercent(smoothMetric(input.prevMemoryPct, rawMemoryPct, 0.35));

  const pingMs =
    input.measuredPingMs !== null && Number.isFinite(input.measuredPingMs)
      ? Math.max(1, Math.round(input.measuredPingMs))
      : 0;

  let pingStatus: TelemetrySample['pingStatus'] = 'Live';
  if (!input.isOnline) {
    pingStatus = 'Offline';
  } else if (input.measuredPingMs === null || pingMs >= 95) {
    pingStatus = 'Degraded';
  } else if (input.bridgeStatus === 'connected') {
    pingStatus = 'Bridge';
  }

  const cpuTone = classifyMetricTone(cpuPct, 65, 85);
  const memTone = classifyMetricTone(memoryPct, 72, 90);
  const pingTone: TelemetryTone =
    pingStatus === 'Offline' ? 'critical' : pingStatus === 'Degraded' ? 'elevated' : 'nominal';

  let overallTone: TelemetryTone = 'nominal';
  if (cpuTone === 'critical' || memTone === 'critical' || pingTone === 'critical') {
    overallTone = 'critical';
  } else if (cpuTone === 'elevated' || memTone === 'elevated' || pingTone === 'elevated') {
    overallTone = 'elevated';
  }

  const overallLabel: TelemetrySample['overallLabel'] =
    input.assistantState === 'stopped'
      ? 'Halted'
      : overallTone === 'critical'
      ? 'Critical'
      : overallTone === 'elevated'
      ? 'Elevated'
      : 'Nominal';

  const updatedAt = `${String(now.getHours()).padStart(2, '0')}:${String(
    now.getMinutes()
  ).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;

  return {
    cpuPct,
    memoryPct,
    memoryUsedMb,
    memoryLimitMb,
    pingMs,
    pingStatus,
    cores: Math.max(1, Math.round(input.cores || 4)),
    loopLagMs,
    overallTone,
    overallLabel,
    updatedAt,
  };
}

export interface TelemetryStreamPoint {
  index: number;
  timestamp: string;
  cpuPct: number;
  memoryPct: number;
  latencyPct: number;
  pingMs: number;
}

export const MAX_TELEMETRY_HISTORY = 24;

export function sampleToStreamPoint(
  sample: TelemetrySample,
  index: number
): TelemetryStreamPoint {
  const latencyPct = Math.round(
    computePingGaugeRatio(sample.pingMs, sample.pingStatus !== 'Offline') * 100
  );
  return {
    index,
    timestamp: sample.updatedAt,
    cpuPct: sample.cpuPct,
    memoryPct: sample.memoryPct,
    latencyPct,
    pingMs: sample.pingMs,
  };
}

export function seedTelemetryHistory(
  initialSample: TelemetrySample,
  count = 14
): TelemetryStreamPoint[] {
  const safeCount = Math.max(2, Math.min(MAX_TELEMETRY_HISTORY, count));
  const basePoint = sampleToStreamPoint(initialSample, 0);
  return Array.from({ length: safeCount }, (_, idx) => ({
    ...basePoint,
    index: idx,
  }));
}

export function appendTelemetryHistory(
  history: readonly TelemetryStreamPoint[],
  sample: TelemetrySample,
  maxPoints = MAX_TELEMETRY_HISTORY
): TelemetryStreamPoint[] {
  const nextRaw = [...history, sampleToStreamPoint(sample, history.length)];
  const sliced = nextRaw.slice(-Math.max(2, maxPoints));
  return sliced.map((point, idx) => ({
    ...point,
    index: idx,
  }));
}

export interface SystemServiceHealthInput {
  isOnline: boolean;
  apiReachable: boolean;
  latencyMs: number | null;
  assistantState: AssistantState;
  bridgeStatus: BridgeConnectionStatus;
  providerLabel: string;
}

export interface SystemServiceHealth {
  latencyMs: number | null;
  latencyLabel: string;
  latencyTone: TelemetryTone;
  apiHealth: 'Optimal' | 'Degraded' | 'Offline';
  apiBadgeText: 'OK' | 'SLOW' | 'DOWN';
  apiTone: TelemetryTone;
  aiStatusLabel: 'Ready' | 'Listening' | 'Thinking' | 'Speaking' | 'Halted';
  aiEngineLabel: string;
  aiTone: TelemetryTone;
  overallTone: TelemetryTone;
}

export function evaluateSystemServiceHealth(
  input: SystemServiceHealthInput
): SystemServiceHealth {
  const validLatency =
    input.latencyMs !== null && Number.isFinite(input.latencyMs) && input.latencyMs >= 0
      ? Math.max(1, Math.round(input.latencyMs))
      : null;

  const latencyLabel = !input.isOnline
    ? 'OFF'
    : validLatency !== null
    ? `${validLatency}ms`
    : '--ms';

  const latencyTone: TelemetryTone = !input.isOnline
    ? 'critical'
    : validLatency === null || validLatency >= 140
    ? 'elevated'
    : 'nominal';

  let apiHealth: SystemServiceHealth['apiHealth'] = 'Optimal';
  let apiBadgeText: SystemServiceHealth['apiBadgeText'] = 'OK';
  let apiTone: TelemetryTone = 'nominal';

  if (!input.isOnline || !input.apiReachable) {
    apiHealth = 'Offline';
    apiBadgeText = 'DOWN';
    apiTone = 'critical';
  } else if (validLatency === null || validLatency >= 140) {
    apiHealth = 'Degraded';
    apiBadgeText = 'SLOW';
    apiTone = 'elevated';
  }

  const aiStatusLabel: SystemServiceHealth['aiStatusLabel'] =
    input.assistantState === 'stopped'
      ? 'Halted'
      : input.assistantState === 'thinking'
      ? 'Thinking'
      : input.assistantState === 'speaking'
      ? 'Speaking'
      : input.assistantState === 'listening'
      ? 'Listening'
      : 'Ready';

  const aiTone: TelemetryTone =
    input.assistantState === 'stopped'
      ? 'critical'
      : input.assistantState === 'thinking'
      ? 'elevated'
      : 'nominal';

  const providerParts = input.providerLabel
    .split('·')
    .map((s) => s.trim())
    .filter(Boolean);
  const aiEngineLabel =
    input.bridgeStatus === 'connected'
      ? 'PyBridge WS'
      : providerParts[providerParts.length - 1] ?? 'Local Core';

  const overallTone: TelemetryTone =
    apiTone === 'critical' || aiTone === 'critical' || latencyTone === 'critical'
      ? 'critical'
      : apiTone === 'elevated' || aiTone === 'elevated' || latencyTone === 'elevated'
      ? 'elevated'
      : 'nominal';

  return {
    latencyMs: validLatency,
    latencyLabel,
    latencyTone,
    apiHealth,
    apiBadgeText,
    apiTone,
    aiStatusLabel,
    aiEngineLabel,
    aiTone,
    overallTone,
  };
}


