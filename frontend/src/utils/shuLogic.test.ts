import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildExactDraftPreview,
  evaluateLocalVoiceCommand,
  findDuplicateMemories,
  parseNaturalReminderPhrase,
  revalidateWorkflowAllowlist,
  snoozeDueTime,
  validateCommunicationDraft,
} from './shuLogic';
import type { MemoryItem, WorkflowItem } from '../types/shu';

test('parseNaturalReminderPhrase extracts relative minutes accurately', () => {
  const now = new Date(2026, 10, 24, 20, 10, 0, 0);
  const parsed = parseNaturalReminderPhrase('Remind me to stretch in 20 minutes', now);
  assert.ok(parsed);
  assert.equal(parsed.reminderText, 'Stretch');
  assert.equal(parsed.dueLocal, '2026-11-24 20:30');
});

test('parseNaturalReminderPhrase extracts tomorrow at 9 AM', () => {
  const now = new Date(2026, 10, 24, 20, 10, 0, 0);
  const parsed = parseNaturalReminderPhrase('call Sam tomorrow at 9 AM', now);
  assert.ok(parsed);
  assert.equal(parsed.reminderText, 'Call Sam');
  assert.equal(parsed.dueLocal, '2026-11-25 09:00');
});

test('snoozeDueTime adds 10 minutes to future due timestamp', () => {
  const now = new Date(2026, 10, 24, 20, 0, 0, 0);
  assert.equal(snoozeDueTime('2026-11-24 20:30', 10, now), '2026-11-24 20:40');
});

test('findDuplicateMemories detects high-overlap memories', () => {
  const items: MemoryItem[] = [
    { id: 'mem-1', type: 'Preference', content: 'User prefers morning briefings at 8 AM', approved: true, updatedAt: '2026-11-24' },
    { id: 'mem-2', type: 'Preference', content: 'User prefers morning briefings at 8 AM daily', approved: true, updatedAt: '2026-11-24' },
    { id: 'mem-3', type: 'Fact', content: 'Project repo is stored in local workspace', approved: true, updatedAt: '2026-11-24' },
  ];
  const pairs = findDuplicateMemories(items, 0.55);
  assert.equal(pairs.length, 1);
  assert.equal(pairs[0].a.id, 'mem-1');
  assert.equal(pairs[0].b.id, 'mem-2');
});

test('validateCommunicationDraft enforces email and E.164 WhatsApp formats', () => {
  assert.equal(validateCommunicationDraft('Email', 'bad-email', 'Subj', 'Hi').valid, false);
  assert.equal(validateCommunicationDraft('Email', 'sam@example.com', 'Subj', 'Hi').valid, true);
  assert.equal(validateCommunicationDraft('WhatsApp', '5551234', '', 'Hi').valid, false);
  assert.equal(validateCommunicationDraft('WhatsApp', '+14155550199', '', 'Hi').valid, true);
});

test('buildExactDraftPreview produces deterministic exact preview', () => {
  const preview = buildExactDraftPreview({
    channel: 'Email',
    recipient: 'sam@example.com',
    subject: 'Sync',
    message: 'See you at 10 AM.',
  });
  assert.equal(
    preview,
    'CHANNEL: Email\nTO: sam@example.com\nSUBJECT: Sync\n---\nSee you at 10 AM.'
  );
});

test('revalidateWorkflowAllowlist flags disallowed tools', () => {
  const wf: WorkflowItem = {
    id: 'wf-1',
    name: 'Morning Digest',
    status: 'Approved',
    tools: ['memory.read', 'shell.exec'],
    steps: ['Read memories', 'Run command'],
    lastPreview: '',
  };
  const check = revalidateWorkflowAllowlist(wf);
  assert.equal(check.allowed, false);
  assert.deepEqual(check.blockedTools, ['shell.exec']);
});

test('evaluateLocalVoiceCommand parses reminder commands cleanly', () => {
  const result = evaluateLocalVoiceCommand('Remind me to check build in 15 minutes', 'voice', {
    memoryCount: 4,
    activeReminders: [],
    approvedWorkflows: 2,
  });
  assert.ok(result.parsedReminder);
  assert.equal(result.suggestedTab, 'reminders');
});
