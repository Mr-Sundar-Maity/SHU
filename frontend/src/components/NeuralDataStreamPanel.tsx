import React from "react";
import { useShu } from "../context/ShuContext";
export const NeuralDataStreamPanel: React.FC<{ className?: string }> = ({
  className = "",
}) => {
  const { statusBanner } = useShu();
  return (
    <section className={"holo-terminal rounded-2xl p-4 " + className}>
      <h2>Runtime events</h2>
      <p role="status">{statusBanner}</p>
    </section>
  );
};
