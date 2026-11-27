import test from 'node:test';
import assert from 'node:assert/strict';
import {
  RADIAL_CORE_CX,
  RADIAL_CORE_CY,
  RADIAL_CORE_RING_RADIUS,
  buildCurvyWavePath,
  computeMeasuredRadialGeometry,
  computeOuterCardConnectors,
  computeRadialNavNodes,
} from './radialNav';

test('buildCurvyWavePath produces smooth cubic Bézier SVG paths without linear L segments', () => {
  const path = buildCurvyWavePath(400, 200, 120, 80, 12, 1);
  assert.ok(path.startsWith('M 400 200 C '));
  assert.ok(path.includes(' C '));
  assert.ok(!path.includes(' L '));
  assert.ok(path.endsWith('120 80'));
});

test('computeRadialNavNodes places all 6 tabs symmetrically around center core with wavy paths', () => {
  const nodes = computeRadialNavNodes();
  assert.equal(nodes.length, 6);

  const leftNodes = nodes.filter((n) => n.side === 'left');
  const rightNodes = nodes.filter((n) => n.side === 'right');
  assert.equal(leftNodes.length, 3);
  assert.equal(rightNodes.length, 3);

  for (const node of nodes) {
    const distFromCenter = Math.hypot(
      node.coreAnchorX - RADIAL_CORE_CX,
      node.coreAnchorY - RADIAL_CORE_CY
    );
    assert.ok(Math.abs(distFromCenter - RADIAL_CORE_RING_RADIUS) <= 2);
    assert.ok(node.pathD.startsWith('M '));
    assert.ok(node.pathD.includes(' C '));
    assert.ok(!node.pathD.includes(' L '));
  }
});

test('computeMeasuredRadialGeometry docks every curvy wave path flush to measured card edge sockets', () => {
  const geo = computeMeasuredRadialGeometry(1380, 640, [
    { id: 'assistant', label: 'Assistant', side: 'left', anchorX: 356, anchorY: 56 },
    { id: 'memory', label: 'Memory', side: 'left', anchorX: 356, anchorY: 310 },
    { id: 'reminders', label: 'Reminders', side: 'left', anchorX: 356, anchorY: 572 },
    { id: 'communications', label: 'Communications', side: 'right', anchorX: 1024, anchorY: 54 },
    { id: 'workflows', label: 'Workflows', side: 'right', anchorX: 1024, anchorY: 312 },
    { id: 'settings', label: 'Settings', side: 'right', anchorX: 1024, anchorY: 584 },
  ]);

  assert.equal(geo.width, 1380);
  assert.equal(geo.height, 640);
  assert.equal(geo.nodes.length, 6);

  for (const node of geo.nodes) {
    const dist = Math.hypot(node.coreAnchorX - geo.coreCx, node.coreAnchorY - geo.coreCy);
    assert.ok(Math.abs(dist - geo.coreRadius) <= 2);
    assert.ok(node.pathD.includes(' C '));
    assert.ok(node.pathD.endsWith(`${node.nodeAnchorX} ${node.nodeAnchorY}`));
  }
});

test('computeOuterCardConnectors connects all 7 perimeter cards including Neural Data Stream with curvy wave paths clearing inner cards', () => {
  const innerObstacles = [
    { side: 'left' as const, left: 372, right: 548, top: 108, bottom: 204 },
    { side: 'left' as const, left: 372, right: 548, top: 326, bottom: 432 },
    { side: 'left' as const, left: 372, right: 548, top: 540, bottom: 644 },
    { side: 'right' as const, left: 892, right: 1068, top: 108, bottom: 204 },
    { side: 'right' as const, left: 892, right: 1068, top: 326, bottom: 432 },
    { side: 'right' as const, left: 892, right: 1068, top: 540, bottom: 644 },
  ];

  const outerCards = [
    { id: 'telemetry' as const, side: 'left' as const, left: 12, right: 340, top: 12, bottom: 202 },
    { id: 'neural-dsp' as const, side: 'left' as const, left: 12, right: 340, top: 210, bottom: 410 },
    { id: 'neural-data-stream' as const, side: 'left' as const, left: 12, right: 340, top: 418, bottom: 520 },
    { id: 'logs' as const, side: 'left' as const, left: 12, right: 340, top: 528, bottom: 672 },
    { id: 'transcript' as const, side: 'right' as const, left: 1100, right: 1428, top: 12, bottom: 175 },
    { id: 'weather' as const, side: 'right' as const, left: 1100, right: 1428, top: 185, bottom: 485 },
    { id: 'command-control' as const, side: 'right' as const, left: 1100, right: 1428, top: 495, bottom: 672 },
  ];

  const connectors = computeOuterCardConnectors(
    1440,
    700,
    720,
    340,
    136,
    outerCards,
    innerObstacles
  );

  assert.equal(connectors.length, 7);

  for (const conn of connectors) {
    const card = outerCards.find((c) => c.id === conn.id)!;
    const expectedX = conn.side === 'left' ? card.right : card.left;
    assert.equal(conn.nodeAnchorX, expectedX);
    assert.ok(conn.nodeAnchorY >= card.top && conn.nodeAnchorY <= card.bottom);
    assert.ok(conn.pathD.includes(' C '));
    assert.ok(!conn.pathD.includes(' L '));
    assert.ok(conn.pathD.endsWith(`${conn.nodeAnchorX} ${conn.nodeAnchorY}`));

    const dist = Math.hypot(conn.coreAnchorX - 720, conn.coreAnchorY - 340);
    assert.ok(Math.abs(dist - 136) <= 2);

    const sideObs = innerObstacles.filter((o) => o.side === conn.side);
    for (const obs of sideObs) {
      assert.ok(
        conn.corridorY <= obs.top || conn.corridorY >= obs.bottom,
        `Connector ${conn.id} corridorY (${conn.corridorY}) crossed inner card [${obs.top}, ${obs.bottom}]`
      );
    }
  }
});
