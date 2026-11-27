import type { AssistantState } from '../types/shu';

export type NeuralThoughtChannel = 'SYNAPSE' | 'INTENT' | 'DSP' | 'MEMORY' | 'CORE';

export interface NeuralThoughtSnippet {
  id: string;
  channel: NeuralThoughtChannel;
  text: string;
  timestamp: string;
  highlighted: boolean;
}

export const MAX_NEURAL_STREAM_ITEMS = 12;

const THOUGHT_TEMPLATES: Record<AssistantState, Array<{ channel: NeuralThoughtChannel; text: string }>> = {
  ready: [
    { channel: 'CORE', text: 'Semantic lattice calibrated · standby entropy 0.04' },
    { channel: 'MEMORY', text: 'Associative context vectors warm in local L1 cache' },
    { channel: 'DSP', text: 'Acoustic noise floor baseline locked at -58 dBFS' },
    { channel: 'SYNAPSE', text: 'Cross-module telemetry links nominal across 6 orbitals' },
  ],
  listening: [
    { channel: 'DSP', text: 'FFT 128-bin spectral envelope tracking incoming speech' },
    { channel: 'SYNAPSE', text: 'Wake-phrase phonetic lattice evaluating phoneme bursts' },
    { channel: 'INTENT', text: 'Streaming VAD speech gate open · zero-latency capture' },
    { channel: 'CORE', text: 'Routing acoustic frames directly to intent parser' },
  ],
  thinking: [
    { channel: 'INTENT', text: 'Decomposing directive tokens into local execution graph' },
    { channel: 'MEMORY', text: 'Scoring approved context & preference embeddings' },
    { channel: 'SYNAPSE', text: 'Synthesizing deterministic tool-allowlist verification' },
    { channel: 'CORE', text: 'Streaming inference shards to HUD holographic buffer' },
  ],
  speaking: [
    { channel: 'CORE', text: 'Modulating prosody envelope for local voice synthesis' },
    { channel: 'DSP', text: 'Echo cancellation gate protecting mic input channel' },
    { channel: 'SYNAPSE', text: 'Synchronizing vocal cadence with 3D holographic core' },
  ],
  stopped: [
    { channel: 'CORE', text: 'Emergency halt circuit engaged · task queues frozen' },
    { channel: 'DSP', text: 'Audio input & synthesis streams isolated by safeguard' },
  ],
};

function sanitizeCommandPreview(commandText: string): string {
  const clean = commandText.trim().replace(/\s+/g, ' ');
  if (clean.length <= 36) return clean;
  return `${clean.slice(0, 35)}…`;
}

export function buildInitialNeuralStream(timestamp = '20:31:00'): NeuralThoughtSnippet[] {
  return [
    {
      id: 'nds-seed-1',
      channel: 'CORE',
      text: 'Holographic neural manifold online · local inference warm',
      timestamp,
      highlighted: false,
    },
    {
      id: 'nds-seed-2',
      channel: 'MEMORY',
      text: 'Indexed approved preference & contact context vectors',
      timestamp,
      highlighted: false,
    },
    {
      id: 'nds-seed-3',
      channel: 'DSP',
      text: '12-channel acoustic spectral analyzer synchronized',
      timestamp,
      highlighted: false,
    },
  ];
}

export function buildNeuralThoughtSnippet(params: {
  state: AssistantState;
  seq: number;
  timestamp: string;
  commandText?: string;
  bridgeConnected?: boolean;
}): NeuralThoughtSnippet {
  const { state, seq, timestamp, commandText, bridgeConnected } = params;
  const cleanCmd = commandText ? sanitizeCommandPreview(commandText) : '';

  if (cleanCmd) {
    return {
      id: `nds-cmd-${seq}`,
      channel: 'INTENT',
      text: `Parsing directive "${cleanCmd}" -> semantic graph`,
      timestamp,
      highlighted: true,
    };
  }

  const pool = THOUGHT_TEMPLATES[state] ?? THOUGHT_TEMPLATES.ready;
  const pick = pool[Math.abs(seq) % pool.length];
  const suffix = bridgeConnected && seq % 3 === 0 ? ' [PyBridge]' : '';

  return {
    id: `nds-tick-${seq}`,
    channel: pick.channel,
    text: `${pick.text}${suffix}`,
    timestamp,
    highlighted: state === 'thinking' || state === 'speaking',
  };
}

export function appendThoughtStream(
  current: readonly NeuralThoughtSnippet[],
  next: NeuralThoughtSnippet,
  maxItems = MAX_NEURAL_STREAM_ITEMS
): NeuralThoughtSnippet[] {
  if (maxItems <= 0) return [];
  const merged = [...current, next];
  if (merged.length <= maxItems) return merged;
  return merged.slice(merged.length - maxItems);
}
