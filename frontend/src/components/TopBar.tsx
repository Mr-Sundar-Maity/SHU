import React from 'react';
import { OctagonAlert, Play } from 'lucide-react';
import { useShu } from '../context/ShuContext';
import { HoloClock } from './HoloClock';
import { SystemStatusIndicator } from './SystemStatusIndicator';

export const TopBar: React.FC = () => {
  const {
    setActiveTab,
    assistantState,
    triggerEmergencyStop,
    resumeAssistant,
  } = useShu();

  const isStopped = assistantState === 'stopped';

  return (
    <header className="relative z-30 w-full border-b border-sky-400/10 bg-[#060911]/85 backdrop-blur-sm">
      <div className="mx-auto grid w-full max-w-[1440px] grid-cols-[1fr_auto_1fr] items-center gap-2 px-3 sm:px-5 py-2.5">
        {/* Zone 1 (Left): Single-line brand wordmark */}
        <div className="justify-self-start">
          <a
            href="#assistant"
            onClick={(e) => {
              e.preventDefault();
              setActiveTab('assistant');
            }}
            className="font-display text-lg font-semibold tracking-[0.18em] text-slate-100 whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-sky-400"
          >
            SHU
          </a>
        </div>

        {/* Zone 2 (Center): Digital Holographic Clock + System Status Info */}
        <div
          data-testid="topbar-center-telemetry"
          className="justify-self-center flex items-center justify-center gap-1.5 sm:gap-2"
        >
          <HoloClock />
          <SystemStatusIndicator />
        </div>

        {/* Zone 3 (Right): Primary Safety Action */}
        <div className="justify-self-end flex items-center shrink-0">
          {isStopped ? (
            <button
              type="button"
              onClick={resumeAssistant}
              className="inline-flex items-center gap-1.5 sm:gap-2 rounded-lg border border-teal-400/40 bg-teal-500/15 px-3 sm:px-3.5 py-1.5 text-xs font-medium text-teal-200 transition-colors hover:bg-teal-500/25 whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-teal-400"
            >
              <Play className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">Resume SHU</span>
              <span className="sm:hidden">Resume</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={triggerEmergencyStop}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/45 bg-rose-600/20 px-3 py-1.5 text-xs font-medium text-rose-200 transition-colors hover:bg-rose-600/35 whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-rose-400"
            >
              <OctagonAlert className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">Emergency stop</span>
              <span className="sm:hidden">Stop</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
