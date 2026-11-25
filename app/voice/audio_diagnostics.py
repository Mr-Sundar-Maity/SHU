"""Short, non-persistent microphone level checks for local setup."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import sounddevice as sd


@dataclass(frozen=True, slots=True)
class AudioLevelReport:
    """Peak and RMS levels for one in-memory audio sample."""

    sample_count: int
    rms: float
    peak: float
    rms_dbfs: float
    peak_dbfs: float
    clipping_fraction: float
    status: str


def analyze_input_audio(audio: np.ndarray) -> AudioLevelReport:
    """Classify input level using conservative, documented level heuristics."""
    waveform = np.asarray(audio, dtype=np.float32).reshape(-1)
    if waveform.size == 0:
        raise ValueError("No audio samples were captured")
    if not np.isfinite(waveform).all():
        raise ValueError("Audio contains non-finite samples")

    absolute = np.abs(waveform)
    rms = float(np.sqrt(np.mean(np.square(waveform), dtype=np.float64)))
    peak = float(np.max(absolute))
    clipping_fraction = float(np.mean(absolute >= 0.999))
    rms_dbfs = 20.0 * math.log10(max(rms, 1e-12))
    peak_dbfs = 20.0 * math.log10(max(peak, 1e-12))

    if clipping_fraction >= 0.001 or peak >= 1.0:
        status = "clipping"
    elif rms < 0.0001 and peak < 0.001:
        status = "silent"
    elif rms < 0.005 or peak < 0.02:
        status = "low"
    else:
        status = "usable"

    return AudioLevelReport(
        sample_count=int(waveform.size),
        rms=rms,
        peak=peak,
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        clipping_fraction=clipping_fraction,
        status=status,
    )


def capture_input_level(
    device_index: int,
    *,
    duration_seconds: float = 3.0,
    sample_rate: int = 16_000,
) -> AudioLevelReport:
    """Capture a short sample, calculate levels, and discard the waveform."""
    if device_index < 0:
        raise ValueError("Microphone device index cannot be negative")
    if not 1.0 <= duration_seconds <= 15.0:
        raise ValueError("Microphone check duration must be between 1 and 15 seconds")
    if sample_rate < 8_000:
        raise ValueError("Sample rate must be at least 8000 Hz")

    samples = sd.rec(
        int(duration_seconds * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device_index,
    )
    sd.wait()
    report = analyze_input_audio(samples)
    del samples
    return report
