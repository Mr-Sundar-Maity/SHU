import type {
  CommunicationChannel,
  CommunicationDraft,
  DuplicatePair,
  MemoryItem,
  ReminderItem,
  WorkflowItem,
} from '../types/shu';

export function formatLocalDateTime(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  const hh = pad(date.getHours());
  const mm = pad(date.getMinutes());
  return `${y}-${m}-${d} ${hh}:${mm}`;
}

export function parseDueTimeString(dueStr: string): Date | null {
  const match = dueStr.trim().match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$/);
  if (!match) return null;
  const [, y, m, d, hh, mm] = match;
  const parsed = new Date(Number(y), Number(m) - 1, Number(d), Number(hh), Number(mm), 0, 0);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function snoozeDueTime(dueStr: string, minutes = 10, now = new Date()): string {
  const base = parseDueTimeString(dueStr);
  const target = base && base.getTime() > now.getTime() ? new Date(base) : new Date(now);
  target.setMinutes(target.getMinutes() + minutes);
  return formatLocalDateTime(target);
}

export interface ParsedReminderPhrase {
  reminderText: string;
  dueLocal: string;
  matchedRule: string;
}

export function parseNaturalReminderPhrase(
  phrase: string,
  now = new Date()
): ParsedReminderPhrase | null {
  const raw = phrase.trim();
  if (!raw) return null;

  const target = new Date(now.getTime());
  let cleaned = raw.replace(/^remind\s+me\s+(to\s+)?/i, '').trim();
  let matchedRule = 'default (+15m)';

  const relMatch = cleaned.match(/\bin\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs)\b/i);
  if (relMatch) {
    const amount = Number(relMatch[1]);
    const unit = relMatch[2].toLowerCase();
    if (unit.startsWith('hour') || unit.startsWith('hr')) {
      target.setHours(target.getHours() + amount);
    } else {
      target.setMinutes(target.getMinutes() + amount);
    }
    cleaned = cleaned.replace(relMatch[0], '').trim();
    matchedRule = `relative (+${amount} ${unit})`;
  } else {
    const isTomorrow = /\btomorrow\b/i.test(cleaned);
    if (isTomorrow) {
      target.setDate(target.getDate() + 1);
      cleaned = cleaned.replace(/\btomorrow\b/i, '').trim();
    }

    const timeMatch = cleaned.match(/\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b/i);
    if (timeMatch) {
      let hours = Number(timeMatch[1]);
      const mins = timeMatch[2] ? Number(timeMatch[2]) : 0;
      const meridiem = timeMatch[3]?.toLowerCase();
      if (meridiem === 'pm' && hours < 12) hours += 12;
      if (meridiem === 'am' && hours === 12) hours = 0;
      target.setHours(hours, mins, 0, 0);
      if (!isTomorrow && target.getTime() <= now.getTime()) {
        target.setDate(target.getDate() + 1);
      }
      cleaned = cleaned.replace(timeMatch[0], '').trim();
      matchedRule = isTomorrow ? 'tomorrow at time' : 'specific time';
    } else if (isTomorrow) {
      target.setHours(9, 0, 0, 0);
      matchedRule = 'tomorrow (09:00)';
    } else {
      target.setMinutes(target.getMinutes() + 15);
    }
  }

  cleaned = cleaned.replace(/[,.\s]+$/, '').replace(/^(to\s+)/i, '').trim();
  if (!cleaned) {
    cleaned = raw;
  }

  return {
    reminderText: cleaned.charAt(0).toUpperCase() + cleaned.slice(1),
    dueLocal: formatLocalDateTime(target),
    matchedRule,
  };
}

function tokenize(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .split(/\s+/)
      .filter((w) => w.length > 2)
  );
}

