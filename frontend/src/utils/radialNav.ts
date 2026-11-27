import type { ShuTab } from '../types/shu';

export interface RadialNavNode {
  id: ShuTab;
  label: string;
  side: 'left' | 'right';
  /** Percentage position inside radial stage (0..100). Anchor is inner edge facing core. */
  xPct: number;
  yPct: number;
  /** SVG connector geometry */
  pathD: string;
  coreAnchorX: number;
  coreAnchorY: number;
  nodeAnchorX: number;
  nodeAnchorY: number;
}

export interface RadialSocketInput {
  id: ShuTab;
  label: string;
  side: 'left' | 'right';
  anchorX: number;
  anchorY: number;
}

export interface MeasuredRadialStageGeometry {
  width: number;
  height: number;
  coreCx: number;
  coreCy: number;
  coreRadius: number;
  nodes: RadialNavNode[];
}

export type OuterCardId =
  | 'telemetry'
  | 'neural-dsp'
  | 'neural-data-stream'
  | 'logs'
  | 'transcript'
  | 'weather'
  | 'command-control';

export interface OuterCardSocketInput {
  id: OuterCardId;
  side: 'left' | 'right';
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface InnerCardObstacle {
  side: 'left' | 'right';
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface OuterCardConnector {
  id: OuterCardId;
  side: 'left' | 'right';
  pathD: string;
  coreAnchorX: number;
  coreAnchorY: number;
  nodeAnchorX: number;
  nodeAnchorY: number;
  corridorY: number;
}

export const RADIAL_VIEWBOX_WIDTH = 1200;
export const RADIAL_VIEWBOX_HEIGHT = 520;
export const RADIAL_CORE_CX = 600;
export const RADIAL_CORE_CY = 250;
export const RADIAL_CORE_RING_RADIUS = 132;

export interface RadialNodeSpec {
  id: ShuTab;
  label: string;
  side: 'left' | 'right';
  xPct: number;
  yPct: number;
}

export const RADIAL_NODE_SPECS: readonly RadialNodeSpec[] = [
  { id: 'assistant', label: 'Assistant', side: 'left', xPct: 26, yPct: 16 },
  { id: 'memory', label: 'Memory', side: 'left', xPct: 26, yPct: 50 },
  { id: 'reminders', label: 'Reminders', side: 'left', xPct: 26, yPct: 84 },
  { id: 'communications', label: 'Communications', side: 'right', xPct: 74, yPct: 16 },
  { id: 'workflows', label: 'Workflows', side: 'right', xPct: 74, yPct: 50 },
  { id: 'settings', label: 'Settings', side: 'right', xPct: 74, yPct: 84 },
];

/**
 * Generates a smooth, C1-continuous SVG cubic Bézier wave path between two points
 * with a gentle sinusoidal undulation (never straight angular polylines).
 */
export function buildCurvyWavePath(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  waveAmplitude = 12,
  waveSign = 1
): string {
  const sx = Math.round(startX);
  const sy = Math.round(startY);
  const ex = Math.round(endX);
  const ey = Math.round(endY);
  const dx = ex - sx;
  const dy = ey - sy;

  const midX = Math.round(sx + dx * 0.5);
  const midY = Math.round(sy + dy * 0.5);
  const amp = Math.round(waveAmplitude) * (waveSign >= 0 ? 1 : -1);

  // First cubic Bézier crest from start -> midpoint
  const c1x = Math.round(sx + dx * 0.22);
  const c1y = Math.round(sy + dy * 0.14 - amp);
  const c2x = Math.round(midX - dx * 0.16);
  const c2y = Math.round(midY - dy * 0.12 + amp * 0.85);

  // Reflect control point across midpoint for seamless C1 continuity into second wave crest
  const c3x = 2 * midX - c2x;
  const c3y = 2 * midY - c2y;
  const c4x = Math.round(ex - dx * 0.2);
  const c4y = Math.round(ey - dy * 0.08 + amp * 0.45);

  return `M ${sx} ${sy} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${midX} ${midY} C ${c3x} ${c3y}, ${c4x} ${c4y}, ${ex} ${ey}`;
}

function resolveWaveSign(id: string): number {
  if (
    id === 'memory' ||
    id === 'communications' ||
    id === 'neural-dsp' ||
    id === 'logs' ||
    id === 'transcript'
  ) {
    return -1;
  }
  return 1;
}

function buildCircuitConnector(
  id: ShuTab,
  label: string,
  side: 'left' | 'right',
  xPct: number,
  yPct: number,
  coreCx: number,
  coreCy: number,
  coreRadius: number,
  nodeAnchorX: number,
  nodeAnchorY: number
): RadialNavNode {
  const dx = nodeAnchorX - coreCx;
  const dy = nodeAnchorY - coreCy;
  const angle = Math.atan2(dy, dx);

  const coreAnchorX = Math.round(coreCx + Math.cos(angle) * coreRadius);
  const coreAnchorY = Math.round(coreCy + Math.sin(angle) * coreRadius);

  const roundedAnchorX = Math.round(nodeAnchorX);
  const roundedAnchorY = Math.round(nodeAnchorY);
  const span = Math.abs(roundedAnchorX - coreAnchorX);
  const waveAmp = Math.max(13, Math.min(22, Math.round(span * 0.14)));
  const pathD = buildCurvyWavePath(
    coreAnchorX,
    coreAnchorY,
    roundedAnchorX,
    roundedAnchorY,
    waveAmp,
    resolveWaveSign(id)
  );

  return {
    id,
    label,
    side,
    xPct,
    yPct,
    pathD,
    coreAnchorX,
    coreAnchorY,
    nodeAnchorX: roundedAnchorX,
    nodeAnchorY: roundedAnchorY,
  };
}

export function computeRadialNavNodes(): RadialNavNode[] {
  return RADIAL_NODE_SPECS.map((spec) => {
    const nodeAnchorX = Math.round((spec.xPct / 100) * RADIAL_VIEWBOX_WIDTH);
    const nodeAnchorY = Math.round((spec.yPct / 100) * RADIAL_VIEWBOX_HEIGHT);
    return buildCircuitConnector(
      spec.id,
      spec.label,
      spec.side,
      spec.xPct,
      spec.yPct,
      RADIAL_CORE_CX,
      RADIAL_CORE_CY,
      RADIAL_CORE_RING_RADIUS,
      nodeAnchorX,
      nodeAnchorY
    );
  });
}

export function computeMeasuredRadialGeometry(
  stageWidth: number,
  stageHeight: number,
  sockets: readonly RadialSocketInput[]
): MeasuredRadialStageGeometry {
  const safeW = Math.max(320, Math.round(stageWidth));
  const safeH = Math.max(240, Math.round(stageHeight));
  const coreCx = Math.round(safeW / 2);
  const coreCy = Math.round(safeH * 0.47);
  const coreRadius = Math.round(Math.max(108, Math.min(safeW * 0.13, safeH * 0.255)));

  const nodes = sockets.map((sock) => {
    const spec = RADIAL_NODE_SPECS.find((s) => s.id === sock.id);
    return buildCircuitConnector(
      sock.id,
      sock.label,
      sock.side,
      spec?.xPct ?? (sock.side === 'left' ? 26 : 74),
      spec?.yPct ?? Math.round((sock.anchorY / safeH) * 100),
      coreCx,
      coreCy,
      coreRadius,
      sock.anchorX,
      sock.anchorY
    );
  });

  return {
    width: safeW,
    height: safeH,
    coreCx,
    coreCy,
    coreRadius,
    nodes,
  };
}

function findOpenYCorridors(
  obstacles: readonly InnerCardObstacle[],
  viewHeight: number
): Array<{ start: number; end: number }> {
  const minBound = 16;
  const maxBound = Math.max(minBound + 20, viewHeight - 16);
  const sorted = [...obstacles].sort((a, b) => a.top - b.top);
  const intervals: Array<{ start: number; end: number }> = [];
  let cursor = minBound;
  const pad = 8;

  for (const obs of sorted) {
    const blockedStart = Math.max(minBound, obs.top - pad);
    const blockedEnd = Math.min(maxBound, obs.bottom + pad);
    if (blockedStart - cursor >= 14) {
      intervals.push({ start: cursor, end: blockedStart });
    }
    cursor = Math.max(cursor, blockedEnd);
  }

  if (maxBound - cursor >= 14) {
    intervals.push({ start: cursor, end: maxBound });
  }

  return intervals;
}

export function computeOuterCardConnectors(
  viewWidth: number,
  viewHeight: number,
  coreCx: number,
  coreCy: number,
  coreRadius: number,
  outerCards: readonly OuterCardSocketInput[],
  innerObstacles: readonly InnerCardObstacle[]
): OuterCardConnector[] {
  const safeW = Math.max(320, Math.round(viewWidth));
  const safeH = Math.max(240, Math.round(viewHeight));

  return outerCards.map((card) => {
    const sideObstacles = innerObstacles.filter((obs) => obs.side === card.side);
    const corridors = findOpenYCorridors(sideObstacles, safeH);

    const cardMidY = Math.round((card.top + card.bottom) / 2);
    const cardAnchorMinY = Math.min(cardMidY, card.top + 16);
    const cardAnchorMaxY = Math.max(cardAnchorMinY, card.bottom - 16);

    const nodeAnchorX = Math.round(card.side === 'left' ? card.right : card.left);

    let directCorridorY: number | null = null;
    let bestOverlapScore = Infinity;

    for (const corr of corridors) {
      const overlapStart = Math.max(cardAnchorMinY, corr.start);
      const overlapEnd = Math.min(cardAnchorMaxY, corr.end);
      if (overlapEnd - overlapStart >= 10) {
        const candidateY = Math.round((overlapStart + overlapEnd) / 2);
        const distFromMid = Math.abs(candidateY - cardMidY);
        if (distFromMid < bestOverlapScore) {
          bestOverlapScore = distFromMid;
          directCorridorY = candidateY;
        }
      }
    }

    const innerOuterEdge =
      sideObstacles.length > 0
        ? card.side === 'left'
          ? Math.min(...sideObstacles.map((o) => o.left))
          : Math.max(...sideObstacles.map((o) => o.right))
        : card.side === 'left'
        ? nodeAnchorX + 16
        : nodeAnchorX - 16;

    const innerInnerEdge =
      sideObstacles.length > 0
        ? card.side === 'left'
          ? Math.max(...sideObstacles.map((o) => o.right))
          : Math.min(...sideObstacles.map((o) => o.left))
        : card.side === 'left'
        ? Math.min(coreCx - coreRadius - 18, nodeAnchorX + 140)
        : Math.max(coreCx + coreRadius + 18, nodeAnchorX - 140);

    let nodeAnchorY: number;
    let corridorY: number;

    if (directCorridorY !== null) {
      nodeAnchorY = directCorridorY;
      corridorY = directCorridorY;
    } else {
      nodeAnchorY = Math.max(cardAnchorMinY, Math.min(cardAnchorMaxY, cardMidY));
      if (corridors.length > 0) {
        let closestY = Math.round((corridors[0].start + corridors[0].end) / 2);
        let closestDist = Math.abs(closestY - nodeAnchorY);
        for (const corr of corridors) {
          const mid = Math.round((corr.start + corr.end) / 2);
          const dist = Math.abs(mid - nodeAnchorY);
          if (dist < closestDist) {
            closestDist = dist;
            closestY = mid;
          }
        }
        corridorY = closestY;
      } else {
        corridorY = nodeAnchorY;
      }
    }

    const gutterX = Math.round(
      card.side === 'left'
        ? Math.max(nodeAnchorX + 6, (nodeAnchorX + innerOuterEdge) / 2)
        : Math.min(nodeAnchorX - 6, (nodeAnchorX + innerOuterEdge) / 2)
    );

    const clearMargin = 18;
    const elbowX = Math.round(
      card.side === 'left'
        ? Math.min(coreCx - coreRadius - 16, innerInnerEdge + clearMargin)
        : Math.max(coreCx + coreRadius + 16, innerInnerEdge - clearMargin)
    );

    const dx = elbowX - coreCx;
    const dy = corridorY - coreCy;
    const angle = Math.atan2(dy, dx);
    const coreAnchorX = Math.round(coreCx + Math.cos(angle) * coreRadius);
    const coreAnchorY = Math.round(coreCy + Math.sin(angle) * coreRadius);

    const sign = resolveWaveSign(card.id);
    let pathD: string;

    if (Math.abs(corridorY - nodeAnchorY) <= 2) {
      pathD = buildCurvyWavePath(
        coreAnchorX,
        coreAnchorY,
        nodeAnchorX,
        nodeAnchorY,
        13,
        sign
      );
    } else {
      // Smooth curvy path through the open corridor around inner cards, ending at the outer card socket
      const waveOffset = 9 * sign;
      const c1x = Math.round(coreAnchorX + (elbowX - coreAnchorX) * 0.45);
      const c1y = Math.round(coreAnchorY + (corridorY - coreAnchorY) * 0.65 - waveOffset);
      const c2x = Math.round(elbowX - (elbowX - gutterX) * 0.25);
      const c2y = Math.round(corridorY + waveOffset);

      const passX = gutterX;
      const passY = corridorY;

      const c3x = Math.round(passX + (nodeAnchorX - passX) * 0.15);
      const c3y = Math.round(corridorY + (nodeAnchorY - corridorY) * 0.52);
      const c4x = Math.round(nodeAnchorX - (nodeAnchorX - passX) * 0.42);
      const c4y = Math.round(nodeAnchorY - waveOffset * 0.5);

      pathD = `M ${coreAnchorX} ${coreAnchorY} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${passX} ${passY} C ${c3x} ${c3y}, ${c4x} ${c4y}, ${nodeAnchorX} ${nodeAnchorY}`;
    }

    return {
      id: card.id,
      side: card.side,
      pathD,
      coreAnchorX: Math.max(0, Math.min(safeW, coreAnchorX)),
      coreAnchorY: Math.max(0, Math.min(safeH, coreAnchorY)),
      nodeAnchorX,
      nodeAnchorY,
      corridorY,
    };
  });
}
