import React from 'react';
import { CornerDownLeft, Delete, Grid3x3, ListChecks, X } from 'lucide-react';
import {
  HOLO_KEYPAD_GRID_KEYS,
  HOLO_KEYPAD_PREFIX_KEYS,
  applyKeypadInput,
  backspaceKeypadInput,
  formatKeypadSubmission,
} from '../utils/holoKeypad';

interface HoloKeypadProps {
  value: string;
  onChange: React.Dispatch<React.SetStateAction<string>>;
  onSubmitCommand: (mode: 'direct' | 'plan', commandText: string) => void;
  onClose: () => void;
}

export const HoloKeypad: React.FC<HoloKeypadProps> = ({
  value,
  onChange,
  onSubmitCommand,
  onClose,
}) => {
  const handleKeyPress = (token: string) => {
    onChange((prev) => applyKeypadInput(prev, token));
  };

  const handleBackspace = () => {
    onChange((prev) => backspaceKeypadInput(prev));
  };

  const handleClear = () => {
    onChange('');
  };

  const handleDispatch = (mode: 'direct' | 'plan') => {
    const formatted = formatKeypadSubmission(value);
    if (!formatted) return;
    onSubmitCommand(mode, formatted);
  };

  return (
    <div
      role="dialog"
      aria-label="Virtual holographic command keypad"
      data-testid="holo-keypad"
      className="holo-popover relative z-40 mb-2 w-full rounded-2xl p-3 md:absolute md:bottom-full md:right-0 md:mb-2 lg:fixed lg:bottom-[184px] lg:right-3 lg:mb-0 lg:w-[320px]"
    >
      {/* Keypad Header with Close "X" */}
      <div className="mb-2 flex items-center justify-between gap-2 border-b border-white/12 pb-1.5">
        <div className="flex items-center gap-1.5">
          <Grid3x3 className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
          <span className="font-mono text-[10.5px] font-semibold tracking-wider text-sky-100">
            Holographic Keypad
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close holographic keypad"
          data-testid="close-holo-keypad"
          className="inline-flex h-6 w-6 items-center justify-center rounded-lg border border-white/15 bg-white/5 text-slate-300 hover:border-sky-400/50 hover:bg-sky-500/15 hover:text-white transition-colors"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>

      {/* Live Numeric / Task ID Readout */}
      <div
        data-testid="holo-keypad-display"
        className="mb-2 flex items-center justify-between gap-2 rounded-lg border border-sky-400/25 bg-[#030712]/90 px-2.5 py-1.5 font-mono text-xs"
      >
        <span className="truncate text-cyan-200 tabular-nums">
          {value || 'Enter task ID or command...'}
        </span>
        <span className="shrink-0 text-[9.5px] text-slate-500 tabular-nums">
          {value ? `${value.length}ch` : 'ID'}
        </span>
      </div>

      {/* Quick Command / ID Prefix Strip */}
      <div className="mb-2 grid grid-cols-3 gap-1.5">
        {HOLO_KEYPAD_PREFIX_KEYS.map((key) => (
          <button
            key={key.id}
            type="button"
            data-testid={`keypad-prefix-${key.id}`}
            onClick={() => handleKeyPress(key.value)}
            className="holo-key-3d rounded-lg px-2 py-1 font-mono text-[10px] font-semibold tracking-wide text-cyan-200"
          >
            {key.label}
          </button>
        ))}
      </div>

      {/* 3D-Styled Numeric & Symbol Grid */}
      <div className="holo-keypad-stage">
        <div className="holo-keypad-grid-3d grid grid-cols-3 gap-1.5 pb-1">
          {HOLO_KEYPAD_GRID_KEYS.map((key) => (
            <button
              key={key.id}
              type="button"
              data-testid={`keypad-key-${key.value}`}
              onClick={() => handleKeyPress(key.value)}
              aria-label={`Keypad ${key.label}`}
              className="holo-key-3d flex flex-col items-center justify-center rounded-xl py-1.5 text-center"
            >
              <span className="font-mono text-sm font-semibold leading-none text-sky-100 tabular-nums">
                {key.label}
              </span>
              {key.subLabel && (
                <span className="mt-0.5 font-mono text-[8px] tracking-widest text-sky-300/60">
                  {key.subLabel}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Tactile Keypad Control Footer */}
      <div className="mt-2 grid grid-cols-4 gap-1.5">
        <button
          type="button"
          onClick={handleBackspace}
          aria-label="Backspace keypad input"
          className="holo-key-3d inline-flex items-center justify-center rounded-lg py-1.5 text-xs text-slate-200"
        >
          <Delete className="h-3.5 w-3.5" aria-hidden="true" />
        </button>

        <button
          type="button"
          onClick={handleClear}
          className="holo-key-3d inline-flex items-center justify-center rounded-lg py-1.5 font-mono text-[10.5px] font-medium text-amber-200"
        >
          CLR
        </button>

        <button
          type="button"
          disabled={!value.trim()}
          onClick={() => handleDispatch('plan')}
          className="holo-key-3d inline-flex items-center justify-center gap-1 rounded-lg py-1.5 text-[10.5px] font-medium text-sky-200 disabled:opacity-40 disabled:pointer-events-none"
        >
          <ListChecks className="h-3 w-3 shrink-0" aria-hidden="true" />
          Plan
        </button>

        <button
          type="button"
          disabled={!value.trim()}
          onClick={() => handleDispatch('direct')}
          data-testid="keypad-run-button"
          className="inline-flex items-center justify-center gap-1 rounded-lg border border-teal-400/55 bg-teal-500/20 py-1.5 text-[10.5px] font-semibold text-teal-100 hover:bg-teal-500/30 disabled:opacity-40 disabled:pointer-events-none transition-colors"
        >
          <CornerDownLeft className="h-3 w-3 shrink-0" aria-hidden="true" />
          Run
        </button>
      </div>
    </div>
  );
};