export function findDuplicateMemories(memories: MemoryItem[], threshold = 0.55): DuplicatePair[] {
  const pairs: DuplicatePair[] = [];
  for (let i = 0; i < memories.length; i += 1) {
    const tokensA = tokenize(memories[i].content);
    for (let j = i + 1; j < memories.length; j += 1) {
      const tokensB = tokenize(memories[j].content);
      if (tokensA.size === 0 || tokensB.size === 0) continue;
      let intersection = 0;
      for (const token of tokensA) {
        if (tokensB.has(token)) intersection += 1;
      }
      const union = tokensA.size + tokensB.size - intersection;
      const similarity = union === 0 ? 0 : intersection / union;
      if (similarity >= threshold) {
        pairs.push({ a: memories[i], b: memories[j], similarity: Number(similarity.toFixed(2)) });
      }
    }
  }
  return pairs;
}

export interface DraftValidationResult {
  valid: boolean;
  error?: string;
}

export function validateCommunicationDraft(
  channel: CommunicationChannel,
  recipient: string,
  subject: string,
  message: string
): DraftValidationResult {
  const cleanRecipient = recipient.trim();
  const cleanMessage = message.trim();

  if (!cleanRecipient) {
    return { valid: false, error: 'Recipient is required.' };
  }
  if (channel === 'Email') {
    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanRecipient);
    if (!emailOk) {
      return { valid: false, error: 'Enter a valid email address for Email drafts.' };
    }
    if (!subject.trim()) {
      return { valid: false, error: 'Subject is required for Email drafts.' };
    }
  } else {
    const phoneOk = /^\+[1-9]\d{6,14}$/.test(cleanRecipient);
    if (!phoneOk) {
      return {
        valid: false,
        error: 'Enter a valid +E.164 phone number (e.g. +14155550199) for WhatsApp.',
      };
    }
  }
  if (!cleanMessage) {
    return { valid: false, error: 'Message text cannot be empty.' };
  }
  return { valid: true };
}

export function buildExactDraftPreview(draft: Omit<CommunicationDraft, 'exactPreview' | 'savedToProviderDrafts' | 'sent'>): string {
  const lines = [
    `CHANNEL: ${draft.channel}`,
    `TO: ${draft.recipient.trim()}`,
  ];
  if (draft.channel === 'Email') {
    lines.push(`SUBJECT: ${draft.subject.trim()}`);
  }
  lines.push('---', draft.message.trim());
  return lines.join('\n');
}

export const CURRENT_TOOL_ALLOWLIST = new Set([
  'memory.read',
  'memory.write',
  'reminders.schedule',
  'communications.draft',
  'voice.speak',
  'files.summarize',
]);

export function revalidateWorkflowAllowlist(workflow: WorkflowItem): {
  allowed: boolean;
  blockedTools: string[];
} {
  const blockedTools = workflow.tools.filter((t) => !CURRENT_TOOL_ALLOWLIST.has(t));
  return {
    allowed: blockedTools.length === 0,
    blockedTools,
  };
}

export function formatWorkflowPreview(workflow: WorkflowItem): string {
  const check = revalidateWorkflowAllowlist(workflow);
  const allowlistLine = check.allowed
    ? 'Allowlist validation: PASSED (all tools permitted)'
    : `Allowlist validation: BLOCKED (${check.blockedTools.join(', ')})`;

  return [
    `Workflow: ${workflow.name} (${workflow.id})`,
    `Status: ${workflow.status}`,
    allowlistLine,
    `Tools: ${workflow.tools.join(', ') || 'None'}`,
    'Steps:',
    ...workflow.steps.map((s, idx) => `  ${idx + 1}. ${s}`),
  ].join('\n');
}

export interface CommandOutcome {
  reply: string;
  suggestedTab?: 'memory' | 'reminders' | 'communications' | 'workflows' | 'settings';
  parsedReminder?: ParsedReminderPhrase;
}

