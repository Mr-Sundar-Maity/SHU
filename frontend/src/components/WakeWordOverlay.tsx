import React from 'react';
import { Radio, X } from 'lucide-react';
import { useShu } from '../context/ShuContext';

export const WakeWordOverlay: React.FC = () => {
  const {
    wakeWordOverlay,
    dismissWakeWordOverlay,
    audioLevel,
  } = useShu();

  if (!wakeWordOverlay.active) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="wake-word-overlay"
      data-wake-phrase={wakeWordOverlay.phrase}
      data-wake-seq={wakeWordOverlay.seq}
      className="holo-surface pointer-events-auto relative mx-auto mb-2 flex w-[calc(100%-2rem)] max-w-md items-center gap-3 rounded-2xl border-teal-400/55 bg-slate-950/90 px-4 py-2 shadow-[0_0_32px_rgba(45,212,191,0.28)] backdrop-blur-md md:absolute md:top-1 md:left-1/2 md:mb-0 md:w-auto md:max-w-none md:-translate-x-1/2 md:gap-3.5 z-30"
    >
      {/* Concentric Holographic Listening Beacon */}
      <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-teal-400/60 bg-teal-500/15">
        <span aria-hidden="true" className="holo-mic-pulse-ring" />
        <span
          aria-hidden="true"
          className="holo-mic-pulse-ring holo-mic-pulse-ring--delayed"
        />
        <Radio className="h-4 w-4 text-teal-300" aria-hidden="true" />
      </div>

      <div className="flex flex-col min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-display text-xs font-semibold tracking-wide text-teal-200 whitespace-nowrap">
            Listening — Ready for Command
          </span>
        </div>
        <span className="font-mono text-[11px] text-sky-200/85 truncate">
          Wake pattern: &ldquo;{wakeWordOverlay.phrase}&rdquo; · Speak command now
        </span>
      </div>

      {/* Live Microphone Level Bars */}
      <div className="hidden sm:flex items-center gap-1 px-1" aria-hidden="true">
        {[0.45, 0.85, 1, 0.75, 0.5].map((w, idx) => (
          <span
            key={idx}
            className="w-1 rounded-full bg-teal-300 transition-transform duration-100"
            style={{
              height: '18px',
              transform: `scaleY(${Math.max(0.28, Math.min(1, (audioLevel || 0.35) * w * 1.45))})`,
            }}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={dismissWakeWordOverlay}
        aria-label="Dismiss wake-word listening overlay"
        className="rounded-lg p-1 text-slate-400 transition-colors hover:bg-slate-800/80 hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-teal-400"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
};
