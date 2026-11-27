export interface WakeWordDetection {
  matched: boolean;
  wakePhrase: string | null;
  trailingCommand: string;
}

export interface AcousticWakeState {
  sawQuietBaseline: boolean;
  lastTriggeredMs: number;
}

const WAKE_WORD_REGEX =
  /\b(hey\s+shu|ok\s+shu|okay\s+shu|hello\s+shu|wake\s+up\s+shu|hey\s+computer|computer|shu)\b/i;

/**
 * Matches spoken or recognized transcripts against supported SHU wake-word
 * patterns and extracts any trailing command spoken right after the wake phrase.
 */
export function detectWakeWordPattern(rawTranscript: string): WakeWordDetection {
  const cleaned = rawTranscript.trim();
  if (!cleaned) {
    return { matched: false, wakePhrase: null, trailingCommand: '' };
  }

  const match = cleaned.match(WAKE_WORD_REGEX);
  if (!match || match.index === undefined) {
    return { matched: false, wakePhrase: null, trailingCommand: cleaned };
  }

  const rawPhrase = match[1];
  const normalizedPhrase = rawPhrase
    .split(/\s+/)
    .map((part) => (part.toLowerCase() === 'shu' ? 'SHU' : part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()))
    .join(' ');

  const afterIdx = match.index + match[0].length;
  const trailingCommand = cleaned
    .slice(afterIdx)
    .replace(/^[,.:;!\-\s]+/, '')
    .trim();

  return {
    matched: true,
    wakePhrase: normalizedPhrase,
    trailingCommand,
  };
}

/**
 * Detects an acoustic wake-word onset burst from live Microphone API RMS frames
 * (sharp vocal onset following a quiet baseline, gated by cooldown).
 */
export function detectAcousticWakeBurst(
  rms: number,
  prevState: AcousticWakeState,
  nowMs: number,
  cooldownMs = 5000
): { triggered: boolean; nextState: AcousticWakeState } {
  const quietThreshold = 0.045;
  const burstThreshold = 0.17;

  if (rms <= quietThreshold) {
    return {
      triggered: false,
      nextState: { ...prevState, sawQuietBaseline: true },
    };
  }

  const cooledDown =
    prevState.lastTriggeredMs === 0 || nowMs - prevState.lastTriggeredMs >= cooldownMs;

  if (prevState.sawQuietBaseline && rms >= burstThreshold && cooledDown) {
    return {
      triggered: true,
      nextState: { sawQuietBaseline: false, lastTriggeredMs: nowMs },
    };
  }

  return { triggered: false, nextState: prevState };
}
