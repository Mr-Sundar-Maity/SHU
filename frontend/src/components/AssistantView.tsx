import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  ArrowDown,
  History,
  MessageSquareText,
  Mic,
  MicOff,
  Radio,
  ShieldCheck,
  Volume2,
  VolumeX,
} from 'lucide-react';
import { useShu } from '../context/ShuContext';
import { shouldAutoScrollTranscript } from '../utils/commandHistory';
import { getHoloColorTheme } from '../utils/colorTheme';
import {
  DATA_GRID_COLUMNS,
  DATA_GRID_NODES,
  DATA_GRID_RIPPLE_DURATION_MS,
  DATA_GRID_ROWS,
  DATA_GRID_STREAMS,
  computeGridCellRippleDelayMs,
  getDataGridProfile,
} from '../utils/dataGrid';
import {
  computeOuterCardConnectors,
  type InnerCardObstacle,
  type OuterCardConnector,
  type OuterCardId,
  type OuterCardSocketInput,
} from '../utils/radialNav';
import { CommandControl } from './CommandControl';
import { CommandHistoryDrawer } from './CommandHistoryDrawer';
import { CommandHistoryView } from './CommandHistoryView';
import { HoloContextMenu } from './HoloContextMenu';
import { NeuralDataStreamPanel } from './NeuralDataStreamPanel';
import { NeuralSignalCard } from './NeuralSignalCard';
import { RadialOrbitNav } from './RadialOrbitNav';
import { SystemStatusView } from './SystemStatusView';
import { VoiceVisualizer } from './VoiceVisualizer';
import { WakeWordOverlay } from './WakeWordOverlay';
import { WeatherForecastCard } from './WeatherForecastCard';

