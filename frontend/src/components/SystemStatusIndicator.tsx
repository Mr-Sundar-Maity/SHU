import React from "react";
import { useShu } from "../context/ShuContext";
export const SystemStatusIndicator: React.FC<{ className?: string }> = ({
  className = "",
}) => {
  const { assistantState } = useShu();
  return (
    <span role="status" className={className}>
      {assistantState}
    </span>
  );
};
