import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DATA_GRID_COLUMNS,
  DATA_GRID_NODES,
  DATA_GRID_ROWS,
  DATA_GRID_STREAMS,
  computeGridCellRippleDelayMs,
  getDataGridProfile,
} from './dataGrid';

test('dataGrid tracks stay within configured CSS grid dimensions', () => {
  assert.ok(DATA_GRID_STREAMS.length >= 8);
  for (const stream of DATA_GRID_STREAMS) {
    if (stream.axis === 'vertical') {
      assert.ok(stream.trackIndex >= 1 && stream.trackIndex <= DATA_GRID_COLUMNS);
    } else {
      assert.ok(stream.trackIndex >= 1 && stream.trackIndex <= DATA_GRID_ROWS);
    }
    assert.ok(stream.durationSec > 0);
  }

  for (const node of DATA_GRID_NODES) {
    assert.ok(node.col >= 1 && node.col <= DATA_GRID_COLUMNS);
    assert.ok(node.row >= 1 && node.row <= DATA_GRID_ROWS);
  }
});

test('getDataGridProfile adapts processing stream speed and pause state by assistantState', () => {
  const ready = getDataGridProfile('ready');
  const thinking = getDataGridProfile('thinking');
  const listening = getDataGridProfile('listening');
  const stopped = getDataGridProfile('stopped');

  assert.equal(ready.paused, false);
  assert.equal(ready.toneClass, 'is-ready');
  assert.ok(thinking.speedMultiplier < ready.speedMultiplier);
  assert.ok(listening.opacityLevel > ready.opacityLevel);
  assert.equal(stopped.paused, true);
  assert.equal(stopped.toneClass, 'is-stopped');
});

test('computeGridCellRippleDelayMs expands radially from center to symmetric corners', () => {
  const centerDelay = computeGridCellRippleDelayMs(6, 4);
  const midDelay = computeGridCellRippleDelayMs(3, 4);
  const topLeftCorner = computeGridCellRippleDelayMs(1, 1);
  const bottomRightCorner = computeGridCellRippleDelayMs(12, 8);

  assert.ok(centerDelay < midDelay);
  assert.ok(midDelay < topLeftCorner);
  assert.equal(topLeftCorner, bottomRightCorner);
  assert.equal(topLeftCorner, 520);
  assert.ok(centerDelay >= 0);
});
