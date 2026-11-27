export interface SpeechGateState {
  speaking: boolean;
  lastVoiceMs: number;
}

/**
 * Computes normalized RMS amplitude [0..1] from Web Audio AnalyserNode
 * getByteTimeDomainData() samples (centered at 128).
 */
export function computeRmsFromTimeDomain(samples: Uint8Array): number {
  if (samples.length === 0) return 0;
  let sumSq = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const normalized = (samples[i] - 128) / 128;
    sumSq += normalized * normalized;
  }
  return Math.min(1, Math.sqrt(sumSq / samples.length) * 2.2);
}

/**
 * Hysteresis + hold-time speech activity gate so brief pauses between words
 * do not flicker the 3D VoiceVisualizer off prematurely.
 */
export function updateSpeechGate(
  prev: SpeechGateState,
  rms: number,
  nowMs: number,
  threshold = 0.035,
  holdMs = 700
): SpeechGateState {
  if (rms >= threshold) {
    return { speaking: true, lastVoiceMs: nowMs };
  }
  if (prev.speaking && nowMs - prev.lastVoiceMs <= holdMs) {
    return prev;
  }
  return { speaking: false, lastVoiceMs: prev.lastVoiceMs };
}

/**
 * Computes 3D circular waveform coordinates (x, y, z) into a pre-allocated
 * Float32Array of length (pointCount + 1) * 3 (closed loop).
 */
export function fillHologramWaveLoop(
  outPositions: Float32Array,
  pointCount: number,
  baseRadius: number,
  timeDomain: Uint8Array | null,
  elapsedSec: number,
  energy: number
): void {
  const sampleLen = timeDomain?.length ?? 0;
  for (let i = 0; i <= pointCount; i += 1) {
    const idx = i % pointCount;
    const angle = (idx / pointCount) * Math.PI * 2;

    let waveSample = 0;
    if (sampleLen > 0 && timeDomain) {
      const sampleIdx = Math.floor((idx / pointCount) * sampleLen) % sampleLen;
      waveSample = (timeDomain[sampleIdx] - 128) / 128;
    } else {
      waveSample =
        Math.sin(angle * 4 + elapsedSec * 5.2) * 0.45 +
        Math.cos(angle * 7 - elapsedSec * 3.4) * 0.25;
      waveSample *= 0.25 + energy * 0.75;
    }

    const radialOffset = waveSample * (0.34 + energy * 0.42);
    const verticalOffset =
      waveSample * (0.28 + energy * 0.36) +
      Math.sin(angle * 3 - elapsedSec * 2.4) * 0.04;

    const r = baseRadius + radialOffset;
    const outIdx = i * 3;
    outPositions[outIdx] = Math.cos(angle) * r;
    outPositions[outIdx + 1] = verticalOffset;
    outPositions[outIdx + 2] = Math.sin(angle) * r;
  }
}

export interface RhythmicPulse {
  scale: number;
  lift: number;
  opacity: number;
  ringExpand: number;
  waveIntensity: number;
}

/**
 * Computes rhythmic holographic pulse parameters synchronized to current
 * waveform amplitude (`energy` in [0..1]) and accumulated `phaseRad`.
 */
export function computeRhythmicPulse(
  energy: number,
  phaseRad: number,
  reducedMotion = false
): RhythmicPulse {
  const clampedEnergy = Math.max(0, Math.min(1, energy));
  if (reducedMotion) {
    return {
      scale: 1 + clampedEnergy * 0.04,
      lift: 0,
      opacity: Math.min(1, 0.7 + clampedEnergy * 0.28),
      ringExpand: 0.25,
      waveIntensity: 0.5 + clampedEnergy * 0.5,
    };
  }

  // Sharp-attack, smooth-release rhythmic beat curve (0..1)
  const rawSin = 0.5 + 0.5 * Math.sin(phaseRad);
  const beat = Math.pow(rawSin, 1.6);

  const scale = 1 + clampedEnergy * 0.06 + beat * (0.035 + clampedEnergy * 0.12);
  const lift = Math.sin(phaseRad * 0.5) * (0.02 + clampedEnergy * 0.045);
  const opacity = Math.min(1, Math.max(0.55, 0.62 + clampedEnergy * 0.25 + beat * 0.15));
  const ringExpand = ((phaseRad / (Math.PI * 2)) % 1 + 1) % 1;
  const waveIntensity = Math.min(1, 0.35 + clampedEnergy * 0.45 + beat * 0.25);

  return {
    scale,
    lift,
    opacity,
    ringExpand,
    waveIntensity,
  };
}

export const PEAK_HOLD_WINDOW_MS = 2000;

export interface PeakSample {
  amplitude: number;
  timestampMs: number;
}

export interface RollingPeakResult {
  samples: PeakSample[];
  peakAmplitude: number;
  peakDb: number;
}

/**
 * Maintains a true 2-second sliding window of frequency amplitude samples and
 * returns the maximum normalized amplitude [0..1] and calibrated dBFS value.
 */
export function updateRollingPeakHistory(
  prevSamples: PeakSample[],
  currentAmplitude: number,
  nowMs: number,
  windowMs: number = PEAK_HOLD_WINDOW_MS
): RollingPeakResult {
  const clamped = Math.max(0, Math.min(1, currentAmplitude));
  const cutoff = nowMs - windowMs;

  const retained: PeakSample[] = [];
  let peakAmplitude = clamped;

  for (let i = 0; i < prevSamples.length; i += 1) {
    const sample = prevSamples[i];
    if (sample.timestampMs >= cutoff) {
      retained.push(sample);
      if (sample.amplitude > peakAmplitude) {
        peakAmplitude = sample.amplitude;
      }
    }
  }
  retained.push({ amplitude: clamped, timestampMs: nowMs });

  const peakDb =
    peakAmplitude <= 0.001
      ? -60
      : Math.max(-60, Math.min(0, Math.round(20 * Math.log10(peakAmplitude) * 10) / 10));

  return {
    samples: retained,
    peakAmplitude,
    peakDb,
  };
}

/**
 * Updates per-bar 2-second peak-hold values in-place for the 48 3D spectrum bars.
 * When the current value meets or exceeds the held peak (or the 2s window expires),
 * the held peak latches immediately; otherwise it holds steady until expiry, then decays.
 */
export function updatePerBarPeakHold(
  peakValues: Float32Array,
  peakTimestampsMs: Float64Array,
  index: number,
  currentValue: number,
  nowMs: number,
  deltaSec: number,
  windowMs: number = PEAK_HOLD_WINDOW_MS
): number {
  const held = peakValues[index];
  const heldAt = peakTimestampsMs[index];

  if (currentValue >= held || heldAt === 0) {
    peakValues[index] = currentValue;
    peakTimestampsMs[index] = nowMs;
    return peakValues[index];
  }

  if (nowMs - heldAt <= windowMs) {
    return held;
  }

  const decayed = Math.max(currentValue, held - deltaSec * 1.15);
  peakValues[index] = decayed;
  if (decayed <= currentValue + 0.001) {
    peakTimestampsMs[index] = nowMs;
  }
  return decayed;
}


