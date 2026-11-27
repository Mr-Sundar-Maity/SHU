import React, { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowUpRight,
  AudioWaveform,
  Bell,
  Check,
  Database,
  GitBranch,
  Mail,
  Play,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react';
import { useShu } from '../context/ShuContext';
import type { ShuTab } from '../types/shu';
import { HOLO_COLOR_THEMES, getHoloColorTheme } from '../utils/colorTheme';
import {
  RADIAL_CORE_CX,
  RADIAL_CORE_CY,
  RADIAL_CORE_RING_RADIUS,
  RADIAL_NODE_SPECS,
  RADIAL_VIEWBOX_HEIGHT,
  RADIAL_VIEWBOX_WIDTH,
  computeMeasuredRadialGeometry,
  computeRadialNavNodes,
  type MeasuredRadialStageGeometry,
  type RadialSocketInput,
} from '../utils/radialNav';

const TAB_ICONS: Record<
  ShuTab,
  React.ComponentType<{ className?: string; 'aria-hidden'?: boolean }>
> = {
  assistant: AudioWaveform,
  memory: Database,
  reminders: Bell,
  communications: Mail,
  workflows: GitBranch,
  settings: SlidersHorizontal,
  privacy: ShieldCheck,
};

export const RadialOrbitNav: React.FC = () => {
  const {
    activeTab,
    setActiveTab,
    assistantState,
    transcript,
    memories,
    reminders,
    completeReminder,
    draft,
    whatsappContacts,
    workflows,
    replayWorkflow,
    settings,
    updateSetting,
    bridgeStatus,
  } = useShu();

  const [hoveredTab, setHoveredTab] = useState<ShuTab | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<Partial<Record<ShuTab, HTMLDivElement | null>>>({});
  const fallbackNodes = useMemo(() => computeRadialNavNodes(), []);
  const [measuredGeometry, setMeasuredGeometry] = useState<MeasuredRadialStageGeometry | null>(null);
  const activeTheme = getHoloColorTheme(settings.colorTheme);

  const measureConnections = useCallback(() => {
    const stageEl = stageRef.current;
    if (!stageEl) return;
    const stageRect = stageEl.getBoundingClientRect();
    if (stageRect.width < 100 || stageRect.height < 100) return;

    const sockets: RadialSocketInput[] = [];
    for (const spec of RADIAL_NODE_SPECS) {
      const cardEl = cardRefs.current[spec.id];
      if (!cardEl) continue;
      const cardRect = cardEl.getBoundingClientRect();
      if (cardRect.width <= 0 || cardRect.height <= 0) continue;
      const anchorX =
        spec.side === 'left'
          ? cardRect.right - stageRect.left
          : cardRect.left - stageRect.left;
      const anchorY = cardRect.top + cardRect.height / 2 - stageRect.top;
      sockets.push({
        id: spec.id,
        label: spec.label,
        side: spec.side,
        anchorX,
        anchorY,
      });
    }

    if (sockets.length === RADIAL_NODE_SPECS.length) {
      setMeasuredGeometry(
        computeMeasuredRadialGeometry(stageRect.width, stageRect.height, sockets)
      );
    }
  }, []);

  useLayoutEffect(() => {
    measureConnections();
    const raf = window.requestAnimationFrame(measureConnections);
    const stageEl = stageRef.current;
    let observer: ResizeObserver | null = null;
    if (stageEl && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        measureConnections();
      });
      observer.observe(stageEl);
      for (const spec of RADIAL_NODE_SPECS) {
        const cardEl = cardRefs.current[spec.id];
        if (cardEl) observer.observe(cardEl);
      }
    }
    window.addEventListener('resize', measureConnections);
    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener('resize', measureConnections);
      observer?.disconnect();
    };
  }, [
    measureConnections,
    assistantState,
    transcript.length,
    memories.length,
    reminders.length,
    draft.recipient,
    draft.subject,
    draft.message,
    workflows.length,
    settings.colorTheme,
    settings.voiceLanguage,
  ]);

  const approvedMemories = useMemo(
    () => memories.filter((m) => m.approved),
    [memories]
  );
  const scheduledReminders = useMemo(
    () => reminders.filter((r) => r.status === 'Scheduled' || r.status === 'Snoozed'),
    [reminders]
  );
  const approvedWorkflows = useMemo(
    () => workflows.filter((w) => w.status === 'Approved'),
    [workflows]
  );
  const pendingWorkflows = useMemo(
    () => workflows.filter((w) => w.status === 'Pending approval'),
    [workflows]
  );
  const latestMessage = transcript[transcript.length - 1];

  const renderPanelContent = (id: ShuTab) => {
    switch (id) {
      case 'assistant': {
        const label =
          assistantState === 'ready'
            ? 'Core Online'
            : assistantState === 'listening'
            ? 'Listening'
            : assistantState === 'thinking'
            ? 'Synthesizing'
            : assistantState === 'speaking'
            ? 'Speaking'
            : 'Halted';
        return (
          <div className="space-y-1 text-[11px] leading-snug">
            <div className="flex items-center justify-between font-mono text-[10px]">
              <span className="text-teal-300">{label}</span>
              <span className="text-slate-400 tabular-nums">{transcript.length} msgs</span>
            </div>
            <p className="truncate text-slate-300/90">
              {latestMessage?.text ?? 'Ready for voice or text command.'}
            </p>
          </div>
        );
      }

      case 'memory':
        return (
          <div className="space-y-1 text-[11px] leading-snug">
            <div className="flex items-center justify-between font-mono text-[10px]">
              <span className="text-sky-300">{approvedMemories.length} approved</span>
              <span className="text-slate-400">Indexed</span>
            </div>
            <ul className="space-y-0.5 text-slate-300/90">
              {approvedMemories.slice(0, 2).map((m) => (
                <li key={m.id} className="truncate">
                  <span className="font-mono text-[10px] text-cyan-300/80 mr-1">
                    {m.type}:
                  </span>
                  {m.content}
                </li>
              ))}
              {approvedMemories.length === 0 && (
                <li className="text-slate-500">No approved memories stored.</li>
              )}
            </ul>
          </div>
        );

      case 'reminders':
        return (
          <div className="space-y-1 text-[11px] leading-snug">
            <div className="flex items-center justify-between font-mono text-[10px]">
              <span className="text-teal-300">{scheduledReminders.length} scheduled</span>
              <span className="text-slate-400">Local queue</span>
            </div>
            <div className="space-y-1">
              {scheduledReminders.slice(0, 2).map((r) => (
                <div key={r.id} className="flex items-center justify-between gap-1.5">
                  <span className="min-w-0 flex-1 truncate text-slate-300/90">
                    <span className="font-mono text-[10px] text-sky-300 mr-1">
                      {r.due.slice(11, 16) || r.due}
                    </span>
                    {r.reminder}
                  </span>
                  <button
                    type="button"
                    aria-label={`Complete reminder ${r.reminder}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      completeReminder(r.id);
                    }}
                    className="shrink-0 rounded border border-teal-400/35 bg-teal-500/10 px-1.5 py-0.5 font-mono text-[10px] text-teal-200 hover:bg-teal-500/25"
                  >
                    <Check className="h-2.5 w-2.5" aria-hidden="true" />
                  </button>
                </div>
              ))}
              {scheduledReminders.length === 0 && (
                <p className="text-slate-500">No active reminders queued.</p>
              )}
            </div>
          </div>
        );

      case 'communications':
        return (
          <div className="space-y-1 text-[11px] leading-snug">
            <div className="flex items-center justify-between font-mono text-[10px]">
              <span className="text-sky-300">{draft.channel} draft</span>
              <span className="text-slate-400 tabular-nums">
                {whatsappContacts.length} contacts
              </span>
            </div>
            <p className="truncate text-slate-300/90">
              {draft.recipient
                ? `To ${draft.recipient}: ${draft.subject || draft.message || 'Draft open'}`
                : `Contacts: ${whatsappContacts.map((c) => c.name).join(', ')}`}
            </p>
          </div>
        );

      case 'workflows':
        return (
          <div className="space-y-1 text-[11px] leading-snug">
            <div className="flex items-center justify-between font-mono text-[10px]">
              <span className="text-teal-300">{approvedWorkflows.length} approved</span>
              <span className="text-slate-400">{pendingWorkflows.length} pending</span>
            </div>
            <div className="space-y-1">
              {workflows.slice(0, 2).map((wf) => (
                <div key={wf.id} className="flex items-center justify-between gap-1.5">
                  <span className="min-w-0 flex-1 truncate text-slate-300/90">
                    {wf.name}
                  </span>
                  {wf.status === 'Approved' ? (
                    <button
                      type="button"
                      aria-label={`Run ${wf.name}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        replayWorkflow(wf.id);
                      }}
                      className="inline-flex shrink-0 items-center gap-0.5 rounded border border-sky-400/35 bg-sky-500/15 px-1.5 py-0.5 font-mono text-[10px] text-sky-200 hover:bg-sky-500/25"
                    >
                      <Play className="h-2.5 w-2.5" aria-hidden="true" />
                      Run
                    </button>
                  ) : (
                    <span className="shrink-0 font-mono text-[10px] text-slate-500">
                      {wf.status === 'Pending approval' ? 'Pending' : 'Revoked'}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        );

      case 'settings':
      default: {
        const shortLang = settings.voiceLanguage.match(/\(([^)]+)\)/)?.[1] ?? settings.voiceLanguage;
        return (
          <div className="space-y-1.5 text-[11px] leading-snug">
            <div className="flex items-center justify-between gap-1 font-mono text-[10px]">
              <span className="truncate text-sky-300">{activeTheme.name}</span>
              <span
                className={`shrink-0 ${
                  bridgeStatus === 'connected' ? 'text-teal-300' : 'text-slate-400'
                }`}
              >
                {shortLang}
              </span>
            </div>
            <div className="flex items-center justify-between gap-1.5">
              <span className="shrink-0 font-mono text-[10px] text-slate-400">
                Theme
              </span>
              <div
                className="flex items-center gap-1.5"
                onClick={(e) => e.stopPropagation()}
              >
                {HOLO_COLOR_THEMES.map((theme) => {
                  const isCurrent = settings.colorTheme === theme.id;
                  return (
                    <button
                      key={`hud-theme-${theme.id}`}
                      type="button"
                      aria-label={`Switch theme to ${theme.name}`}
                      title={theme.name}
                      onClick={(e) => {
                        e.stopPropagation();
                        updateSetting('colorTheme', theme.id);
                      }}
                      className={`h-3.5 w-3.5 rounded-full border transition-transform ${
                        isCurrent
                          ? 'scale-125 border-white'
                          : 'border-white/30 opacity-80 hover:opacity-100'
                      }`}
                      style={{
                        background: theme.gradientCss,
                        boxShadow: isCurrent ? `0 0 8px ${theme.primaryCss}` : undefined,
                      }}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        );
      }
    }
  };

  const activeNodes = measuredGeometry?.nodes ?? fallbackNodes;
  const leftNodes = activeNodes.filter((n) => n.side === 'left');
  const rightNodes = activeNodes.filter((n) => n.side === 'right');

  const renderDesktopCard = (node: (typeof activeNodes)[number]) => {
    const Icon = TAB_ICONS[node.id];
    const active = activeTab === node.id;
    return (
      <div
        key={node.id}
        ref={(el) => {
          cardRefs.current[node.id] = el;
        }}
        role="button"
        tabIndex={0}
        data-radial-node={node.id}
        data-hud-always-visible="true"
        onClick={() => setActiveTab(node.id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setActiveTab(node.id);
          }
        }}
        onMouseEnter={() => setHoveredTab(node.id)}
        onMouseLeave={() => setHoveredTab((curr) => (curr === node.id ? null : curr))}
        aria-label={`Open ${node.label} view`}
        className={`pointer-events-auto group flex flex-col justify-between rounded-2xl px-3.5 py-2.5 text-left transition-all duration-150 cursor-pointer focus-visible:outline-2 focus-visible:outline-sky-400 ${
          active
            ? 'holo-surface border-sky-400/65 shadow-[0_0_24px_rgba(var(--holo-primary-rgb),0.22)]'
            : 'holo-surface-subtle hover:border-white/35 hover:shadow-[0_14px_34px_rgba(2,6,18,0.58),0_0_20px_rgba(var(--holo-primary-rgb),0.16)]'
        }`}
      >
        <div className="mb-1 flex items-center justify-between gap-2 border-b border-white/12 pb-1">
          <div className="flex items-center gap-1.5 min-w-0">
            <Icon
              className={`h-3.5 w-3.5 shrink-0 ${
                active ? 'text-cyan-300' : 'text-sky-400/85'
              }`}
              aria-hidden={true}
            />
            <span className="font-display text-xs font-semibold tracking-wide text-sky-100 truncate">
              {node.label}
            </span>
          </div>
          <ArrowUpRight
            className="h-3 w-3 shrink-0 text-slate-400 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-sky-300"
            aria-hidden="true"
          />
        </div>
        {renderPanelContent(node.id)}
      </div>
    );
  };

  return (
    <>
      {/* Desktop Always-Visible Live HUD Panels Connected Around Center 3D Model */}
      <div
        ref={stageRef}
        data-testid="radial-orbit-nav"
        className="hidden lg:block absolute inset-x-0 top-[88px] bottom-[72px] pointer-events-none"
      >
        <svg
          aria-hidden="true"
          viewBox={`0 0 ${measuredGeometry?.width ?? RADIAL_VIEWBOX_WIDTH} ${
            measuredGeometry?.height ?? RADIAL_VIEWBOX_HEIGHT
          }`}
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full pointer-events-none"
        >
          {/* Central Core Perimeter Coupling Ring */}
          <ellipse
            cx={measuredGeometry?.coreCx ?? RADIAL_CORE_CX}
            cy={measuredGeometry?.coreCy ?? RADIAL_CORE_CY}
            rx={measuredGeometry?.coreRadius ?? RADIAL_CORE_RING_RADIUS}
            ry={
              measuredGeometry
                ? measuredGeometry.coreRadius
                : RADIAL_CORE_RING_RADIUS * 1.04
            }
            fill="none"
            stroke={`rgba(${activeTheme.primaryRgb}, 0.24)`}
            strokeWidth="1.25"
            strokeDasharray="6 8"
          />

          {activeNodes.map((node) => {
            const isHighlighted = activeTab === node.id || hoveredTab === node.id;
            const strokeColor =
              assistantState === 'stopped'
                ? 'rgba(244, 63, 94, 0.35)'
                : isHighlighted
                ? `rgba(${activeTheme.accentRgb}, 0.88)`
                : `rgba(${activeTheme.primaryRgb}, 0.36)`;

            return (
              <g key={`link-${node.id}`}>
                <path
                  data-connector-path="true"
                  d={node.pathD}
                  fill="none"
                  stroke={strokeColor}
                  strokeWidth={isHighlighted ? 1.8 : 1.25}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                />
                <path
                  data-connector-path="true"
                  d={node.pathD}
                  fill="none"
                  stroke={
                    isHighlighted
                      ? `rgba(${activeTheme.softRgb}, 0.92)`
                      : `rgba(${activeTheme.primaryRgb}, 0.55)`
                  }
                  strokeWidth={isHighlighted ? 2 : 1.25}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                  className="holo-link-flow"
                />
                <circle
                  cx={node.coreAnchorX}
                  cy={node.coreAnchorY}
                  r={isHighlighted ? 4.2 : 3}
                  fill={isHighlighted ? activeTheme.accentCss : activeTheme.primaryCss}
                  fillOpacity={isHighlighted ? 0.95 : 0.7}
                />
                {/* Hardware socket collar + center pin anchored directly on card border */}
                <circle
                  cx={node.nodeAnchorX}
                  cy={node.nodeAnchorY}
                  r={isHighlighted ? 6.5 : 5.2}
                  fill="none"
                  stroke={isHighlighted ? activeTheme.accentCss : activeTheme.primaryCss}
                  strokeOpacity={isHighlighted ? 0.75 : 0.4}
                  strokeWidth="1"
                />
                <circle
                  cx={node.nodeAnchorX}
                  cy={node.nodeAnchorY}
                  r={isHighlighted ? 3.8 : 2.8}
                  fill={isHighlighted ? activeTheme.accentCss : activeTheme.primaryCss}
                  fillOpacity={isHighlighted ? 1 : 0.85}
                />
              </g>
            );
          })}
        </svg>

        {/* Left 3 Always-Visible HUD Panels: Assistant, Memory, Reminders */}
        <div
          aria-label="Left live HUD modules"
          className="absolute left-[0.5%] inset-y-3 w-[25.5%] flex flex-col justify-between gap-2 pointer-events-none"
        >
          {leftNodes.map(renderDesktopCard)}
        </div>

        {/* Right 3 Always-Visible HUD Panels: Communications, Workflows, Settings */}
        <div
          aria-label="Right live HUD modules"
          className="absolute right-[0.5%] inset-y-3 w-[25.5%] flex flex-col justify-between gap-2 pointer-events-none"
        >
          {rightNodes.map(renderDesktopCard)}
        </div>
      </div>

      {/* Compact Always-Visible Live HUD Grid for Mobile & Tablet Viewports */}
      <div
        aria-label="Mobile live HUD modules"
        className="lg:hidden relative z-10 mx-auto my-2 grid w-full max-w-md grid-cols-1 sm:grid-cols-2 gap-2 px-4 pointer-events-auto"
      >
        {activeNodes.map((node) => {
          const Icon = TAB_ICONS[node.id];
          const active = activeTab === node.id;
          return (
            <div
              key={`mob-${node.id}`}
              role="button"
              tabIndex={0}
              onClick={() => setActiveTab(node.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setActiveTab(node.id);
                }
              }}
              aria-label={`Open ${node.label} view`}
              className={`flex flex-col gap-1 rounded-2xl px-3 py-2 text-left transition-all ${
                active
                  ? 'holo-surface border-sky-400/60 shadow-[0_0_20px_rgba(var(--holo-primary-rgb),0.2)]'
                  : 'holo-surface-subtle hover:border-white/35'
              }`}
            >
              <div className="flex items-center justify-between gap-2 border-b border-white/12 pb-1">
                <div className="flex items-center gap-1.5">
                  <Icon className="h-3.5 w-3.5 text-sky-300" aria-hidden={true} />
                  <span className="font-display text-xs font-semibold text-sky-100">
                    {node.label}
                  </span>
                </div>
                <ArrowUpRight className="h-3 w-3 text-slate-400" aria-hidden="true" />
              </div>
              {renderPanelContent(node.id)}
            </div>
          );
        })}
      </div>
    </>
  );
};
