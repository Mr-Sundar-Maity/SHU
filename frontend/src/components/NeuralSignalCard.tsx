import React from "react";
import { useShu } from "../context/ShuContext";
export const NeuralSignalCard: React.FC<{ className?: string }> = ({
  className = "",
}) => {
  const {
    voiceActivity,
    speechPaused,
    canPauseSpeech,
    canPlanVoice,
    toggleSpeechPause,
    planLastVoiceRequest,
  } = useShu();
  const buttonClass =
    "rounded-lg border border-sky-400/30 px-2 py-1 text-xs text-sky-200 hover:bg-sky-500/15 disabled:opacity-40 disabled:cursor-not-allowed";
  return (
    <section className={"holo-surface rounded-2xl p-4 " + className}>
      <h2>Voice engine</h2>
      <p role="status" aria-live="polite">
        {voiceActivity}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          className={buttonClass}
          disabled={!canPauseSpeech}
          aria-pressed={speechPaused}
          onClick={toggleSpeechPause}
        >
          {speechPaused ? "Resume speech" : "Pause speech"}
        </button>
        <button
          type="button"
          className={buttonClass}
          disabled={!canPlanVoice}
          onClick={planLastVoiceRequest}
        >
          Plan last voice request
        </button>
      </div>
    </section>
  );
};