export const AssistantView: React.FC = () => {
  const {
    setActiveTab,
    assistantState,
    isListening,
    isMuted,
    dataGridRippleSeq,
    statusBanner,
    transcript,
    toggleListening,
    toggleMute,
    quietMode,
    setQuietMode,
    settings,
  } = useShu();

  const [inputText, setInputText] = useState('');
  const [logsOpen, setLogsOpen] = useState(true);
  const [transcriptOpen, setTranscriptOpen] = useState(true);
  const [statusOpen, setStatusOpen] = useState(true);
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const [autoScrollPinned, setAutoScrollPinned] = useState(true);
  const [activeRippleSeq, setActiveRippleSeq] = useState(0);
  const [hoveredOuterCard, setHoveredOuterCard] = useState<OuterCardId | null>(null);
  const [outerConnectors, setOuterConnectors] = useState<{
    width: number;
    height: number;
    items: OuterCardConnector[];
  } | null>(null);
  const [contextMenu, setContextMenu] = useState<{ open: boolean; x: number; y: number }>({
    open: false,
    x: 0,
    y: 0,
  });

  const viewRef = useRef<HTMLDivElement | null>(null);
  const outerCardRefs = useRef<Partial<Record<OuterCardId, HTMLElement | null>>>({});
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);
  const transcriptContentRef = useRef<HTMLDivElement | null>(null);
  const autoScrollEnabledRef = useRef(true);

  const activeTheme = getHoloColorTheme(settings.colorTheme);
  const lastEntry = transcript[transcript.length - 1];
  const lastEntryText = lastEntry?.text ?? '';
  const isStreaming = assistantState === 'thinking' || assistantState === 'speaking';

  const scrollTranscriptToBottom = useCallback(() => {
    const el = transcriptScrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  useEffect(() => {
    if (dataGridRippleSeq <= 0) return;
    setActiveRippleSeq(dataGridRippleSeq);
    const timer = window.setTimeout(() => {
      setActiveRippleSeq((curr) => (curr === dataGridRippleSeq ? 0 : curr));
    }, DATA_GRID_RIPPLE_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [dataGridRippleSeq]);

  // Automatically re-arm sticky auto-scroll when the user sends a new command
  useEffect(() => {
    if (lastEntry?.role === 'user') {
      autoScrollEnabledRef.current = true;
      setAutoScrollPinned(true);
    }
  }, [lastEntry?.id, lastEntry?.role]);

  // Keep latest streamed tokens visible in Transcript panel
  useEffect(() => {
    if (!transcriptOpen || !autoScrollEnabledRef.current) return;
    scrollTranscriptToBottom();
    const raf = window.requestAnimationFrame(scrollTranscriptToBottom);
    return () => window.cancelAnimationFrame(raf);
  }, [transcript.length, lastEntryText, transcriptOpen, scrollTranscriptToBottom]);

  // Also observe inner content height changes during multi-line token streaming
  useEffect(() => {
    if (!transcriptOpen || typeof ResizeObserver === 'undefined') return;
    const contentEl = transcriptContentRef.current;
    if (!contentEl) return;

    const observer = new ResizeObserver(() => {
      if (autoScrollEnabledRef.current) {
        scrollTranscriptToBottom();
      }
    });
    observer.observe(contentEl);
    return () => observer.disconnect();
  }, [transcriptOpen, scrollTranscriptToBottom]);

  const handleTranscriptScroll = () => {
    const el = transcriptScrollRef.current;
    if (!el) return;
    const shouldStick = shouldAutoScrollTranscript({
      scrollHeight: el.scrollHeight,
      scrollTop: el.scrollTop,
      clientHeight: el.clientHeight,
    });
    autoScrollEnabledRef.current = shouldStick;
    setAutoScrollPinned(shouldStick);
  };

  const stateTitle =
    assistantState === 'ready'
      ? 'Holographic Core Ready'
      : assistantState === 'listening'
      ? 'Listening for Voice Command'
      : assistantState === 'thinking'
      ? 'Synthesizing Response'
      : assistantState === 'speaking'
      ? 'Speaking Response'
      : 'Emergency Stop Active';

  const dataGridProfile = getDataGridProfile(assistantState);
  const isRippling = activeRippleSeq > 0;

  const measureOuterConnections = useCallback(() => {
    const viewEl = viewRef.current;
    if (!viewEl) return;
    const viewRect = viewEl.getBoundingClientRect();
    if (viewRect.width < 1024 || viewRect.height < 240) {
      setOuterConnectors(null);
      return;
    }

    const stageEl = viewEl.querySelector<HTMLElement>('[data-testid="radial-orbit-nav"]');
    if (!stageEl) return;
    const stageRect = stageEl.getBoundingClientRect();
    if (stageRect.width < 100 || stageRect.height < 100) return;

    const safeStageW = Math.max(320, Math.round(stageRect.width));
    const safeStageH = Math.max(240, Math.round(stageRect.height));
    const coreCx = stageRect.left - viewRect.left + Math.round(safeStageW / 2);
    const coreCy = stageRect.top - viewRect.top + Math.round(safeStageH * 0.47);
    const coreRadius = Math.round(
      Math.max(108, Math.min(safeStageW * 0.13, safeStageH * 0.255))
    );

    const innerObstacles: InnerCardObstacle[] = [];
    const innerEls = stageEl.querySelectorAll<HTMLElement>('[data-radial-node]');
    innerEls.forEach((el) => {
      const nodeId = el.getAttribute('data-radial-node');
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      const side: 'left' | 'right' =
        nodeId === 'assistant' || nodeId === 'memory' || nodeId === 'reminders'
          ? 'left'
          : 'right';
      innerObstacles.push({
        side,
        left: r.left - viewRect.left,
        right: r.right - viewRect.left,
        top: r.top - viewRect.top,
        bottom: r.bottom - viewRect.top,
      });
    });

    const outerSpecs: Array<{ id: OuterCardId; side: 'left' | 'right' }> = [
      { id: 'telemetry', side: 'left' },
      { id: 'neural-dsp', side: 'left' },
      { id: 'neural-data-stream', side: 'left' },
      { id: 'logs', side: 'left' },
      { id: 'transcript', side: 'right' },
      { id: 'weather', side: 'right' },
      { id: 'command-control', side: 'right' },
    ];

    const outerCards: OuterCardSocketInput[] = [];
    for (const spec of outerSpecs) {
      const el = outerCardRefs.current[spec.id];
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const visibleTop = Math.max(0, r.top - viewRect.top);
      const visibleBottom = Math.min(viewRect.height, r.bottom - viewRect.top);
      if (visibleBottom - visibleTop < 24) continue;
      outerCards.push({
        id: spec.id,
        side: spec.side,
        left: r.left - viewRect.left,
        right: r.right - viewRect.left,
        top: visibleTop,
        bottom: visibleBottom,
      });
    }

    const items = computeOuterCardConnectors(
      viewRect.width,
      viewRect.height,
      coreCx,
      coreCy,
      coreRadius,
      outerCards,
      innerObstacles
    );

    setOuterConnectors({
      width: Math.round(viewRect.width),
      height: Math.round(viewRect.height),
      items,
    });
  }, []);

  useLayoutEffect(() => {
    measureOuterConnections();
    const raf = window.requestAnimationFrame(measureOuterConnections);
    const viewEl = viewRef.current;
    let observer: ResizeObserver | null = null;
    if (viewEl && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        measureOuterConnections();
      });
      observer.observe(viewEl);
      for (const el of Object.values(outerCardRefs.current)) {
        if (el) observer.observe(el);
      }
      const stageEl = viewEl.querySelector<HTMLElement>('[data-testid="radial-orbit-nav"]');
      if (stageEl) observer.observe(stageEl);
    }
    window.addEventListener('resize', measureOuterConnections);
    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener('resize', measureOuterConnections);
      observer?.disconnect();
    };
  }, [
    measureOuterConnections,
    statusOpen,
    transcriptOpen,
    logsOpen,
    transcript.length,
    settings.colorTheme,
  ]);

  const handleContextMenu = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    setContextMenu({ open: true, x: e.clientX, y: e.clientY });
  };

  return (
    <div
      ref={viewRef}
      data-testid="assistant-view"
      onContextMenu={handleContextMenu}
      className="relative z-10 flex h-full w-full flex-col gap-3 p-3 pb-24 overflow-y-auto lg:grid lg:overflow-hidden lg:p-3 lg:pb-3 lg:grid-cols-[minmax(256px,328px)_minmax(0,1fr)_minmax(256px,328px)] lg:grid-rows-[auto_minmax(0,1fr)_auto] pointer-events-auto"
    >
      {/* Background CSS Grid Holographic Data-Stream Layer */}
      <div
        aria-hidden="true"
        data-testid="assistant-data-grid"
        data-state={assistantState}
        data-rippling={isRippling ? 'true' : 'false'}
        data-ripple-seq={dataGridRippleSeq}
        className={`data-grid ${dataGridProfile.toneClass} ${isRippling ? 'is-rippling' : ''}`}
        style={{ opacity: isRippling ? 1 : dataGridProfile.opacityLevel }}
      >
        {Array.from({ length: DATA_GRID_ROWS }, (_, rowIdx) =>
          Array.from({ length: DATA_GRID_COLUMNS }, (__, colIdx) => (
            <div
              key={`cell-${rowIdx}-${colIdx}`}
              className="data-grid-cell"
              style={{
                gridColumn: colIdx + 1,
                gridRow: rowIdx + 1,
              }}
            />
          ))
        )}

        {DATA_GRID_STREAMS.map((stream) => (
          <div
            key={stream.id}
            className={`data-grid-stream ${
              stream.axis === 'vertical'
                ? 'data-grid-stream--vertical'
                : 'data-grid-stream--horizontal'
            }`}
            style={
              stream.axis === 'vertical'
                ? { gridColumn: stream.trackIndex, gridRow: '1 / -1' }
                : { gridColumn: '1 / -1', gridRow: stream.trackIndex }
            }
          >
            <span
              className={`data-grid-pulse ${
                stream.axis === 'vertical'
                  ? 'data-grid-pulse--vertical'
                  : 'data-grid-pulse--horizontal'
              } data-grid-pulse--${stream.tone}`}
              style={{
                animationDuration: `${(
                  stream.durationSec * dataGridProfile.speedMultiplier
                ).toFixed(2)}s`,
                animationDelay: `${stream.delaySec}s`,
              }}
            />
          </div>
        ))}

        {DATA_GRID_NODES.map((node) => (
          <div
            key={node.id}
            className="data-grid-node"
            style={
              {
                gridColumn: node.col,
                gridRow: node.row,
                '--node-duration': `${(
                  node.durationSec * dataGridProfile.speedMultiplier
                ).toFixed(2)}s`,
                '--node-delay': `${node.delaySec}s`,
              } as React.CSSProperties
            }
          />
        ))}

        {isRippling && (
          <div
            key={`ripple-${activeRippleSeq}`}
            data-testid="data-grid-ripple-layer"
            className="data-grid-ripple-layer"
          >
            <div className="data-grid-ripple-wave data-grid-ripple-wave--primary" />
            <div className="data-grid-ripple-wave data-grid-ripple-wave--secondary" />
            <div className="data-grid-ripple-cells">
              {Array.from({ length: DATA_GRID_ROWS }, (_, rowIdx) =>
                Array.from({ length: DATA_GRID_COLUMNS }, (__, colIdx) => {
                  const col = colIdx + 1;
                  const row = rowIdx + 1;
                  return (
                    <div
                      key={`ripple-cell-${row}-${col}`}
                      className="data-grid-ripple-cell"
                      style={{
                        gridColumn: col,
                        gridRow: row,
                        animationDelay: `${computeGridCellRippleDelayMs(col, row)}ms`,
                      }}
                    />
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>

      {/* Perimeter Card-to-Core Holographic Conduit Overlay (Desktop) */}
      {outerConnectors && outerConnectors.items.length > 0 && (
        <svg
          aria-hidden="true"
          data-testid="outer-core-connectors"
          viewBox={`0 0 ${outerConnectors.width} ${outerConnectors.height}`}
          preserveAspectRatio="none"
          className="hidden lg:block pointer-events-none absolute inset-0 z-10 h-full w-full"
        >
          {outerConnectors.items.map((conn) => {
            const isHighlighted = hoveredOuterCard === conn.id;
            const strokeColor =
              assistantState === 'stopped'
                ? 'rgba(244, 63, 94, 0.34)'
                : isHighlighted
                ? `rgba(${activeTheme.accentRgb}, 0.88)`
                : `rgba(${activeTheme.primaryRgb}, 0.34)`;

            return (
              <g key={`outer-link-${conn.id}`} data-outer-connector={conn.id}>
                <path
                  data-connector-path="true"
                  d={conn.pathD}
                  fill="none"
                  stroke={strokeColor}
                  strokeWidth={isHighlighted ? 1.8 : 1.25}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                />
                <path
                  data-connector-path="true"
                  d={conn.pathD}
                  fill="none"
                  stroke={
                    isHighlighted
                      ? `rgba(${activeTheme.softRgb}, 0.92)`
                      : `rgba(${activeTheme.primaryRgb}, 0.5)`
                  }
                  strokeWidth={isHighlighted ? 2 : 1.2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                  className="holo-link-flow"
                />
                <circle
                  cx={conn.coreAnchorX}
                  cy={conn.coreAnchorY}
                  r={isHighlighted ? 4.2 : 2.8}
                  fill={isHighlighted ? activeTheme.accentCss : activeTheme.primaryCss}
                  fillOpacity={isHighlighted ? 0.95 : 0.72}
                />
                <circle
                  cx={conn.nodeAnchorX}
                  cy={conn.nodeAnchorY}
                  r={isHighlighted ? 6.2 : 5}
                  fill="none"
                  stroke={isHighlighted ? activeTheme.accentCss : activeTheme.primaryCss}
                  strokeOpacity={isHighlighted ? 0.75 : 0.42}
                  strokeWidth="1"
                />
                <circle
                  cx={conn.nodeAnchorX}
                  cy={conn.nodeAnchorY}
                  r={isHighlighted ? 3.6 : 2.6}
                  fill={isHighlighted ? activeTheme.accentCss : activeTheme.primaryCss}
                  fillOpacity={isHighlighted ? 1 : 0.85}
                />
              </g>
            );
          })}
        </svg>
      )}

      {/* Top-Center Core Status Header + Panel Visibility Controls */}
      <div className="relative z-20 flex shrink-0 flex-col items-center gap-1.5 text-center lg:col-start-2 lg:row-start-1 lg:justify-self-center lg:self-start lg:max-w-[560px] pointer-events-auto">
        <div className="flex flex-col items-center gap-0.5 max-w-full">
          <p className="font-display text-sm font-medium tracking-wide text-sky-200/90">
            {stateTitle}
          </p>
          <p
            title={statusBanner}
            className="max-w-full truncate font-mono text-[11px] text-slate-400"
          >
            {statusBanner}
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-x-2.5 gap-y-0.5 rounded-2xl sm:rounded-full border border-white/15 bg-[#060911]/80 px-3.5 py-1 text-[11px] text-slate-400 backdrop-blur-md">
          <button
            type="button"
            onClick={() => setStatusOpen((v) => !v)}
            className="py-1 text-slate-300 hover:text-sky-300 transition-colors whitespace-nowrap shrink-0"
          >
            {statusOpen ? 'Hide telemetry' : 'Show telemetry'}
          </button>
          <span aria-hidden="true" className="text-slate-600">·</span>
          <button
            type="button"
            onClick={() => setTranscriptOpen((v) => !v)}
            className="py-1 text-slate-300 hover:text-sky-300 transition-colors whitespace-nowrap shrink-0"
          >
            {transcriptOpen ? 'Hide transcript' : 'Show transcript'}
          </button>
          <span aria-hidden="true" className="text-slate-600">·</span>
          <button
            type="button"
            onClick={() => setLogsOpen((v) => !v)}
            className="py-1 text-slate-300 hover:text-sky-300 transition-colors whitespace-nowrap shrink-0"
          >
            {logsOpen ? 'Hide logs' : 'Show logs'}
          </button>
          <span aria-hidden="true" className="text-slate-600">·</span>
          <button
            type="button"
            data-testid="command-history-drawer-toggle"
            aria-expanded={historyDrawerOpen}
            onClick={() => setHistoryDrawerOpen((v) => !v)}
            className={`inline-flex items-center gap-1 py-1 transition-colors whitespace-nowrap shrink-0 ${
              historyDrawerOpen ? 'text-cyan-200' : 'text-slate-300 hover:text-sky-300'
            }`}
          >
            <History className="h-3 w-3" aria-hidden="true" />
            <span>History</span>
          </button>
          <span aria-hidden="true" className="text-slate-600">·</span>
          <button
            type="button"
            data-testid="open-privacy-dashboard"
            onClick={() => setActiveTab('privacy')}
            className="inline-flex items-center gap-1 py-1 text-slate-300 hover:text-sky-300 transition-colors whitespace-nowrap shrink-0"
          >
            <ShieldCheck className="h-3 w-3 text-teal-300" aria-hidden="true" />
            <span>Privacy</span>
          </button>
          <span aria-hidden="true" className="text-slate-600">·</span>
          <button
            type="button"
            onClick={() => setQuietMode(!quietMode)}
            className="inline-flex items-center gap-1 py-1 text-slate-300 hover:text-sky-300 transition-colors whitespace-nowrap shrink-0"
            aria-pressed={quietMode}
          >
            {quietMode ? (
              <VolumeX className="h-3 w-3 text-amber-300" aria-hidden="true" />
            ) : (
              <Volume2 className="h-3 w-3 text-sky-300" aria-hidden="true" />
            )}
            <span>{quietMode ? 'Voice off' : 'Voice on'}</span>
          </button>
        </div>
      </div>

      {/* Unified Left Perimeter Rail: Telemetry, Neural DSP Matrix, Neural Data Stream, Logs */}
      <div
        data-testid="left-hud-rail"
        onScroll={measureOuterConnections}
        className="hud-side-rail relative z-20 flex shrink-0 flex-col gap-2.5 lg:col-start-1 lg:row-start-1 lg:row-end-4 lg:h-full lg:min-h-0 lg:justify-between lg:gap-2 lg:overflow-y-auto lg:overflow-x-hidden lg:pr-0.5 shu-scroll pointer-events-auto"
      >
        {statusOpen && (
          <div
            ref={(el) => {
              outerCardRefs.current.telemetry = el;
            }}
            data-outer-card="telemetry"
            onMouseEnter={() => setHoveredOuterCard('telemetry')}
            onMouseLeave={() => setHoveredOuterCard((c) => (c === 'telemetry' ? null : c))}
            className="shrink-0"
          >
            <SystemStatusView />
          </div>
        )}

        <div
          ref={(el) => {
            outerCardRefs.current['neural-dsp'] = el;
          }}
          data-outer-card="neural-dsp"
          onMouseEnter={() => setHoveredOuterCard('neural-dsp')}
          onMouseLeave={() => setHoveredOuterCard((c) => (c === 'neural-dsp' ? null : c))}
          className="shrink-0"
        >
          <NeuralSignalCard />
        </div>

        <div
          ref={(el) => {
            outerCardRefs.current['neural-data-stream'] = el;
          }}
          data-outer-card="neural-data-stream"
          onMouseEnter={() => setHoveredOuterCard('neural-data-stream')}
          onMouseLeave={() =>
            setHoveredOuterCard((c) => (c === 'neural-data-stream' ? null : c))
          }
          className="shrink-0"
        >
          <NeuralDataStreamPanel />
        </div>

        {logsOpen && (
          <div
            ref={(el) => {
              outerCardRefs.current.logs = el;
            }}
            data-outer-card="logs"
            onMouseEnter={() => setHoveredOuterCard('logs')}
            onMouseLeave={() => setHoveredOuterCard((c) => (c === 'logs' ? null : c))}
            className="shrink-0"
          >
            <CommandHistoryView onSelectCommand={(cmd) => setInputText(cmd)} />
          </div>
        )}
      </div>

      {/* Unified Right Perimeter Rail: Transcript, Live Weather, Command Control */}
      <div
        data-testid="right-hud-rail"
        onScroll={measureOuterConnections}
        className="hud-side-rail relative z-20 flex shrink-0 flex-col gap-2.5 lg:col-start-3 lg:row-start-1 lg:row-end-4 lg:h-full lg:min-h-0 lg:justify-between lg:gap-2 lg:overflow-y-auto lg:overflow-x-hidden lg:pl-0.5 shu-scroll pointer-events-auto"
      >
        {transcriptOpen && (
          <section
            ref={(el) => {
              outerCardRefs.current.transcript = el;
            }}
            data-outer-card="transcript"
            onMouseEnter={() => setHoveredOuterCard('transcript')}
            onMouseLeave={() => setHoveredOuterCard((c) => (c === 'transcript' ? null : c))}
            aria-label="Conversation transcript"
            data-testid="transcript-panel"
            className="holo-surface flex shrink-0 flex-col rounded-2xl px-3.5 py-2.5"
          >
            <div className="mb-1.5 flex items-center justify-between gap-2 border-b border-white/12 pb-1">
              <div className="flex items-center gap-1.5">
                <MessageSquareText className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
                <h2 className="font-mono text-[11px] font-medium tracking-wider text-sky-200/95">
                  Transcript
                </h2>
              </div>

              <div className="flex items-center gap-2 font-mono text-[10px]">
                {isStreaming && (
                  <span className="inline-flex items-center gap-1 text-teal-300">
                    <span className="h-1.5 w-1.5 rounded-full bg-teal-300 animate-pulse" />
                    Streaming
                  </span>
                )}
                {!autoScrollPinned && (
                  <button
                    type="button"
                    onClick={() => {
                      autoScrollEnabledRef.current = true;
                      setAutoScrollPinned(true);
                      scrollTranscriptToBottom();
                    }}
                    className="inline-flex items-center gap-1 rounded border border-sky-400/40 bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-200 hover:bg-sky-500/25"
                  >
                    <ArrowDown className="h-2.5 w-2.5" aria-hidden="true" />
                    Latest
                  </button>
                )}
                <span className="text-slate-400 tabular-nums">
                  {transcript.length} {transcript.length === 1 ? 'msg' : 'msgs'}
                </span>
              </div>
            </div>

            <div
              ref={transcriptScrollRef}
              data-testid="transcript-scroll-container"
              onScroll={handleTranscriptScroll}
              className="h-32 max-h-36 overflow-y-auto pr-1 shu-scroll"
            >
              <div ref={transcriptContentRef} className="space-y-2">
                {transcript.length === 0 ? (
                  <p className="font-mono text-xs text-slate-500">
                    Transcript cleared · Ready for commands or diagnostics.
                  </p>
                ) : (
                  transcript.map((entry) => (
                    <div
                      key={entry.id}
                      className="flex items-baseline justify-between gap-3 border-b border-slate-800/70 pb-1.5 last:border-b-0 last:pb-0 text-xs"
                    >
                      <div className="min-w-0 flex-1">
                        <span
                          className={`mr-1.5 font-mono text-[11px] ${
                            entry.role === 'user'
                              ? 'text-teal-300'
                              : entry.role === 'system'
                              ? 'text-rose-300'
                              : 'text-sky-300'
                          }`}
                        >
                          {entry.role === 'user'
                            ? 'YOU'
                            : entry.role === 'system'
                            ? 'SYS'
                            : 'SHU'}
                        </span>
                        <span className="text-slate-200 whitespace-pre-wrap break-words leading-relaxed">
                          {entry.text}
                        </span>
                        {entry.rating !== undefined && (
                          <span className="ml-2 font-mono text-[11px] text-amber-300">
                            · Rated {entry.rating}/5
                          </span>
                        )}
                      </div>
                      <span className="font-mono text-[10px] text-slate-500 shrink-0 tabular-nums">
                        {entry.timestamp}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>
        )}

        <div
          ref={(el) => {
            outerCardRefs.current.weather = el;
          }}
          data-outer-card="weather"
          onMouseEnter={() => setHoveredOuterCard('weather')}
          onMouseLeave={() => setHoveredOuterCard((c) => (c === 'weather' ? null : c))}
          className="shrink-0"
        >
          <WeatherForecastCard />
        </div>

        <div
          ref={(el) => {
            outerCardRefs.current['command-control'] = el;
          }}
          data-outer-card="command-control"
          onMouseEnter={() => setHoveredOuterCard('command-control')}
          onMouseLeave={() =>
            setHoveredOuterCard((c) => (c === 'command-control' ? null : c))
          }
          className="relative z-30 shrink-0"
        >
          <CommandControl inputText={inputText} onInputChange={setInputText} />
        </div>
      </div>

      {/* Center 3D Radial Stage: 6 Live Connected HUD Panels Around Center 3D Model + Voice Waveform */}
      <div className="relative z-10 flex shrink-0 flex-col items-center justify-center lg:col-start-2 lg:row-start-1 lg:row-end-4 lg:min-h-0 lg:pt-20 lg:pb-18 pointer-events-none">
        <WakeWordOverlay />
        <RadialOrbitNav />
        <VoiceVisualizer />
      </div>

      {/* Bottom-Center Microphone Cluster: [Mute microphone] — [Microphone] — [Start listening] */}
      <div
        data-testid="bottom-mic-cluster"
        className="fixed bottom-3 left-1/2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-full border border-sky-400/20 bg-[#060911]/88 px-2.5 py-1.5 backdrop-blur-md shadow-[0_12px_34px_rgba(2,6,18,0.75)] lg:static lg:translate-x-0 lg:col-start-2 lg:row-start-3 lg:justify-self-center lg:self-end lg:mb-0.5 pointer-events-auto"
      >
        {/* Left of Microphone: Mute microphone */}
        <button
          type="button"
          data-testid="mute-mic-button"
          onClick={toggleMute}
          aria-pressed={isMuted}
          aria-label={isMuted ? 'Unmute microphone' : 'Mute microphone'}
          className={`inline-flex min-h-[38px] items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-amber-300 ${
            isMuted
              ? 'border-amber-400/60 bg-amber-500/20 text-amber-200'
              : 'border-slate-700/80 bg-slate-900/80 text-slate-200 hover:border-sky-400/45 hover:text-sky-100'
          }`}
        >
          <MicOff className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="sm:hidden">{isMuted ? 'Unmute' : 'Mute'}</span>
          <span className="hidden sm:inline">
            {isMuted ? 'Unmute microphone' : 'Mute microphone'}
          </span>
        </button>

        {/* Center Persistent Glass-Morphism Microphone Toggle */}
        <button
          type="button"
          data-testid="floating-mic-toggle"
          data-listening={isListening ? 'true' : 'false'}
          aria-pressed={isListening}
          aria-label={isListening ? 'Microphone listening, click to stop' : 'Microphone, click to start listening'}
          onClick={toggleListening}
          className={`holo-mic-glass relative inline-flex min-h-[42px] items-center gap-2 rounded-full px-4 py-2 text-xs font-medium tracking-wide whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-cyan-300 ${
            isListening
              ? 'holo-mic-glass--listening text-teal-100'
              : 'text-sky-100 hover:text-cyan-100'
          }`}
        >
          {isListening && (
            <>
              <span aria-hidden="true" className="holo-mic-pulse-ring" />
              <span
                aria-hidden="true"
                className="holo-mic-pulse-ring holo-mic-pulse-ring--delayed"
              />
            </>
          )}
          <Mic
            className={`h-4 w-4 ${isListening ? 'text-teal-300' : 'text-sky-300'}`}
            aria-hidden="true"
          />
          <span>{isListening ? 'Listening' : 'Microphone'}</span>
        </button>

        {/* Right of Microphone: Start listening */}
        <button
          type="button"
          data-testid="start-listening-button"
          onClick={toggleListening}
          aria-pressed={isListening}
          aria-label={isListening ? 'Stop listening' : 'Start listening'}
          className={`inline-flex min-h-[38px] items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-teal-300 ${
            isListening
              ? 'border-teal-400/60 bg-teal-500/20 text-teal-100 hover:bg-teal-500/30'
              : 'border-slate-700/80 bg-slate-900/80 text-slate-200 hover:border-teal-400/45 hover:text-teal-200'
          }`}
        >
          <Radio className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="sm:hidden">{isListening ? 'Stop' : 'Listen'}</span>
          <span className="hidden sm:inline">
            {isListening ? 'Stop listening' : 'Start listening'}
          </span>
        </button>
      </div>

      {/* Bottom Sliding Voice Command History Drawer (Last 5 Commands + Clear History) */}
      <CommandHistoryDrawer
        open={historyDrawerOpen}
        onClose={() => setHistoryDrawerOpen(false)}
        onSelectCommand={(cmd) => setInputText(cmd)}
      />

      {/* Holographic Right-Click Quick-Action Context Menu */}
      <HoloContextMenu
        open={contextMenu.open}
        x={contextMenu.x}
        y={contextMenu.y}
        onClose={() => setContextMenu((prev) => ({ ...prev, open: false }))}
      />
    </div>
  );
};
