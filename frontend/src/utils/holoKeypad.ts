export interface HoloKeySpec {
  id: string;
  label: string;
  subLabel?: string;
  value: string;
  kind: 'digit' | 'symbol' | 'prefix' | 'control';
}

export const HOLO_KEYPAD_PREFIX_KEYS: readonly HoloKeySpec[] = [
  { id: 'prefix-hash', label: 'TASK #', value: 'Task #', kind: 'prefix' },
  { id: 'prefix-wf', label: 'WF-', value: 'wf-', kind: 'prefix' },
  { id: 'prefix-rem', label: 'REM-', value: 'rem-', kind: 'prefix' },
];

export const HOLO_KEYPAD_GRID_KEYS: readonly HoloKeySpec[] = [
  { id: 'k1', label: '1', subLabel: 'CORE', value: '1', kind: 'digit' },
  { id: 'k2', label: '2', subLabel: 'MEM', value: '2', kind: 'digit' },
  { id: 'k3', label: '3', subLabel: 'WRK', value: '3', kind: 'digit' },
  { id: 'k4', label: '4', subLabel: 'REM', value: '4', kind: 'digit' },
  { id: 'k5', label: '5', subLabel: 'COM', value: '5', kind: 'digit' },
  { id: 'k6', label: '6', subLabel: 'DSP', value: '6', kind: 'digit' },
  { id: 'k7', label: '7', subLabel: 'WX', value: '7', kind: 'digit' },
  { id: 'k8', label: '8', subLabel: 'LOG', value: '8', kind: 'digit' },
  { id: 'k9', label: '9', subLabel: 'SYS', value: '9', kind: 'digit' },
  { id: 'k-hash', label: '#', subLabel: 'ID', value: '#', kind: 'symbol' },
  { id: 'k0', label: '0', subLabel: 'ZERO', value: '0', kind: 'digit' },
  { id: 'k-dash', label: '-', subLabel: 'SEP', value: '-', kind: 'symbol' },
];

export function applyKeypadInput(current: string, token: string, maxLength = 64): string {
  if (!token) return current;
  const next = `${current}${token}`;
  return next.length > maxLength ? next.slice(0, maxLength) : next;
}

export function backspaceKeypadInput(current: string): string {
  if (!current) return '';
  return current.slice(0, -1);
}

export function formatKeypadSubmission(rawBuffer: string): string {
  const trimmed = rawBuffer.trim();
  if (!trimmed) return '';
  if (/^\d+$/.test(trimmed)) {
    return `Task #${trimmed}`;
  }
  return trimmed;
}
