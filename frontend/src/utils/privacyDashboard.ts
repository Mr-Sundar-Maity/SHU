export type PrivacyPermissionKey =
  | 'microphone'
  | 'memoryStore'
  | 'weatherGeo'
  | 'voiceLogs'
  | 'pythonBridge';

export interface PrivacyPermissionItem {
  key: PrivacyPermissionKey;
  label: string;
  description: string;
  scope: string;
  retention: string;
  enabled: boolean;
}

export interface PrivacyDashboardState {
  permissions: Record<PrivacyPermissionKey, boolean>;
  gdprDeletionRequested: boolean;
  gdprDeletionRequestedAt: string | null;
  lastPurgedAt: string | null;
  erasureTicketId: string | null;
}

export interface PrivacyDataFlowItem {
  id: string;
  channel: string;
  destination: string;
  active: boolean;
  volumeLabel: string;
  complianceTag: string;
}

export const PRIVACY_PERMISSION_SPECS: readonly Omit<PrivacyPermissionItem, 'enabled'>[] = [
  {
    key: 'microphone',
    label: 'Microphone Acoustic Stream',
    description: 'Real-time Web Audio & speech recognition waveform capture.',
    scope: 'In-memory FFT buffer',
    retention: 'Ephemeral (0s persisted)',
  },
  {
    key: 'memoryStore',
    label: 'Approved Local Memory Vault',
    description: 'Stores user-approved preferences, context, and contacts locally.',
    scope: 'Browser localStorage',
    retention: 'Until user delete / GDPR purge',
  },
  {
    key: 'weatherGeo',
    label: 'Live Geolocation Telemetry',
    description: 'Coordinates sent only to Open-Meteo for local weather forecasts.',
    scope: 'Lat/Lon coordinates',
    retention: 'Session transient',
  },
  {
    key: 'voiceLogs',
    label: 'Voice Command History Log',
    description: 'Retains recent interpreted voice directives for quick replay.',
    scope: 'Local session transcript',
    retention: 'Rolling 5-command drawer',
  },
  {
    key: 'pythonBridge',
    label: 'Local Python Runtime Bridge',
    description: 'Optional WebSocket bridge to local Ollama / Whisper runtime.',
    scope: '127.0.0.1 loopback',
    retention: 'Session socket only',
  },
];

export const DEFAULT_PRIVACY_STATE: PrivacyDashboardState = {
  permissions: {
    microphone: true,
    memoryStore: true,
    weatherGeo: true,
    voiceLogs: true,
    pythonBridge: false,
  },
  gdprDeletionRequested: false,
  gdprDeletionRequestedAt: null,
  lastPurgedAt: null,
  erasureTicketId: null,
};

export function normalizePrivacyState(raw: unknown): PrivacyDashboardState {
  if (!raw || typeof raw !== 'object') return DEFAULT_PRIVACY_STATE;
  const candidate = raw as Partial<PrivacyDashboardState>;
  const perms = (candidate.permissions ?? {}) as Partial<Record<PrivacyPermissionKey, unknown>>;

  return {
    permissions: {
      microphone:
        typeof perms.microphone === 'boolean'
          ? perms.microphone
          : DEFAULT_PRIVACY_STATE.permissions.microphone,
      memoryStore:
        typeof perms.memoryStore === 'boolean'
          ? perms.memoryStore
          : DEFAULT_PRIVACY_STATE.permissions.memoryStore,
      weatherGeo:
        typeof perms.weatherGeo === 'boolean'
          ? perms.weatherGeo
          : DEFAULT_PRIVACY_STATE.permissions.weatherGeo,
      voiceLogs:
        typeof perms.voiceLogs === 'boolean'
          ? perms.voiceLogs
          : DEFAULT_PRIVACY_STATE.permissions.voiceLogs,
      pythonBridge:
        typeof perms.pythonBridge === 'boolean'
          ? perms.pythonBridge
          : DEFAULT_PRIVACY_STATE.permissions.pythonBridge,
    },
    gdprDeletionRequested: Boolean(candidate.gdprDeletionRequested),
    gdprDeletionRequestedAt:
      typeof candidate.gdprDeletionRequestedAt === 'string'
        ? candidate.gdprDeletionRequestedAt
        : null,
    lastPurgedAt: typeof candidate.lastPurgedAt === 'string' ? candidate.lastPurgedAt : null,
    erasureTicketId:
      typeof candidate.erasureTicketId === 'string' ? candidate.erasureTicketId : null,
  };
}

