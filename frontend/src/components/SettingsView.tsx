import React from "react";
import { useShu } from "../context/ShuContext";
export const SettingsView: React.FC = () => {
  const { settings, updateSetting, setActiveTab } = useShu();
  return (
    <section className="holo-surface m-6 rounded-2xl p-6">
      <h1>Settings</h1>
      <p>These values come from the running SHU configuration.</p>
      {Object.entries(settings)
        .filter(([k]) => k !== "colorTheme")
        .map(([key, value]) => (
          <p key={key}>
            <strong>{key}</strong>: {value || "Not configured"}
          </p>
        ))}
      <button onClick={() => updateSetting("provider", settings.provider)}>
        Open runtime settings
      </button>
      <button onClick={() => setActiveTab("assistant")}>Back</button>
    </section>
  );
};
