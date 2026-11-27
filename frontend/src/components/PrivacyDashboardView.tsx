import React from "react";
import { useShu } from "../context/ShuContext";
export const PrivacyDashboardView: React.FC = () => {
  const {
    setActiveTab,
    settings,
    isListening,
    exportApprovedMemories,
    togglePrivacyPermission,
  } = useShu();
  return (
    <section className="holo-surface m-6 rounded-2xl p-6">
      <h1>Privacy and permissions</h1>
      <p>Data directory: {settings.dataFolder || "Awaiting runtime"}</p>
      <p>Microphone: {isListening ? "Voice session active" : "Idle"}</p>
      <p>
        Personal data stays in SHU's existing local store. The UI has no cloud
        credentials, browser speech recognition, or browser storage of
        conversations.
      </p>
      <p>
        Cloud AI, automation and microphone controls remain independent. Edge
        TTS requires network access under the existing sensitive-data policy.
      </p>
      <button onClick={() => togglePrivacyPermission("pythonBridge")}>
        Open permission controls
      </button>
      <button onClick={() => exportApprovedMemories()}>
        Review memory export
      </button>
      <button onClick={() => setActiveTab("assistant")}>Back</button>
    </section>
  );
};
