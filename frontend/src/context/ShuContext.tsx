import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type {
  AssistantState,
  BridgeConnectionStatus,
  CommunicationChannel,
  CommunicationDraft,
  DuplicatePair,
  MemoryCategory,
  MemoryItem,
  ReminderItem,
  ShuSettings,
  ShuTab,
  TranscriptEntry,
  WhatsAppContact,
  WorkflowItem,
} from "../types/shu";
import { DEFAULT_COLOR_THEME, getHoloColorTheme } from "../utils/colorTheme";
import {
  DEFAULT_PRIVACY_STATE,
  type PrivacyDashboardState,
  type PrivacyPermissionKey,
} from "../utils/privacyDashboard";
import type { ActiveWorkflowExecution } from "../utils/workflowProgress";
export interface WakeWordOverlayState {
  active: boolean;
  phrase: string;
  seq: number;
}

interface ShuContextValue {
  activeTab: ShuTab;
  setActiveTab: (tab: ShuTab) => void;
  openRuntimeControls: (tab: string) => void;
  assistantState: AssistantState;
  isListening: boolean;
  isMuted: boolean;
  isUserSpeaking: boolean;
  audioLevel: number;
  audioAnalyser: AnalyserNode | null;
  recognizedVoiceSeq: number;
  commandProcessedSeq: number;
  lastProcessedCommand: string;
  dataGridRippleSeq: number;
  triggerDataGridRipple: () => void;
  wakeWordOverlay: WakeWordOverlayState;
  triggerWakeWordOverlay: (phrase?: string) => void;
  dismissWakeWordOverlay: () => void;
  logsCleared: boolean;
  clearedVoiceIds: string[];
  clearLogs: () => void;
  clearVoiceHistory: () => void;
  toggleAssistantMute: () => void;
  runSystemDiagnostic: () => void;
  statusBanner: string;
  transcript: TranscriptEntry[];
  sendCommand: (text: string, mode?: "direct" | "plan" | "voice") => void;
  toggleListening: () => void;
  toggleMute: () => void;
  triggerEmergencyStop: () => void;
  resumeAssistant: () => void;
  rateLastTask: (rating: number, note?: string) => void;
  hasLastTask: boolean;

  // Memory
  memories: MemoryItem[];
  selectedMemoryId: string | null;
  setSelectedMemoryId: (id: string | null) => void;
  addApprovedMemory: (type: MemoryCategory, content: string) => void;
  correctSelectedMemory: (
    id: string,
    type: MemoryCategory,
    content: string,
  ) => void;
  deleteSelectedMemory: (id: string) => void;
  refreshMemories: () => void;
  exportApprovedMemories: () => string;
  duplicatePairs: DuplicatePair[];
  refreshDuplicateScan: () => DuplicatePair[];
  mergeDuplicatePair: (keepId: string, removeId: string) => void;

  // Reminders
  reminders: ReminderItem[];
  selectedReminderId: string | null;
  setSelectedReminderId: (id: string | null) => void;
  quietMode: boolean;
  setQuietMode: (quiet: boolean) => void;
  addReminder: (
    reminderText: string,
    dueLocal: string,
  ) => { ok: boolean; error?: string };
  scheduleNaturalPhrase: (phrase: string) => {
    ok: boolean;
    parsed?: { reminderText: string; dueLocal: string; matchedRule: string };
    error?: string;
  };
  snoozeReminder: (id: string) => void;
  completeReminder: (id: string) => void;
  cancelReminder: (id: string) => void;

  // Communications
  draft: CommunicationDraft;
  canSendDraft: boolean;
  canSaveDraft: boolean;
  updateDraftField: <
    K extends keyof Pick<
      CommunicationDraft,
      "channel" | "recipient" | "subject" | "message"
    >,
  >(
    field: K,
    value: CommunicationDraft[K],
  ) => void;
  createAndPreviewDraft: () => { ok: boolean; error?: string };
  saveReviewedEmailToProviderDrafts: () => { ok: boolean; error?: string };
  confirmAndSendExactPreview: () => { ok: boolean; error?: string };
  whatsappContacts: WhatsAppContact[];
  addWhatsAppContact: (
    name: string,
    phone: string,
  ) => { ok: boolean; error?: string };
  removeWhatsAppContact: (id: string) => void;

  // Workflows
  workflows: WorkflowItem[];
  selectedWorkflowId: string | null;
  setSelectedWorkflowId: (id: string | null) => void;
  workflowPreviewText: string;
  activeWorkflowExecution: ActiveWorkflowExecution | null;
  refreshWorkflows: () => void;
  reviewWorkflow: (id: string) => void;
  editWorkflow: (
    id: string,
    name: string,
    tools: string[],
    steps: string[],
  ) => void;
  approveWorkflow: (id: string) => void;
  revokeWorkflow: (id: string) => void;
  replayWorkflow: (id: string) => void;