export function evaluateLocalVoiceCommand(
  rawInput: string,
  mode: 'direct' | 'plan' | 'voice',
  contextSummary: {
    memoryCount: number;
    activeReminders: ReminderItem[];
    approvedWorkflows: number;
  }
): CommandOutcome {
  const input = rawInput.trim();
  const lower = input.toLowerCase();

  if (lower.includes('remind') || /\bin\s+\d+\s*(min|minute|hour)/i.test(lower)) {
    const parsed = parseNaturalReminderPhrase(input);
    if (parsed) {
      return {
        reply: `Scheduled reminder "${parsed.reminderText}" for ${parsed.dueLocal} (${parsed.matchedRule}).`,
        suggestedTab: 'reminders',
        parsedReminder: parsed,
      };
    }
  }

  if (lower.includes('memory') || lower.includes('remember')) {
    return {
      reply: `You currently have ${contextSummary.memoryCount} approved memories stored locally. Open the Memory tab to add, correct, or audit duplicates.`,
      suggestedTab: 'memory',
    };
  }

  if (lower.includes('email') || lower.includes('whatsapp') || lower.includes('draft') || lower.includes('message')) {
    return {
      reply: `Local draft workspace is ready. Communications require an exact preview before confirmation or provider authorization.`,
      suggestedTab: 'communications',
    };
  }

  if (lower.includes('workflow') || lower.includes('replay') || lower.includes('routine')) {
    return {
      reply: `${contextSummary.approvedWorkflows} approved workflows are validated against the current tool allowlist.`,
      suggestedTab: 'workflows',
    };
  }

  if (lower.includes('setting') || lower.includes('microphone') || lower.includes('language') || lower.includes('python')) {
    return {
      reply: `Opening settings telemetry. You can adjust voice language, session provider, microphone input, or bind the local Python bridge.`,
      suggestedTab: 'settings',
    };
  }

  const taskIdMatch = input.match(/^(?:task\s*#?|#)?(\d{1,5})$/i);
  if (taskIdMatch) {
    const taskId = taskIdMatch[1];
    const matchingReminder = contextSummary.activeReminders.find((r) =>
      r.id.endsWith(`-${taskId}`) || r.id === taskId
    );
    if (matchingReminder) {
      return {
        reply: `Located Reminder #${taskId} (${matchingReminder.id}): "${matchingReminder.reminder}" scheduled for ${matchingReminder.due}.`,
        suggestedTab: 'reminders',
      };
    }
    return {
      reply:
        mode === 'plan'
          ? `Execution plan prepared for Task #${taskId}:\n1. Resolve local task manifest #${taskId}.\n2. Validate against active allowlist & ${contextSummary.memoryCount} memories.\n3. Ready for operator execution.`
          : `Dispatched numeric Task #${taskId} to local-first execution queue (${contextSummary.approvedWorkflows} workflows & ${contextSummary.memoryCount} memories in context).`,
    };
  }

  const prefixedMatch = input.match(/^(wf|rem|mem)-(\d{1,5})$/i);
  if (prefixedMatch) {
    const [, prefix, num] = prefixedMatch;
    const upperPrefix = prefix.toUpperCase();
    const targetTab =
      upperPrefix === 'WF' ? 'workflows' : upperPrefix === 'REM' ? 'reminders' : 'memory';
    return {
      reply: `Resolved identifier ${prefix.toLowerCase()}-${num} in ${targetTab} store. Ready for direct inspection or replay.`,
      suggestedTab: targetTab,
    };
  }

  if (mode === 'plan') {
    return {
      reply: `Execution plan drafted for "${input}":\n1. Parse local intent & verify tool allowlist.\n2. Check ${contextSummary.memoryCount} approved memories for context.\n3. Await explicit confirmation before external actions.`,
    };
  }

  if (lower.includes('status') || lower.includes('hello') || lower.includes('hi') || lower.includes('shu')) {
    return {
      reply: `SHU is active and local-first. ${contextSummary.activeReminders.length} active reminder(s), ${contextSummary.memoryCount} approved memories, and ${contextSummary.approvedWorkflows} approved workflows ready.`,
    };
  }

  return {
    reply: `Understood: "${input}". Processed via local-first pipeline (${contextSummary.memoryCount} memories in context). Connect the Python bridge in Settings to stream live local LLM & TTS output.`,
  };
}
