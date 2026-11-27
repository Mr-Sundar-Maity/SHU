import React from "react";
import { useShu } from "../context/ShuContext";
export const NeuralSignalCard: React.FC<{ className?: string }> = ({
  className = "",
}) => {
  const { isListening, isMuted } = useShu();
  return (
    <section className={"holo-surface rounded-2xl p-4 " + className}>
      <h2>Voice engine</h2>
      <p>
        {isMuted
          ? "Muted"
          : isListening
            ? "Voice session active"
            : "Microphone idle"}
      </p>
      <p>Waveform telemetry is not available.</p>
    </section>
  );
};