  // Settings & Python Bridge
  settings: ShuSettings;
  updateSetting: <K extends keyof ShuSettings>(
    key: K,
    value: ShuSettings[K],
  ) => void;
  bridgeStatus: BridgeConnectionStatus;
  connectPythonBridge: () => void;
  disconnectPythonBridge: () => void;

  // Privacy & GDPR
  privacyState: PrivacyDashboardState;
  togglePrivacyPermission: (key: PrivacyPermissionKey) => void;
  toggleGdprDeletionRequest: (enabled?: boolean) => void;
  executeGdprDataPurge: () => void;
  exportGdprPersonalData: () => string;

  notification: { message: string; tone: "info" | "success" | "error" } | null;
  clearNotification: () => void;
}

const ShuContext = createContext<ShuContextValue | null>(null);
interface NativeBridge {
  read(cb: (raw: string) => void): void;
  dispatch(action: string, raw: string): void;
  changed: { connect(cb: (raw: string) => void): void };
}
declare global {
  interface Window {
    qt?: { webChannelTransport: unknown };
    QWebChannel?: new (
      transport: unknown,
      cb: (channel: { objects: { shu: NativeBridge } }) => void,
    ) => unknown;
  }
}
const initialDraft: CommunicationDraft = {
  channel: "Email",
  recipient: "",
  subject: "",
  message: "",
  exactPreview: "",
  sent: false,
  savedToProviderDrafts: false,
};
export const ShuProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [activeTab, setActiveTab] = useState<ShuTab>("assistant");
  const [state, setState] = useState<Partial<ShuContextValue>>({});
  const [draft, setDraft] = useState(initialDraft);
  const [colorTheme, setColorTheme] = useState(DEFAULT_COLOR_THEME);
  const [notification, setNotification] =
    useState<ShuContextValue["notification"]>(null);
  const [bridgeStatus, setBridgeStatus] =
    useState<BridgeConnectionStatus>("connecting");
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null);
  const [selectedReminderId, setSelectedReminderId] = useState<string | null>(
    null,
  );
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(
    null,
  );
  const bridge = useRef<NativeBridge | null>(null);
  const request = (action: string, data: object = {}) => {
    if (!bridge.current) {
      setNotification({
        message:
          "Open SHU using python -m app.cli gui. No browser simulation is active.",
        tone: "error",
      });
      return { ok: false, error: "Desktop runtime disconnected" };
    }
    bridge.current.dispatch(action, JSON.stringify(data));
    return { ok: true };
  };
  const controls = (tab: string) => request("controls", { tab });
  useEffect(() => {
    let closed = false;
    const receive = (raw: string) => {
      if (closed) return;
      const data = JSON.parse(raw);
      setState(data);
      setDraft((previous) => ({
        ...previous,
        exactPreview: data.preview || "",
      }));
    };
    if (window.qt && window.QWebChannel)
      new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
        if (closed) return;
        bridge.current = channel.objects.shu;
        bridge.current.changed.connect(receive);
        bridge.current.read(receive);
        setBridgeStatus("connected");
      });
    else setBridgeStatus("disconnected");
    return () => {
      closed = true;
      bridge.current = null;
    };
  }, []);
  const settings: ShuSettings = {
    ...(state.settings || {
      voiceLanguage: "",
      provider: "",
      microphone: "",
      dataFolder: "",
      localModel: "",
      emergencyHotkey: "Ctrl+Alt+Pause",
      bridgeUrl: "Qt WebChannel",
      colorTheme: DEFAULT_COLOR_THEME,
    }),
    colorTheme,
  };
  useEffect(() => {
    const t = getHoloColorTheme(settings.colorTheme);
    document.documentElement.dataset.holoTheme = settings.colorTheme;
    for (const [k, v] of Object.entries({
      "primary-rgb": t.primaryRgb,
      "secondary-rgb": t.secondaryRgb,
      "accent-rgb": t.accentRgb,
      "soft-rgb": t.softRgb,
      "primary-hex": t.primaryCss,
      "secondary-hex": t.secondaryCss,
      "accent-hex": t.accentCss,
      gradient: t.gradientCss,
    }))
      document.documentElement.style.setProperty("--holo-" + k, v);
  }, [settings.colorTheme]);
  const value: ShuContextValue = {
    activeTab,
    setActiveTab,
    openRuntimeControls: controls,
    assistantState: state.assistantState || "ready",
    isListening: state.isListening || false,
    isMuted: state.isMuted || false,
    isUserSpeaking: false,
    audioLevel: 0,
    audioAnalyser: null,
    recognizedVoiceSeq: 0,
    commandProcessedSeq: 0,
    lastProcessedCommand: "",
    dataGridRippleSeq: 0,
    triggerDataGridRipple: () => {},
    wakeWordOverlay: { active: false, phrase: "", seq: 0 },
    triggerWakeWordOverlay: () => {},
    dismissWakeWordOverlay: () => {},
    logsCleared: true,
    clearedVoiceIds: [],
    clearLogs: () => request("reset"),
    clearVoiceHistory: () => request("reset"),
    toggleAssistantMute: () => request("mute"),
    runSystemDiagnostic: () => request("diagnostics"),
    statusBanner: state.statusBanner || "Connecting to SHU",
    transcript: state.transcript || [],
    sendCommand: (text, mode) =>
      request(mode === "plan" ? "plan" : "chat", { text }),
    toggleListening: () => request(state.isListening ? "stop_voice" : "listen"),
    toggleMute: () => request("mute"),
    triggerEmergencyStop: () => request("stop"),
    resumeAssistant: () => request("resume"),
    rateLastTask: () => request("rate"),
    hasLastTask: state.hasLastTask || false,
    memories: state.memories || [],
    selectedMemoryId,
    setSelectedMemoryId,
    addApprovedMemory: (type, content) =>
      request("save_memory", { type, content }),
    correctSelectedMemory: (id, type, content) =>
      request("correct_memory", { id, type, content }),
    deleteSelectedMemory: (id) => request("memory_delete", { id }),
    refreshMemories: () =>
      bridge.current?.read((raw) => setState(JSON.parse(raw))),
    exportApprovedMemories: () => {
      request("memory_export");
      return "";
    },
    duplicatePairs: [],
    refreshDuplicateScan: () => {
      request("memory_review");
      return [];
    },
    mergeDuplicatePair: () => request("memory_review"),
    reminders: state.reminders || [],
    selectedReminderId,
    setSelectedReminderId,
    quietMode: state.quietMode || false,
    setQuietMode: (enabled) => request("quiet", { enabled }),
    addReminder: (text, due) => request("add_reminder", { text, due }),
    scheduleNaturalPhrase: (text) => request("natural_reminder", { text }),
    snoozeReminder: (id) => request("reminder_snooze", { id }),
    completeReminder: (id) => request("reminder_complete", { id }),
    cancelReminder: (id) => request("reminder_cancel", { id }),
    draft,
    canSendDraft: state.canSendDraft || false,
    canSaveDraft: state.canSaveDraft || false,
    updateDraftField: (field, value) => {
      request("invalidate_draft");
      setDraft((previous) => ({
        ...previous,
        [field]: value,
        exactPreview: "",
        sent: false,
        savedToProviderDrafts: false,
      }));
    },
    createAndPreviewDraft: () => request("preview", draft),
    saveReviewedEmailToProviderDrafts: () => request("save_draft"),
    confirmAndSendExactPreview: () => request("send"),
    whatsappContacts: state.whatsappContacts || [],
    addWhatsAppContact: (name, phone) =>
      request("add_contact", { name, phone }),
    removeWhatsAppContact: (id) => request("delete_contact", { id }),
    workflows: state.workflows || [],
    selectedWorkflowId,
    setSelectedWorkflowId,
    workflowPreviewText: state.workflowPreviewText || "",
    activeWorkflowExecution: null,
    refreshWorkflows: () => request("refresh"),
    reviewWorkflow: (id) => request("workflow_review", { id }),
    editWorkflow: (id) => request("workflow_edit", { id }),
    approveWorkflow: (id) => request("workflow_approve", { id }),
    revokeWorkflow: (id) => request("workflow_revoke", { id }),
    replayWorkflow: (id) => request("workflow_replay", { id }),
    settings,
    updateSetting: (key, value) => {
      if (key === "colorTheme")
        setColorTheme(getHoloColorTheme(String(value)).id);
      else controls("settings");
    },
    bridgeStatus,
    connectPythonBridge: () => controls("settings"),
    disconnectPythonBridge: () => request("stop"),
    privacyState: {
      ...DEFAULT_PRIVACY_STATE,
      permissions: {
        microphone: state.isListening || false,
        memoryStore: true,
        weatherGeo: false,
        voiceLogs: false,
        pythonBridge: bridgeStatus === "connected",
      },
    },
    togglePrivacyPermission: () => controls("settings"),
    toggleGdprDeletionRequest: () => controls("memory"),
    executeGdprDataPurge: () => controls("memory"),
    exportGdprPersonalData: () => {
      request("memory_export");
      return "";
    },
    notification,
    clearNotification: () => setNotification(null),
  };
  return <ShuContext.Provider value={value}>{children}</ShuContext.Provider>;
};
export function useShu() {
  const value = useContext(ShuContext);
  if (!value) throw new Error("Missing ShuProvider");
  return value;
}
