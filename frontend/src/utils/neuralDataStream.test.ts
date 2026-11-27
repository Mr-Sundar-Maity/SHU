import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_NEURAL_STREAM_ITEMS,
  appendThoughtStream,
  buildInitialNeuralStream,
  buildNeuralThoughtSnippet,
} from './neuralDataStream';

test('buildNeuralThoughtSnippet highlights processed commands and truncates long payloads cleanly', () => {
  const snippet = buildNeuralThoughtSnippet({
    state: 'thinking',
    seq: 4,
    timestamp: '21:14:02',
    commandText: 'Analyze atmospheric telemetry and schedule a briefing tomorrow morning',
  });

  assert.equal(snippet.channel, 'INTENT');
  assert.equal(snippet.highlighted, true);
  assert.ok(snippet.text.includes('Parsing directive "'));
  assert.ok(snippet.text.includes('…'));
});

test('appendThoughtStream caps cascaded stream at MAX_NEURAL_STREAM_ITEMS', () => {
  let stream = buildInitialNeuralStream('21:00:00');
  for (let i = 1; i <= 20; i += 1) {
    const next = buildNeuralThoughtSnippet({
      state: i % 2 === 0 ? 'thinking' : 'ready',
      seq: i,
      timestamp: `21:00:${String(i).padStart(2, '0')}`,
    });
    stream = appendThoughtStream(stream, next);
  }

  assert.equal(stream.length, MAX_NEURAL_STREAM_ITEMS);
  assert.equal(stream[stream.length - 1].id, 'nds-tick-20');
});
