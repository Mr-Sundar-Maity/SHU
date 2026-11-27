import type { TranscriptEntry } from '../types/shu';

export interface VoiceCommandLogItem {
  id: string;
  text: string;
  timestamp: string;
  status: 'recognized' | 'executed';
}

export const MAX_DRAWER_VOICE_COMMANDS = 5;

export const INITIAL_VOICE_HISTORY_LOGS: readonly VoiceCommandLogItem[] = [];

/**
 * Combines seeded initial voice command history with any recognized voice
 * commands from the active session transcript (preserving chronological order),
 * optionally filtering out individually cleared command IDs.
 */
export function buildVoiceCommandLogs(
  transcript: readonly TranscriptEntry[],
  seedLogs: readonly VoiceCommandLogItem[] = INITIAL_VOICE_HISTORY_LOGS,
  clearedIds: readonly string[] = []
): VoiceCommandLogItem[] {
  const clearedSet = clearedIds.length > 0 ? new Set(clearedIds) : null;
  const sessionVoiceLogs: VoiceCommandLogItem[] = transcript
    .filter((entry) => entry.role === 'user' && entry.mode === 'voice')
    .map((entry) => ({
      id: entry.id,
      text: entry.text,
      timestamp: entry.timestamp,
      status: 'recognized' as const,
    }));

  const combined = [...seedLogs, ...sessionVoiceLogs];
  if (!clearedSet) return combined;
  return combined.filter((item) => !clearedSet.has(item.id));
}

/**
 * Returns the most recent interpreted voice commands (up to `limit`, newest first)
 * for the bottom Command History Log Drawer.
 */
export function getRecentVoiceCommands(
  logs: readonly VoiceCommandLogItem[],
  limit = MAX_DRAWER_VOICE_COMMANDS
): VoiceCommandLogItem[] {
  if (limit <= 0) return [];
  return logs.slice(-limit).reverse();
}

export function shouldAutoScrollTranscript(
  metrics: { scrollHeight: number; scrollTop: number; clientHeight: number },
  thresholdPx = 36
): boolean {
  const remaining = metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight;
  return remaining <= Math.max(0, thresholdPx);
}

/**
 * Splits a completed assistant reply into natural word-preserving chunks
 * so streamed transcript updates trigger incremental auto-scroll smoothly.
 */
export function tokenizeStreamText(text: string): string[] {
  if (!text) return [];
  return text.match(/\S+\s*/g) ?? [text];
}
