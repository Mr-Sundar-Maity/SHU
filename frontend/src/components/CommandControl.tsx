import React, { useState } from 'react';
import {
  Grid3x3,
  ListChecks,
  OctagonAlert,
  Play,
  Send,
  Star,
  TerminalSquare,
  X,
} from 'lucide-react';
import { useShu } from '../context/ShuContext';
import { HoloKeypad } from './HoloKeypad';

interface CommandControlProps {
  inputText: string;
  onInputChange: React.Dispatch<React.SetStateAction<string>>;
  className?: string;
}

export const CommandControl: React.FC<CommandControlProps> = ({
  inputText,
  onInputChange,
  className = '',
}) => {
  const {
    assistantState,
    isListening,
    audioLevel,
    sendCommand,
    triggerEmergencyStop,
    resumeAssistant,
    rateLastTask,
    hasLastTask,
  } = useShu();

  const [keypadOpen, setKeypadOpen] = useState(false);
  const [ratingOpen, setRatingOpen] = useState(false);
  const [ratingScore, setRatingScore] = useState(5);
  const [ratingNote, setRatingNote] = useState('');

  const handleSend = (mode: 'direct' | 'plan') => {
    const trimmed = inputText.trim();
    if (!trimmed) return;
    sendCommand(trimmed, mode);
    onInputChange('');
  };

  const handleRatingSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    rateLastTask(ratingScore, ratingNote);
    setRatingOpen(false);
    setRatingNote('');
  };

  return (
    <section
      aria-label="Command control"
      data-testid="command-control"
      className={`holo-surface relative flex flex-col rounded-2xl px-3.5 py-2.5 ${className}`}
    >
      {keypadOpen && (
        <HoloKeypad
          value={inputText}
          onChange={onInputChange}
          onSubmitCommand={(mode, commandText) => {
            sendCommand(commandText, mode);
            onInputChange('');
            setKeypadOpen(false);
          }}
          onClose={() => setKeypadOpen(false)}
        />
      )}

      <div className="mb-2 flex items-center justify-between gap-2 border-b border-white/12 pb-1.5">
        <div className="flex items-center gap-1.5">
          <TerminalSquare className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
          <h2 className="font-mono text-[11px] font-medium tracking-wider text-sky-200/95">
            Command Control
          </h2>
        </div>

        <div className="flex items-center gap-2">
          {isListening && (
            <div
              className="flex items-center gap-0.5"
              aria-label="Microphone input level"
            >
              {[0.35, 0.7, 1, 0.6, 0.4].map((weight, idx) => (
                <span
                  key={idx}
                  className="w-1 rounded-full bg-teal-400 transition-transform duration-100"
                  style={{
                    height: '12px',
                    transform: `scaleY(${Math.max(0.22, Math.min(1, audioLevel * weight * 1.6))})`,
                  }}
                />
              ))}
            </div>
          )}

          <button
            type="button"
            data-testid="toggle-holo-keypad"
            aria-expanded={keypadOpen}
            aria-label={keypadOpen ? 'Close virtual holographic keypad' : 'Open virtual holographic keypad'}
            onClick={() => setKeypadOpen((prev) => !prev)}
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors ${
              keypadOpen
                ? 'border-cyan-400/60 bg-cyan-500/20 text-cyan-100'
                : 'border-white/15 bg-white/5 text-sky-200 hover:border-sky-400/45 hover:bg-sky-500/15'
            }`}
          >
            <Grid3x3 className="h-3 w-3" aria-hidden="true" />
            <span>Keypad</span>
          </button>
        </div>
      </div>

      {ratingOpen && (
        <form
          onSubmit={handleRatingSubmit}
          data-testid="rate-task-drawer"
          className="mb-2 flex flex-col gap-2 rounded-lg border border-sky-400/25 bg-slate-950/90 p-2.5"
        >
          <div className="flex items-center justify-between gap-1.5">
            <span className="text-[11px] font-medium text-slate-300">Rate last task:</span>
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setRatingScore(n)}
                  aria-label={`Rate ${n} out of 5`}
                  className={`rounded px-2 py-0.5 text-[11px] font-mono transition-colors ${
                    ratingScore >= n
                      ? 'bg-sky-500/25 text-sky-200 border border-sky-400/50'
                      : 'bg-slate-800/70 text-slate-400 border border-slate-700'
                  }`}
                >
                  {n}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setRatingOpen(false)}
                aria-label="Close rating drawer"
                className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded border border-white/15 bg-white/5 text-slate-300 hover:text-white"
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              value={ratingNote}
              onChange={(e) => setRatingNote(e.target.value)}
              placeholder="Optional feedback note..."
              aria-label="Rating feedback note"
              className="holo-input min-w-0 flex-1 rounded-md px-2.5 py-1 text-xs"
            />
            <button
              type="submit"
              className="rounded-md bg-sky-500/25 border border-sky-400/50 px-2.5 py-1 text-[11px] font-medium text-sky-100 hover:bg-sky-500/35 whitespace-nowrap shrink-0"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setRatingOpen(false)}
              className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:text-slate-200 whitespace-nowrap shrink-0"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSend('direct');
        }}
        className="flex flex-col gap-2"
      >
        <div>
          <label htmlFor="shu-command-input" className="sr-only">
            Type a question or a task for SHU
          </label>
          <textarea
            id="shu-command-input"
            rows={2}
            value={inputText}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend('direct');
              }
            }}
            placeholder="Type a question or a task for SHU..."
            className="holo-input w-full resize-none rounded-lg px-3 py-2 text-xs text-slate-100 placeholder:text-slate-500 shu-scroll"
          />
        </div>

        <div className="grid grid-cols-2 gap-1.5">
          <button
            type="submit"
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-sky-500/25 border border-sky-400/50 px-2.5 py-1.5 text-xs font-medium text-sky-100 hover:bg-sky-500/35 transition-colors whitespace-nowrap"
          >
            <Send className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>Send</span>
          </button>

          <button
            type="button"
            onClick={() => handleSend('plan')}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700/80 bg-slate-900/75 px-2.5 py-1.5 text-xs font-medium text-slate-200 hover:border-sky-400/40 hover:text-sky-200 transition-colors whitespace-nowrap"
          >
            <ListChecks className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>Plan task</span>
          </button>

          <button
            type="button"
            disabled={!hasLastTask}
            onClick={() => rateLastTask(0)}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700/80 bg-slate-900/75 px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:text-sky-200 disabled:opacity-45 disabled:pointer-events-none transition-colors whitespace-nowrap"
          >
            <Star className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>Rate last task</span>
          </button>

          {assistantState === 'stopped' ? (
            <button
              type="button"
              onClick={resumeAssistant}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-teal-400/50 bg-teal-500/20 px-2.5 py-1.5 text-xs font-medium text-teal-100 hover:bg-teal-500/30 transition-colors whitespace-nowrap"
            >
              <Play className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span>Resume</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={triggerEmergencyStop}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-rose-500/55 bg-rose-600/25 px-2.5 py-1.5 text-xs font-medium text-rose-100 hover:bg-rose-600/40 transition-colors whitespace-nowrap"
            >
              <OctagonAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span>Emergency stop</span>
            </button>
          )}
        </div>
      </form>
    </section>
  );
};
