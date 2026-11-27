import React, { useEffect, useState } from 'react';
import { Clock } from 'lucide-react';
import { formatHoloClockSnapshot } from '../utils/holoClock';

export const HoloClock: React.FC = () => {
  const [now, setNow] = useState<Date>(() => new Date());
  const [use12Hour, setUse12Hour] = useState<boolean>(false);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(new Date());
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const snapshot = formatHoloClockSnapshot(now, { use12Hour });

  return (
    <button
      type="button"
      data-testid="holo-clock"
      data-clock-format={use12Hour ? '12h' : '24h'}
      onClick={() => setUse12Hour((prev) => !prev)}
      title={`${snapshot.dateLabel} · ${snapshot.ianaZone} (${snapshot.utcOffset}) · Click to toggle 12h/24h`}
      aria-label={`Digital holographic clock ${snapshot.timeText} ${snapshot.tzAbbr} (${snapshot.utcOffset}), ${snapshot.dateLabel}. Click to toggle 12 or 24 hour format.`}
      className="holo-surface-subtle inline-flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 font-mono text-[10.5px] tracking-wide text-sky-100 transition-all hover:border-white/35 focus-visible:outline-2 focus-visible:outline-sky-300 whitespace-nowrap shrink-0"
    >
      <Clock className="h-3 w-3 text-cyan-300/85 shrink-0" aria-hidden="true" />

      <span className="inline-flex items-baseline tabular-nums font-medium text-sky-100">
        <span>{snapshot.hours}</span>
        <span className="mx-px text-cyan-300/80">:</span>
        <span>{snapshot.minutes}</span>
        <span className="hidden sm:inline text-cyan-200/85">
          <span className="mx-px text-cyan-300/65">:</span>
          {snapshot.seconds}
        </span>
        {snapshot.period && (
          <span className="ml-1 text-[9.5px] text-teal-200">{snapshot.period}</span>
        )}
      </span>

      <span aria-hidden="true" className="text-white/20">
        |
      </span>

      <span className="inline-flex items-center gap-1 text-[10px] text-sky-300/90">
        <span data-testid="holo-clock-tz" className="font-semibold text-cyan-200">
          {snapshot.tzAbbr}
        </span>
        <span className="hidden xl:inline text-slate-400 tabular-nums">
          {snapshot.utcOffset}
        </span>
      </span>
    </button>
  );
};
