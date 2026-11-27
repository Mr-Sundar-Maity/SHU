import React from "react";
import { useShu } from "../context/ShuContext";
export const SystemStatusView: React.FC<{ className?: string }> = ({
  className = "",
}) => {
  const { statusBanner, settings } = useShu();
  return (
    <section className={"holo-surface rounded-2xl p-4 " + className}>
      <h2>Runtime status</h2>
      <p>{statusBanner}</p>
      <p>{settings.localModel || "Awaiting runtime"}</p>
      <p>CPU / RAM / latency: not measured</p>
    </section>
  );
};
