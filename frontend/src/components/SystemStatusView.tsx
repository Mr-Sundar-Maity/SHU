import React from "react";
import { useShu } from "../context/ShuContext";
export const SystemStatusView: React.FC<{ className?: string }> = ({
  className = "",
}) => {
  const { statusBanner, settings, systemMetrics: metrics } = useShu();
  const percent = (value: number | null | undefined) =>
    typeof value === "number" ? `${value.toFixed(1)}%` : "Unavailable";
  const gib = (value: number | null | undefined) =>
    typeof value === "number"
      ? `${(value / 1024 ** 3).toFixed(1)} GiB`
      : "Unavailable";
  return (
    <section className={"holo-surface rounded-2xl p-4 " + className}>
      <h2>Runtime status</h2>
      <p>{statusBanner}</p>
      <p>{settings.localModel || "Awaiting runtime"}</p>
      <dl className="mt-2 space-y-1 text-xs text-slate-300">
        <div className="flex justify-between gap-2">
          <dt>System CPU</dt>
          <dd>{percent(metrics?.cpuPercent)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>System RAM</dt>
          <dd>{percent(metrics?.memoryPercent)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>RAM used / total</dt>
          <dd>
            {gib(metrics?.memoryUsedBytes)} / {gib(metrics?.memoryTotalBytes)}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>Data volume free</dt>
          <dd>{gib(metrics?.diskFreeBytes)}</dd>
        </div>
      </dl>
      <p className="mt-2 text-[10px] text-slate-400">
        Whole system; refreshed every 2 seconds.
      </p>
    </section>
  );
};
