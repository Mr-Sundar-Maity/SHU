import React, { useMemo } from 'react';
import { History, Trash2, X } from 'lucide-react';
import { useShu } from '../context/ShuContext';
import {
  INITIAL_VOICE_HISTORY_LOGS,
  MAX_DRAWER_VOICE_COMMANDS,
  buildVoiceCommandLogs,
  getRecentVoiceCommands,
} from '../utils/commandHistory';

interface CommandHistoryDrawerProps {
  open: boolean;
  onClose: () => void;
  onSelectCommand: (commandText: string) => void;
}

export const CommandHistoryDrawer: React.FC<CommandHistoryDrawerProps> = ({
  open,
  onClose,
  onSelectCommand,
}) => {
  const { transcript, logsCleared, clearedVoiceIds, clearVoiceHistory } = useShu();

  const recentCommands = useMemo(() => {
    const logs = buildVoiceCommandLogs(
      transcript,
      logsCleared ? [] : INITIAL_VOICE_HISTORY_LOGS,
      clearedVoiceIds
    );
    return getRecentVoiceCommands(logs, MAX_DRAWER_VOICE_COMMANDS);
  }, [clearedVoiceIds, logsCleared, transcript]);

  return (
    <aside
      aria-label="Recent voice command history drawer"
      aria-hidden={!open}
      data-testid="command-history-drawer"
      data-open={open ? 'true' : 'false'}
      className={`holo-popover fixed bottom-[68px] left-1/2 z-30 w-[calc(100%-1.5rem)] max-w-[380px] -translate-x-1/2 rounded-2xl px-4 py-3 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] ${
        open
          ? 'translate-y-0 opacity-100 pointer-events-auto'
          : 'translate-y-8 opacity-0 pointer-events-none'
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2 border-b border-white/12 pb-1.5">
        <div className="flex items-center gap-1.5">
          <History className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
          <h2 className="font-mono text-[11px] font-medium tracking-wider text-sky-100">
            Voice Command History
          </h2>
          <span className="font-mono text-[10px] text-slate-400 tabular-nums">
            ({recentCommands.length}/{MAX_DRAWER_VOICE_COMMANDS})
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            data-testid="clear-history-button"
            onClick={clearVoiceHistory}
            disabled={recentCommands.length === 0}
            className="inline-flex items-center gap-1 rounded-md border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 font-mono text-[10px] font-medium text-rose-100 transition-colors hover:bg-rose-500/25 disabled:opacity-40 disabled:pointer-events-none"
          >
            <Trash2 className="h-2.5 w-2.5" aria-hidden="true" />
            Clear History
          </button>

          <button
            type="button"
            data-testid="close-history-drawer"
            onClick={onClose}
            aria-label="Close voice command history drawer"
            className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-white/15 bg-white/5 text-slate-300 transition-colors hover:border-sky-400/50 hover:text-white"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>

      {recentCommands.length === 0 ? (
        <p
          data-testid="command-history-empty"
          className="py-3 text-center font-mono text-xs text-slate-400"
        >
          No recent voice commands recorded.
        </p>
      ) : (
        <ul className="space-y-1 max-h-44 overflow-y-auto shu-scroll pr-0.5">
          {recentCommands.map((item, idx) => (
            <li key={item.id} data-drawer-command-id={item.id}>
              <button
                type="button"
                onClick={() => {
                  onSelectCommand(item.text);
                  onClose();
                }}
                className="flex w-full items-center justify-between gap-2.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-left font-mono text-xs transition-colors hover:border-sky-400/45 hover:bg-sky-500/15"
              >
                <span className="text-[10px] text-slate-500 tabular-nums shrink-0">
                  #{idx + 1} · {item.timestamp}
                </span>
                <span className="min-w-0 flex-1 truncate text-sky-100">
                  {item.text}
                </span>
                <span className="shrink-0 text-[10px] text-teal-300">
                  {item.status === 'recognized' ? 'voice' : 'core'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
};
