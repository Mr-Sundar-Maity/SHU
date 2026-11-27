import React, { useEffect, useMemo, useRef } from 'react';
import { Terminal } from 'lucide-react';
import { useShu } from '../context/ShuContext';
import {
  INITIAL_VOICE_HISTORY_LOGS,
  buildVoiceCommandLogs,
} from '../utils/commandHistory';

interface CommandHistoryViewProps {
  onSelectCommand?: (commandText: string) => void;
  className?: string;
}

export const CommandHistoryView: React.FC<CommandHistoryViewProps> = ({
  onSelectCommand,
  className = '',
}) => {
  const { transcript, assistantState, logsCleared, clearedVoiceIds } = useShu();
  const scrollEndRef = useRef<HTMLDivElement | null>(null);

  const logs = useMemo(
    () =>
      buildVoiceCommandLogs(
        transcript,
        logsCleared ? [] : INITIAL_VOICE_HISTORY_LOGS,
        clearedVoiceIds
      ),
    [clearedVoiceIds, logsCleared, transcript]
  );

  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs.length]);

  return (
    <section
      aria-label="Recent voice command logs"
      data-testid="command-history-view"
      className={`holo-terminal holo-float-card holo-float-card--delayed flex flex-col rounded-2xl px-3.5 py-2.5 ${className}`}
    >
      <div className="mb-1.5 flex items-center justify-between gap-2 border-b border-white/12 pb-1">
        <div className="flex items-center gap-1.5">
          <Terminal className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
          <h2 className="font-mono text-[11px] font-medium tracking-wider text-sky-200/95">
            Logs
          </h2>
        </div>
        <span className="font-mono text-[10px] text-slate-400 tabular-nums">
          {logs.length} {logs.length === 1 ? 'entry' : 'entries'}
        </span>
      </div>

      <div
        role="log"
        aria-live="polite"
        className="h-24 max-h-28 flex-1 overflow-y-auto pr-1 font-mono text-xs shu-scroll space-y-1"
      >
        {logs.length === 0 ? (
          <p className="text-slate-500">
            &gt; Awaiting recognized voice input...
          </p>
        ) : (
          logs.map((item) => {
            const rowContent = (
              <>
                <span className="text-slate-500 shrink-0 tabular-nums">
                  [{item.timestamp}]
                </span>
                <span
                  aria-hidden="true"
                  className={
                    item.status === 'recognized' ? 'text-teal-300' : 'text-sky-400'
                  }
                >
                  &gt;
                </span>
                <span className="min-w-0 flex-1 truncate text-sky-100/95">
                  {item.text}
                </span>
                <span className="shrink-0 text-[10px] text-cyan-300/70">
                  {item.status === 'recognized' ? 'voice' : 'core'}
                </span>
              </>
            );

            if (onSelectCommand) {
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelectCommand(item.text)}
                  title={`Load "${item.text}" into command input`}
                  className="flex w-full items-baseline gap-2 rounded px-1.5 py-0.5 text-left transition-colors hover:bg-sky-500/12 focus-visible:outline-1 focus-visible:outline-sky-400"
                >
                  {rowContent}
                </button>
              );
            }

            return (
              <div key={item.id} className="flex items-baseline gap-2 px-1.5 py-0.5">
                {rowContent}
              </div>
            );
          })
        )}
        <div className="flex items-center gap-1.5 px-1.5 pt-0.5 text-[11px] text-sky-400/75">
          <span aria-hidden="true">&gt;</span>
          <span className="text-slate-500">
            {assistantState === 'listening'
              ? 'listening stream open_'
              : assistantState === 'stopped'
              ? 'stream halted_'
              : 'ready_'}
          </span>
        </div>
        <div ref={scrollEndRef} />
      </div>
    </section>
  );
};