export function getPrivacyPermissionItems(
  state: PrivacyDashboardState
): PrivacyPermissionItem[] {
  return PRIVACY_PERMISSION_SPECS.map((spec) => ({
    ...spec,
    enabled: state.permissions[spec.key],
  }));
}

export function togglePrivacyPermissionInState(
  state: PrivacyDashboardState,
  key: PrivacyPermissionKey
): PrivacyDashboardState {
  return {
    ...state,
    permissions: {
      ...state.permissions,
      [key]: !state.permissions[key],
    },
  };
}

export function toggleGdprDeletionState(
  state: PrivacyDashboardState,
  nowLabel: string,
  explicitEnabled?: boolean
): PrivacyDashboardState {
  const nextEnabled =
    typeof explicitEnabled === 'boolean' ? explicitEnabled : !state.gdprDeletionRequested;

  if (!nextEnabled) {
    return {
      ...state,
      gdprDeletionRequested: false,
      gdprDeletionRequestedAt: null,
      erasureTicketId: null,
    };
  }

  return {
    ...state,
    gdprDeletionRequested: true,
    gdprDeletionRequestedAt: nowLabel,
    erasureTicketId: state.erasureTicketId ?? `GDPR-ART17-${nowLabel.replace(/\D/g, '').slice(-6) || '1042'}`,
  };
}

export function executeGdprPurgeState(
  state: PrivacyDashboardState,
  nowLabel: string
): PrivacyDashboardState {
  return {
    ...state,
    gdprDeletionRequested: true,
    gdprDeletionRequestedAt: state.gdprDeletionRequestedAt ?? nowLabel,
    lastPurgedAt: nowLabel,
    erasureTicketId: state.erasureTicketId ?? `GDPR-ART17-${nowLabel.replace(/\D/g, '').slice(-6) || '1042'}`,
  };
}

export function buildPrivacyDataFlows(params: {
  state: PrivacyDashboardState;
  isListening: boolean;
  bridgeConnected: boolean;
  memoryCount: number;
  transcriptCount: number;
  voiceLogCount: number;
}): PrivacyDataFlowItem[] {
  const { state, isListening, bridgeConnected, memoryCount, transcriptCount, voiceLogCount } =
    params;

  return [
    {
      id: 'flow-audio',
      channel: 'Audio Capture',
      destination: 'Local WebAudio Analyser',
      active: state.permissions.microphone && isListening,
      volumeLabel: state.permissions.microphone
        ? isListening
          ? 'Streaming · 48kHz local'
          : 'Armed · Standby'
        : 'Blocked by policy',
      complianceTag: 'Art. 5 Minimization',
    },
    {
      id: 'flow-memory',
      channel: 'Memory Store',
      destination: 'Device localStorage',
      active: state.permissions.memoryStore,
      volumeLabel: state.permissions.memoryStore
        ? `${memoryCount} approved records`
        : 'Storage paused',
      complianceTag: 'Local-First Vault',
    },
    {
      id: 'flow-weather',
      channel: 'Geo Forecast',
      destination: 'api.open-meteo.com',
      active: state.permissions.weatherGeo,
      volumeLabel: state.permissions.weatherGeo ? 'Coarse coords · No ID' : 'Location masked',
      complianceTag: 'Zero Tracking',
    },
    {
      id: 'flow-logs',
      channel: 'Command Logs',
      destination: 'Session Drawer + Transcript',
      active: state.permissions.voiceLogs,
      volumeLabel: state.permissions.voiceLogs
        ? `${voiceLogCount} voice · ${transcriptCount} msgs`
        : 'Logging suppressed',
      complianceTag: 'Art. 17 Erasable',
    },
    {
      id: 'flow-bridge',
      channel: 'Runtime Socket',
      destination: '127.0.0.1 WebSocket',
      active: state.permissions.pythonBridge && bridgeConnected,
      volumeLabel: bridgeConnected ? 'Loopback linked' : 'Local browser only',
      complianceTag: 'Loopback Isolated',
    },
  ];
}

export function buildPersonalDataExportPayload(params: {
  exportedAt: string;
  privacyState: PrivacyDashboardState;
  memoryCount: number;
  reminderCount: number;
  transcriptCount: number;
}): string {
  return JSON.stringify(
    {
      schema: 'shu.gdpr.article20.export.v1',
      exportedAt: params.exportedAt,
      gdprDeletionRequested: params.privacyState.gdprDeletionRequested,
      erasureTicketId: params.privacyState.erasureTicketId,
      permissions: params.privacyState.permissions,
      localRecordCounts: {
        memories: params.memoryCount,
        reminders: params.reminderCount,
        transcriptMessages: params.transcriptCount,
      },
    },
    null,
    2
  );
}
