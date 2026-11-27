import test from 'node:test';
import assert from 'node:assert/strict';
import { formatHoloClockSnapshot, formatUtcOffsetFromMinutes } from './holoClock';

test('formatUtcOffsetFromMinutes formats positive, negative, half-hour, and zero offsets', () => {
  assert.equal(formatUtcOffsetFromMinutes(0), 'UTC+0');
  assert.equal(formatUtcOffsetFromMinutes(480), 'UTC-8');
  assert.equal(formatUtcOffsetFromMinutes(-330), 'UTC+5:30');
  assert.equal(formatUtcOffsetFromMinutes(-540), 'UTC+9');
});

test('formatHoloClockSnapshot formats 24-hour and 12-hour UTC time cleanly with timezone label', () => {
  const sample = new Date('2026-11-25T16:42:51.000Z');

  const utc24 = formatHoloClockSnapshot(sample, { use12Hour: false, timeZone: 'UTC' });
  assert.equal(utc24.hours, '16');
  assert.equal(utc24.minutes, '42');
  assert.equal(utc24.seconds, '51');
  assert.equal(utc24.period, null);
  assert.equal(utc24.timeText, '16:42:51');
  assert.equal(utc24.compactTimeText, '16:42');
  assert.equal(utc24.tzAbbr, 'UTC');
  assert.equal(utc24.utcOffset, 'UTC+0');
  assert.equal(utc24.ianaZone, 'UTC');

  const tokyo12 = formatHoloClockSnapshot(sample, {
    use12Hour: true,
    timeZone: 'Asia/Tokyo',
  });
  assert.equal(tokyo12.hours, '01');
  assert.equal(tokyo12.minutes, '42');
  assert.equal(tokyo12.seconds, '51');
  assert.equal(tokyo12.period, 'AM');
  assert.equal(tokyo12.timeText, '01:42:51 AM');
  assert.equal(tokyo12.utcOffset, 'UTC+9');
});
