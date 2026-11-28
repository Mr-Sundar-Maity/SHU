import type { HoloColorThemeId } from '../utils/colorTheme';

export type ShuTab =
  | 'assistant'
  | 'memory'
  | 'reminders'
  | 'communications'
  | 'workflows'
  | 'settings'
  | 'privacy';

export type AssistantState =
  | 'ready'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'stopped';

export interface TranscriptEntry {
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  mode?: 'direct' | 'plan' | 'voice';
  timestamp: string;
  rating?: number;
  ratingNote?: string;
}

export type MemoryCategory = 'Preference' | 'Fact' | 'Context' | 'Contact';

export interface MemoryItem {
  id: string;
  type: MemoryCategory;
  content: string;
  approved: boolean;
  updatedAt: string;
}

export type ReminderStatus = 'Scheduled' | 'Snoozed' | 'Completed' | 'Cancelled';

export interface ReminderItem {
  id: string;
  due: string;
  reminder: string;
  status: ReminderStatus;
  quietMode: boolean;
}

export type CommunicationChannel = 'Email' | 'WhatsApp';

export interface CommunicationDraft {
  channel: CommunicationChannel;
  recipient: string;
  subject: string;
  message: string;
  exactPreview: string;
  savedToProviderDrafts: boolean;
  sent: boolean;
}

export interface WhatsAppContact {
  id: string;
  name: string;
  phone: string;
}

export type WorkflowStatus = 'Approved' | 'Pending approval' | 'Revoked';

export interface WorkflowItem {
  id: string;
  name: string;
  status: WorkflowStatus;
  tools: string[];
  steps: string[];
  lastPreview: string;
}

export interface ShuSettings {
  voiceLanguage: string;
  provider: string;
  microphone: string;
  dataFolder: string;
  localModel: string;
  emergencyHotkey: string;
  bridgeUrl: string;
  colorTheme: HoloColorThemeId;
}

export type BridgeConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface SystemMetricsSnapshot {
  cpuPercent: number | null;
  memoryPercent: number | null;
  memoryUsedBytes: number | null;
  memoryTotalBytes: number | null;
  diskFreeBytes: number | null;
  sampledAt: string | null;
}

export interface DuplicatePair {
  a: MemoryItem;
  b: MemoryItem;
  similarity: number;
}
