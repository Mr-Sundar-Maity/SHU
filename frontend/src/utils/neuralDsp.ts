import type { AssistantState, BridgeConnectionStatus } from '../types/shu';

export type DspStageStatus = 'active' | 'idle' | 'muted' | 'halted';

export interface DspPipelineStage {
  id: 'mic' | 'vad' | 'llm' | 'tts';
  label: string;
  stateLabel: string;
  status: DspStageStatus;
}

export interface NeuralDspSnapshot {
  sampleRateKhz: string;
  fftBins: number;
  rmsPct: number;
  peakDb: number;
  snrDb: number;
  noiseFloorDb: number;
  latencyMs: number;
  providerShort: string;
  localeShort: string;
  pipelineMode: string;
  stages: DspPipelineStage[];
}

export function extractShortProvider(provider: string): string {
  const trimmed = provider.trim();
  if (!trimmed) return 'Local LLM';
  const dotParts = trimmed.split('·').map((p) => p.trim()).filter(Boolean);
  if (dotParts.length > 1) {
    return dotParts[dotParts.length - 1];
  }
  return trimmed.length > 18 ? `${trimmed.slice(0, 16)}..` : trimmed;
}

export function extractShortLocale(voiceLanguage: string): string {
  const match = voiceLanguage.match(/\(([a-z]{2}-[A-Z]{2})\)/);
  if (match) return match[1];
  return voiceLanguage.trim().slice(0, 8) || 'en-US';
}

export function updatePeakHoldBands(
  currentBands: readonly number[],
  previousPeaks: readonly number[],
  decayStep = 0.045
): number[] {
  return currentBands.map((level, idx) => {
    const prev = previousPeaks[idx] ?? 0;
    const decayed = Math.max(0.1, prev - decayStep);
    return Number(Math.max(level, decayed).toFixed(3));
  });
}

export function computeWaveTracePoints(
  phase: number,
  audioLevel: number,
  assistantState: AssistantState,
  isListening: boolean,
  width = 240,
  height = 42,
  samples = 32
): { primaryPath: string; harmonicPath: string } {
  const clampedAudio = Math.max(0, Math.min(1, Number.isFinite(audioLevel) ? audioLevel : 0));
  const ampScale =
    assistantState === 'stopped'
      ? 0.08
      : assistantState === 'thinking'
      ? 0.55
      : assistantState === 'speaking'
      ? 0.72
      : isListening
      ? Math.max(0.28, clampedAudio * 0.95)
      : 0.18;

  const midY = height / 2;
  const maxAmp = height * 0.38 * ampScale;

  const primaryCoords: string[] = [];
  const harmonicCoords: string[] = [];

  for (let i = 0; i < samples; i += 1) {
    const t = i / (samples - 1);
    const x = Number((t * width).toFixed(1));
    const envelope = Math.sin(t * Math.PI);
    const y1 =
      midY +
      Math.sin(t * Math.PI * 4 + phase * 1.4) * maxAmp * envelope +
      Math.cos(t * Math.PI * 7 - phase * 0.8) * (maxAmp * 0.35) * envelope;
    const y2 =
      midY +
      Math.cos(t * Math.PI * 3 - phase * 1.15) * (maxAmp * 0.68) * envelope;

    primaryCoords.push(`${i === 0 ? 'M' : 'L'}${x} ${y1.toFixed(1)}`);
    harmonicCoords.push(`${i === 0 ? 'M' : 'L'}${x} ${y2.toFixed(1)}`);
  }

  return {
    primaryPath: primaryCoords.join(' '),
    harmonicPath: harmonicCoords.join(' '),
  };
}

export function computeNeuralDspSnapshot(params: {
  assistantState: AssistantState;
  isListening: boolean;
  isMuted: boolean;
  isUserSpeaking: boolean;
  quietMode: boolean;
  audioLevel: number;
  sampleRateHz?: number;
  fftSize?: number;
  bridgeStatus: BridgeConnectionStatus;
  provider: string;
  voiceLanguage: string;
  phase: number;
}): NeuralDspSnapshot {
  const clampedAudio = Math.max(0, Math.min(1, Number.isFinite(params.audioLevel) ? params.audioLevel : 0));
  const rmsPct = Math.round(clampedAudio * 100);
  const sampleRateHz =
    typeof params.sampleRateHz === 'number' && params.sampleRateHz > 0
      ? params.sampleRateHz
      : 48000;
  const fftBins =
    typeof params.fftSize === 'number' && params.fftSize > 0
      ? Math.round(params.fftSize / 2)
      : 128;

  const effectiveLevel =
    params.assistantState === 'stopped' || params.isMuted
      ? 0.015
      : params.assistantState === 'thinking' || params.assistantState === 'speaking'
      ? Math.max(0.28, clampedAudio)
      : params.isListening
      ? Math.max(0.14, clampedAudio)
      : 0.04;

  const peakDb = Math.max(-60, Math.min(-1, Math.round(20 * Math.log10(effectiveLevel))));
  const noiseFloorDb = params.isMuted ? -68 : params.isListening ? -52 : -58;
  const snrDb = Math.max(4, Math.min(48, peakDb - noiseFloorDb));
  const latencyMs =
    params.assistantState === 'stopped'
      ? 0
      : params.bridgeStatus === 'connected'
      ? 14 + Math.round((Math.sin(params.phase) + 1) * 3)
      : 6 + Math.round((Math.cos(params.phase) + 1) * 2);

  const pipelineMode =
    params.assistantState === 'stopped'
      ? 'Halted'
      : params.assistantState === 'thinking'
      ? 'Synthesizing'
      : params.assistantState === 'speaking'
      ? 'Vocal Output'
      : params.isListening
      ? 'Acoustic Stream'
      : 'Core Standby';

  const stages: DspPipelineStage[] = [
    {
      id: 'mic',
      label: 'MIC',
      stateLabel: params.isMuted ? 'Muted' : params.isListening ? 'Hot' : 'Armed',
      status: params.isMuted ? 'muted' : params.isListening ? 'active' : 'idle',
    },
    {
      id: 'vad',
      label: 'VAD',
      stateLabel:
        params.assistantState === 'stopped'
          ? 'Halted'
          : params.isUserSpeaking
          ? 'Speech'
          : params.isListening
          ? 'Gate'
          : 'Idle',
      status:
        params.assistantState === 'stopped'
          ? 'halted'
          : params.isUserSpeaking || params.isListening
          ? 'active'
          : 'idle',
    },
    {
      id: 'llm',
      label: 'LLM',
      stateLabel:
        params.assistantState === 'stopped'
          ? 'Halted'
          : params.assistantState === 'thinking'
          ? 'Infer'
          : 'Ready',
      status:
        params.assistantState === 'stopped'
          ? 'halted'
          : params.assistantState === 'thinking'
          ? 'active'
          : 'idle',
    },
    {
      id: 'tts',
      label: 'TTS',
      stateLabel: params.quietMode
        ? 'Quiet'
        : params.assistantState === 'speaking'
        ? 'Speak'
        : 'Standby',
      status: params.quietMode
        ? 'muted'
        : params.assistantState === 'speaking'
        ? 'active'
        : 'idle',
    },
  ];

  return {
    sampleRateKhz: `${(sampleRateHz / 1000).toFixed(1)}kHz`,
    fftBins,
    rmsPct,
    peakDb,
    snrDb,
    noiseFloorDb,
    latencyMs,
    providerShort: extractShortProvider(params.provider),
    localeShort: extractShortLocale(params.voiceLanguage),
    pipelineMode,
    stages,
  };
}
