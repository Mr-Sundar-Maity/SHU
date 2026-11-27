import type { AssistantState } from '../types/shu';

export interface DataGridStreamTrack {
  id: string;
  axis: 'vertical' | 'horizontal';
  /** 1-indexed CSS grid line / track position */
  trackIndex: number;
  durationSec: number;
  delaySec: number;
  tone: 'cyan' | 'teal' | 'indigo';
}

export interface DataGridNodePulse {
  id: string;
  col: number;
  row: number;
  durationSec: number;
  delaySec: number;
}

export interface DataGridVisualProfile {
  speedMultiplier: number;
  opacityLevel: number;
  paused: boolean;
  toneClass: 'is-ready' | 'is-listening' | 'is-thinking' | 'is-speaking' | 'is-stopped';
}

export const DATA_GRID_COLUMNS = 12;
export const DATA_GRID_ROWS = 8;

export const DATA_GRID_STREAMS: readonly DataGridStreamTrack[] = [
  { id: 'v-1', axis: 'vertical', trackIndex: 2, durationSec: 6.4, delaySec: -1.2, tone: 'cyan' },
  { id: 'v-2', axis: 'vertical', trackIndex: 4, durationSec: 5.2, delaySec: -3.4, tone: 'teal' },
  { id: 'v-3', axis: 'vertical', trackIndex: 6, durationSec: 7.1, delaySec: -0.6, tone: 'cyan' },
  { id: 'v-4', axis: 'vertical', trackIndex: 8, durationSec: 5.8, delaySec: -4.1, tone: 'indigo' },
  { id: 'v-5', axis: 'vertical', trackIndex: 10, durationSec: 6.7, delaySec: -2.5, tone: 'cyan' },
  { id: 'v-6', axis: 'vertical', trackIndex: 12, durationSec: 5.5, delaySec: -1.9, tone: 'teal' },
  { id: 'h-1', axis: 'horizontal', trackIndex: 2, durationSec: 7.8, delaySec: -2.1, tone: 'cyan' },
  { id: 'h-2', axis: 'horizontal', trackIndex: 4, durationSec: 6.3, delaySec: -4.6, tone: 'teal' },
  { id: 'h-3', axis: 'horizontal', trackIndex: 6, durationSec: 8.2, delaySec: -1.4, tone: 'indigo' },
  { id: 'h-4', axis: 'horizontal', trackIndex: 8, durationSec: 6.9, delaySec: -3.3, tone: 'cyan' },
];

export const DATA_GRID_NODES: readonly DataGridNodePulse[] = [
  { id: 'n-1', col: 2, row: 2, durationSec: 4.4, delaySec: -0.8 },
  { id: 'n-2', col: 4, row: 6, durationSec: 3.9, delaySec: -2.1 },
  { id: 'n-3', col: 9, row: 2, durationSec: 4.8, delaySec: -1.6 },
  { id: 'n-4', col: 10, row: 6, durationSec: 4.1, delaySec: -3.0 },
  { id: 'n-5', col: 3, row: 4, durationSec: 5.0, delaySec: -2.4 },
  { id: 'n-6', col: 10, row: 4, durationSec: 3.7, delaySec: -0.9 },
];

export function getDataGridProfile(state: AssistantState): DataGridVisualProfile {
  switch (state) {
    case 'listening':
      return {
        speedMultiplier: 0.78,
        opacityLevel: 0.92,
        paused: false,
        toneClass: 'is-listening',
      };
    case 'thinking':
      return {
        speedMultiplier: 0.62,
        opacityLevel: 1,
        paused: false,
        toneClass: 'is-thinking',
      };
    case 'speaking':
      return {
        speedMultiplier: 0.72,
        opacityLevel: 0.95,
        paused: false,
        toneClass: 'is-speaking',
      };
    case 'stopped':
      return {
        speedMultiplier: 1.4,
        opacityLevel: 0.35,
        paused: true,
        toneClass: 'is-stopped',
      };
    case 'ready':
    default:
      return {
        speedMultiplier: 1,
        opacityLevel: 0.76,
        paused: false,
        toneClass: 'is-ready',
      };
  }
}

export const DATA_GRID_RIPPLE_DURATION_MS = 1450;

/**
 * Computes radial stagger delay (in ms) from the center of the CSS grid
 * so each cell lights up synchronously as the holographic ripple expands outward.
 */
export function computeGridCellRippleDelayMs(
  col: number,
  row: number,
  totalCols: number = DATA_GRID_COLUMNS,
  totalRows: number = DATA_GRID_ROWS,
  maxStaggerMs: number = 520
): number {
  const centerCol = (totalCols + 1) / 2;
  const centerRow = (totalRows + 1) / 2;
  const maxDist = Math.hypot(centerCol - 1, centerRow - 1) || 1;
  const dist = Math.hypot(col - centerCol, row - centerRow);
  const normalized = Math.max(0, Math.min(1, dist / maxDist));
  return Math.round(normalized * maxStaggerMs);
}

