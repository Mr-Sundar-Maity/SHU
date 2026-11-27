import test from 'node:test';
import assert from 'node:assert/strict';
import type { TranscriptEntry } from '../types/shu';
import {
  INITIAL_VOICE_HISTORY_LOGS,
  MAX_DRAWER_VOICE_COMMANDS,
  buildVoiceCommandLogs,
  getRecentVoiceCommands,
  shouldAutoScrollTranscript,
  tokenizeStreamText,
} from './commandHistory';

test('buildVoiceCommandLogs includes initial logs and filters only user voice commands', () => {
  const transcript: TranscriptEntry[] = [
    { id: '1', role: 'assistant', text: 'Ready', mode: 'direct', timestamp: '10:00' },
    { id: '2', role: 'user', text: 'Typed command', mode: 'direct', timestamp: '10:01' },
    { id: '3', role: 'user', text: 'Remind me to stretch in 10 minutes', mode: 'voice', timestamp: '10:02' },
    { id: '4', role: 'system', text: 'Stopped', timestamp: '10:03' },
  ];

  const logs = buildVoiceCommandLogs(transcript);
  assert.equal(logs.length, INITIAL_VOICE_HISTORY_LOGS.length + 1);
  assert.equal(logs[logs.length - 1].text, 'Remind me to stretch in 10 minutes');
  assert.equal(logs[logs.length - 1].status, 'recognized');
});

test('getRecentVoiceCommands returns at most the last 5 commands newest first and respects clearedIds', () => {
  const transcript: TranscriptEntry[] = Array.from({ length: 6 }, (_, i) => ({
    id: `v-${i + 1}`,
    role: 'user',
    text: `Voice cmd ${i + 1}`,
    mode: 'voice',
    timestamp: `10:0${i}`,
  }));

  const logs = buildVoiceCommandLogs(transcript);
  const recent = getRecentVoiceCommands(logs);
  assert.equal(recent.length, MAX_DRAWER_VOICE_COMMANDS);
  assert.equal(recent[0].text, 'Voice cmd 6');
  assert.equal(recent[4].text, 'Voice cmd 2');

  const clearedIds = logs.map((item) => item.id);
  const afterClear = buildVoiceCommandLogs(transcript, INITIAL_VOICE_HISTORY_LOGS, clearedIds);
  assert.equal(afterClear.length, 0);
  assert.equal(getRecentVoiceCommands(afterClear).length, 0);
});

test('shouldAutoScrollTranscript keeps auto-scroll active near bottom and pauses when scrolled up', () => {
  assert.equal(
    shouldAutoScrollTranscript({ scrollHeight: 400, scrollTop: 220, clientHeight: 170 }),
    true
  );
  assert.equal(
    shouldAutoScrollTranscript({ scrollHeight: 400, scrollTop: 50, clientHeight: 170 }),
    false
  );
});

test('tokenizeStreamText preserves exact concatenated text across word chunks', () => {
  const sample = 'Planned 3 steps:\n1. Inspect sensors\n2. Verify state';
  const tokens = tokenizeStreamText(sample);
  assert.ok(tokens.length > 3);
  assert.equal(tokens.join(''), sample);
});
