import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import { ShuProvider, useShu } from './context/ShuContext';
import { HologramCore } from './components/HologramCore';
import { TopBar } from './components/TopBar';
import { AssistantView } from './components/AssistantView';
import { MemoryView } from './components/MemoryView';
import { RemindersView } from './components/RemindersView';
import { CommunicationsView } from './components/CommunicationsView';
import { WorkflowsView } from './components/WorkflowsView';
import { SettingsView } from './components/SettingsView';
import { PrivacyDashboardView } from './components/PrivacyDashboardView';

const ShuShell: React.FC = () => {
  const { activeTab, setActiveTab, assistantState, notification, clearNotification, settings, statusBanner } =
    useShu();

  useEffect(() => {
    if (!notification) return;
    const id = window.setTimeout(clearNotification, 4200);
    return () => window.clearTimeout(id);
  }, [notification, clearNotification]);

  useEffect(() => {
    if (activeTab === 'assistant') return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setActiveTab('assistant');
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activeTab, setActiveTab]);

  return (
    <div
      data-shu-state={assistantState}
      data-active-tab={activeTab}
      data-holo-theme={settings.colorTheme}
      className="relative flex h-screen w-screen flex-col overflow-hidden bg-[#060911] text-slate-100"
    >
      {/* Persistent 3D Holographic Viewport */}
      <HologramCore />

      {/* Global Horizontal Holographic Scanline Overlay */}
      <div aria-hidden="true" className="holo-scanline-overlay" />

      {/* Top 3-Zone Navigation Bar */}
      <TopBar />

      {/* Transient Notification Bar */}
      {notification && (
        <div
          role="status"
          className={`fixed right-4 left-4 md:left-auto md:right-5 top-28 md:top-16 z-30 flex items-center justify-between gap-3 rounded-xl px-4 py-2.5 text-xs shadow-lg border ${
            notification.tone === 'error'
              ? 'border-rose-500/50 bg-[#1a0b12]/95 text-rose-100'
              : notification.tone === 'success'
              ? 'border-teal-400/45 bg-[#07181d]/95 text-teal-100'
              : 'border-sky-400/40 bg-[#091324]/95 text-sky-100'
          }`}
        >
          <span>{notification.message}</span>
          <button
            type="button"
            onClick={clearNotification}
            aria-label="Dismiss notification"
            className="text-slate-400 hover:text-white"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      )}

      {/* Active Workspace View */}
      <main className="relative z-10 flex-1 min-h-0 overflow-hidden">
        {activeTab === 'assistant' && <AssistantView />}
        {activeTab === 'memory' && <MemoryView />}
        {activeTab === 'reminders' && <RemindersView />}
        {activeTab === 'communications' && <CommunicationsView />}
        {activeTab === 'workflows' && <WorkflowsView />}
        {activeTab === 'settings' && <SettingsView />}
        {activeTab === 'privacy' && <PrivacyDashboardView />}
      </main>
      {activeTab !== 'assistant' && <div role="status" className="relative z-20 border-t border-sky-400/15 bg-slate-950 px-6 py-2 text-xs text-sky-200">{statusBanner}</div>}
    </div>
  );
};

export default function App() {
  return (
    <ShuProvider>
      <ShuShell />
    </ShuProvider>
  );
}
