import React from "react";
import { useShu } from "../context/ShuContext";
export const WeatherForecastCard: React.FC<{ className?: string }> = ({
  className = "",
}) => {
  return (
    <section className={"holo-surface rounded-2xl p-4 " + className}>
      <h2>Weather</h2>
      <p>Not configured. No location data is collected.</p>
    </section>
  );
};
