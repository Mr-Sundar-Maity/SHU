import React, { useEffect, useRef } from 'react';
import {
  Activity,
  Mic,
  MicOff,
  ShieldCheck,
  Trash2,
  Volume2,
  VolumeX,
} from 'lucide-react';
import { useShu } from '../context/ShuContext';
import { clampContextMenuPosition } from '../utils/contextMenu';

interface HoloContextMenuProps {
  open: boolean;
  x: number;
  y: number;
  onClose: () => void;
}

const MENU_WIDTH = 228;
const MENU_HEIGHT = 216;

export const HoloContextMenu: React.FC<HoloContextMenuProps> = ({
  open,
  x,
  y,
  onClose,
}) => {
  const {
    isMuted,
    quietMode,
    isListening,
    setActiveTab,
    clearLogs,
    toggleAssistantMute,
    runSystemDiagnostic,
    toggleListening,
  } = useShu();

  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    const handlePointerDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('mousedown', handlePointerDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('mousedown', handlePointerDown);
    };
  }, [open, onClose]);

  if (!open) return null;

  const vw = typeof window !== 'undefined' ? window.innerWidth : 1440;
  const vh = typeof window !== 'undefined' ? window.innerHeight : 900;
  const pos = clampContextMenuPosition(x, y, MENU_WIDTH, MENU_HEIGHT, vw, vh, 12);
  const assistantMuted = isMuted && quietMode;

  const handleAction = (fn: () => void) => {
    fn();
    onClose();
  };

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label="Holographic quick actions"
      data-testid="holo-context-menu"
      style={{ left: `${pos.left}px`, top: `${pos.top}px`, width: `${MENU_WIDTH}px` }}
      onContextMenu={(e) => e.preventDefault()}
      className="holo-surface fixed z-50 flex flex-col gap-1 rounded-xl p-2 backdrop-blur-md pointer-events-auto shadow-[0_18px_48px_rgba(2,6,23,0.85)]"
    >
      <div className="flex items-center justify-between border-b border-sky-400/15 px-2.5 pb-1.5 pt-0.5">
        <span className="font-mono text-[10px] font-medium tracking-wider text-sky-300/90">
          Quick Actions
        </span>
        <span className="font-mono text-[10px] text-slate-500">SHU</span>
      </div>

      <button
        type="button"
        role="menuitem"
        onClick={() => handleAction(clearLogs)}
        className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-slate-200 transition-colors hover:bg-sky-500/15 hover:text-sky-100 focus-visible:outline-2 focus-visible:outline-sky-400"
      >
        <Trash2 className="h-3.5 w-3.5 text-sky-300 shrink-0" aria-hidden="true" />
        <span className="whitespace-nowrap">Clear Logs</span>
      </button>

      <button
        type="button"
        role="menuitem"
        onClick={() => handleAction(toggleAssistantMute)}
        className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-slate-200 transition-colors hover:bg-sky-500/15 hover:text-sky-100 focus-visible:outline-2 focus-visible:outline-sky-400"
      >
        {assistantMuted ? (
          <Volume2 className="h-3.5 w-3.5 text-teal-300 shrink-0" aria-hidden="true" />
        ) : (
          <VolumeX className="h-3.5 w-3.5 text-amber-300 shrink-0" aria-hidden="true" />
        )}
        <span className="whitespace-nowrap">
          {assistantMuted ? 'Unmute Assistant' : 'Mute Assistant'}
        </span>
      </button>

      <button
        type="button"
        role="menuitem"
        onClick={() => handleAction(runSystemDiagnostic)}
        className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-slate-200 transition-colors hover:bg-teal-500/15 hover:text-teal-100 focus-visible:outline-2 focus-visible:outline-teal-400"
      >
        <Activity className="h-3.5 w-3.5 text-teal-300 shrink-0" aria-hidden="true" />
        <span className="whitespace-nowrap">System Diagnostic</span>
      </button>

      <button
        type="button"
        role="menuitem"
        onClick={() => handleAction(() => setActiveTab('privacy'))}
        className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-slate-200 transition-colors hover:bg-sky-500/15 hover:text-sky-100 focus-visible:outline-2 focus-visible:outline-sky-400"
      >
        <ShieldCheck className="h-3.5 w-3.5 text-cyan-300 shrink-0" aria-hidden="true" />
        <span className="whitespace-nowrap">Privacy Dashboard</span>
      </button>

      <div className="my-0.5 border-t border-sky-400/10" />

      <button
        type="button"
        role="menuitem"
        onClick={() => handleAction(toggleListening)}
        className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-slate-300 transition-colors hover:bg-sky-500/15 hover:text-sky-100 focus-visible:outline-2 focus-visible:outline-sky-400"
      >
        {isListening ? (
          <MicOff className="h-3.5 w-3.5 text-rose-300 shrink-0" aria-hidden="true" />
        ) : (
          <Mic className="h-3.5 w-3.5 text-cyan-300 shrink-0" aria-hidden="true" />
        )}
        <span className="whitespace-nowrap">
          {isListening ? 'Stop Listening' : 'Start Listening'}
        </span>
      </button>
    </div>
  );
};
