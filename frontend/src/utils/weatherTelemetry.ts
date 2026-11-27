import type { AssistantState } from '../types/shu';

export interface WeatherPresetCity {
  id: string;
  name: string;
  region: string;
  lat: number;
  lon: number;
}

export const WEATHER_PRESET_CITIES: readonly WeatherPresetCity[] = [
  { id: 'kolkata', name: 'Kolkata', region: 'IN', lat: 22.5726, lon: 88.3639 },
  { id: 'bengaluru', name: 'Bengaluru', region: 'IN', lat: 12.9716, lon: 77.5946 },
  { id: 'san-francisco', name: 'San Francisco', region: 'US', lat: 37.7749, lon: -122.4194 },
  { id: 'tokyo', name: 'Tokyo', region: 'JP', lat: 35.6762, lon: 139.6503 },
  { id: 'london', name: 'London', region: 'UK', lat: 51.5072, lon: -0.1276 },
];

export type WeatherConditionKind =
  | 'clear'
  | 'partly-cloudy'
  | 'cloudy'
  | 'fog'
  | 'rain'
  | 'storm'
  | 'snow';

export type WeatherAlertSeverity = 'warning' | 'watch' | 'advisory';

export interface WeatherAlert {
  id: string;
  severity: WeatherAlertSeverity;
  title: string;
  description: string;
  source: string;
  expiresLabel?: string;
}

export interface HourlyWeatherPoint {
  hourLabel: string;
  tempC: number;
  precipProb: number;
}

export interface DailyForecastDay {
  dateIso: string;
  dayLabel: string;
  weatherCode: number;
  conditionLabel: string;
  conditionKind: WeatherConditionKind;
  tempMinC: number;
  tempMaxC: number;
  precipProbPct: number;
  trendDeltaC: number;
  trendDirection: 'up' | 'down' | 'steady';
  rangeStartPct: number;
  rangeWidthPct: number;
}

export interface WeatherSnapshot {
  locationLabel: string;
  temperatureC: number;
  apparentTempC: number;
  humidityPct: number;
  windKmh: number;
  windGustsKmh: number;
  windDirectionDeg: number;
  windCompass: string;
  pressureHpa: number;
  cloudCoverPct: number;
  weatherCode: number;
  conditionLabel: string;
  conditionKind: WeatherConditionKind;
  isDay: boolean;
  hourly: HourlyWeatherPoint[];
  daily: DailyForecastDay[];
  alerts: WeatherAlert[];
  source: 'live' | 'cached';
  updatedAt: string;
}

export interface ResolvedLiveLocation {
  lat: number;
  lon: number;
  label: string;
  countryCode: string;
  method: 'gps' | 'ip';
}

export function degreesToCompass(deg: number): string {
  if (!Number.isFinite(deg)) return 'N';
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const;
  const normalized = ((deg % 360) + 360) % 360;
  const idx = Math.round(normalized / 45) % 8;
  return dirs[idx];
}

export function describeWmoWeatherCode(code: number): {
  label: string;
  kind: WeatherConditionKind;
} {
  if (code === 0) return { label: 'Clear Sky', kind: 'clear' };
  if (code === 1 || code === 2) return { label: 'Partly Cloudy', kind: 'partly-cloudy' };
  if (code === 3) return { label: 'Overcast', kind: 'cloudy' };
  if (code === 45 || code === 48) return { label: 'Dense Fog', kind: 'fog' };
  if (code >= 51 && code <= 67) return { label: 'Rain Showers', kind: 'rain' };
  if (code >= 71 && code <= 77) return { label: 'Snowfall', kind: 'snow' };
  if (code >= 80 && code <= 82) return { label: 'Passing Rain', kind: 'rain' };
  if (code >= 85 && code <= 86) return { label: 'Snow Showers', kind: 'snow' };
  if (code >= 95) return { label: 'Thunderstorm', kind: 'storm' };
  return { label: 'Atmospheric Clear', kind: 'partly-cloudy' };
}

function formatClockTime(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function formatShortWeekday(dateIso: string, index: number, baseDate: Date): string {
  if (index === 0) return 'Today';
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(dateIso)
    ? new Date(`${dateIso}T12:00:00`)
    : new Date(baseDate.getTime() + index * 86_400_000);
  const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const;
  return weekdays[parsed.getDay()] ?? `D+${index}`;
}

function formatIsoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export interface RawDailyWeatherInput {
  dateIso: string;
  weatherCode: number;
  tempMinC: number;
  tempMaxC: number;
  precipProbPct: number;
}

export function finalizeFiveDayForecast(
  rawDays: readonly RawDailyWeatherInput[],
  baselineTempC: number,
  now: Date = new Date()
): DailyForecastDay[] {
  const slice = rawDays.slice(0, 5);
  if (slice.length === 0) return [];

  const allMins = slice.map((d) => d.tempMinC);
  const allMaxs = slice.map((d) => d.tempMaxC);
  const globalMin = Math.min(...allMins);
  const globalMax = Math.max(...allMaxs);
  const totalSpan = Math.max(2, globalMax - globalMin);

  return slice.map((day, idx) => {
    const minT = Math.round(Math.min(day.tempMinC, day.tempMaxC));
    const maxT = Math.round(Math.max(day.tempMinC, day.tempMaxC));
    const prevRef = idx === 0 ? Math.round(baselineTempC) : Math.round(slice[idx - 1].tempMaxC);
    const delta = maxT - prevRef;
    const trendDirection: DailyForecastDay['trendDirection'] =
      delta >= 1 ? 'up' : delta <= -1 ? 'down' : 'steady';

    const startPct = Math.max(0, Math.min(86, ((minT - globalMin) / totalSpan) * 100));
    const rawWidthPct = ((maxT - minT) / totalSpan) * 100;
    const widthPct = Math.max(14, Math.min(100 - startPct, rawWidthPct));

    const desc = describeWmoWeatherCode(day.weatherCode);
    return {
      dateIso: day.dateIso,
      dayLabel: formatShortWeekday(day.dateIso, idx, now),
      weatherCode: day.weatherCode,
      conditionLabel: desc.label,
      conditionKind: desc.kind,
      tempMinC: minT,
      tempMaxC: maxT,
      precipProbPct: Math.max(0, Math.min(100, Math.round(day.precipProbPct))),
      trendDeltaC: delta,
      trendDirection,
      rangeStartPct: Number(startPct.toFixed(1)),
      rangeWidthPct: Number(widthPct.toFixed(1)),
    };
  });
}

export function parseNwsWeatherAlerts(payload: unknown): WeatherAlert[] {
  if (!payload || typeof payload !== 'object') return [];
  const features = (payload as { features?: unknown }).features;
  if (!Array.isArray(features)) return [];

  const alerts: WeatherAlert[] = [];
  for (const item of features.slice(0, 4)) {
    if (!item || typeof item !== 'object') continue;
    const props = (item as { properties?: Record<string, unknown> }).properties;
    if (!props) continue;

    const event = typeof props.event === 'string' ? props.event.trim() : '';
    if (!event) continue;

    const rawSev = typeof props.severity === 'string' ? props.severity.toLowerCase() : '';
    const severity: WeatherAlertSeverity =
      rawSev === 'extreme' || rawSev === 'severe'
        ? 'warning'
        : rawSev === 'moderate'
        ? 'watch'
        : 'advisory';

    const headline =
      typeof props.headline === 'string' && props.headline.trim()
        ? props.headline.trim()
        : typeof props.description === 'string'
        ? props.description.slice(0, 120).trim()
        : `${event} active for current coordinates.`;

    const endsRaw = typeof props.ends === 'string' ? props.ends : '';
    const expiresMatch = endsRaw.match(/T(\d{2}:\d{2})/);

    alerts.push({
      id: `nws-${typeof props.id === 'string' ? props.id : alerts.length}`,
      severity,
      title: event,
      description: headline,
      source: 'NWS Live',
      expiresLabel: expiresMatch ? `Until ${expiresMatch[1]}` : undefined,
    });
  }
  return alerts;
}

export function deriveWeatherAlertsFromMetrics(params: {
  weatherCode: number;
  temperatureC: number;
  apparentTempC: number;
  windKmh: number;
  windGustsKmh: number;
  pressureHpa: number;
  hourly: readonly HourlyWeatherPoint[];
  daily: readonly DailyForecastDay[];
}): WeatherAlert[] {
  const alerts: WeatherAlert[] = [];
  const todayPrecip = params.daily[0]?.precipProbPct ?? 0;
  const maxHourlyPrecip = params.hourly.reduce(
    (max, pt) => Math.max(max, pt.precipProb),
    0
  );

  if (params.weatherCode >= 95 || params.daily[0]?.weatherCode >= 95) {
    alerts.push({
      id: 'meteo-storm',
      severity: 'warning',
      title: 'Thunderstorm Warning',
      description: `Convective storm cells detected (WMO ${params.weatherCode}). Expect lightning & squalls.`,
      source: 'Open-Meteo API',
    });
  }

  if (params.windGustsKmh >= 55 || params.windKmh >= 42) {
    const severe = params.windGustsKmh >= 70 || params.windKmh >= 55;
    alerts.push({
      id: 'meteo-wind',
      severity: severe ? 'warning' : 'advisory',
      title: severe ? 'High Wind Warning' : 'Strong Wind Advisory',
      description: `Sustained ${params.windKmh} km/h with gusts up to ${params.windGustsKmh} km/h.`,
      source: 'Open-Meteo API',
    });
  }

  if (
    [63, 65, 67, 81, 82].includes(params.weatherCode) ||
    maxHourlyPrecip >= 75 ||
    todayPrecip >= 80
  ) {
    alerts.push({
      id: 'meteo-rain',
      severity: 'watch',
      title: 'Heavy Rain Watch',
      description: `Elevated precipitation risk (${Math.max(maxHourlyPrecip, todayPrecip)}%) in active forecast window.`,
      source: 'Open-Meteo API',
    });
  }

  if (params.weatherCode === 73 || params.weatherCode === 75 || params.weatherCode === 86) {
    alerts.push({
      id: 'meteo-snow',
      severity: 'watch',
      title: 'Winter Snow Advisory',
      description: `Moderate-to-heavy snowfall reported (${params.temperatureC}°C).`,
      source: 'Open-Meteo API',
    });
  }

  if (params.weatherCode === 45 || params.weatherCode === 48) {
    alerts.push({
      id: 'meteo-fog',
      severity: 'advisory',
      title: 'Dense Fog Advisory',
      description: 'Reduced surface visibility detected across atmospheric layer.',
      source: 'Open-Meteo API',
    });
  }

  if (params.apparentTempC >= 39) {
    alerts.push({
      id: 'meteo-heat',
      severity: 'warning',
      title: 'Extreme Heat Warning',
      description: `Heat index reaching ${params.apparentTempC}°C. Limit prolonged exposure.`,
      source: 'Open-Meteo API',
    });
  } else if (params.temperatureC <= 0) {
    alerts.push({
      id: 'meteo-freeze',
      severity: 'advisory',
      title: 'Freeze Warning',
      description: `Sub-zero surface temperature (${params.temperatureC}°C). Watch for black ice.`,
      source: 'Open-Meteo API',
    });
  }

  if (params.pressureHpa > 0 && params.pressureHpa <= 996) {
    alerts.push({
      id: 'meteo-pressure',
      severity: 'advisory',
      title: 'Low Pressure Front',
      description: `Barometer dropped to ${params.pressureHpa} hPa indicating unstable weather.`,
      source: 'Open-Meteo API',
    });
  }

  return alerts;
}

export function formatReverseGeocodeLabel(
  payload: unknown,
  lat: number,
  lon: number
): { label: string; countryCode: string } {
  const coordFallback = `Live ${lat.toFixed(2)}°, ${lon.toFixed(2)}°`;
  if (!payload || typeof payload !== 'object') {
    return { label: coordFallback, countryCode: '' };
  }
  const obj = payload as Record<string, unknown>;
  const countryCode =
    typeof obj.countryCode === 'string'
      ? obj.countryCode.toUpperCase()
      : typeof (obj.address as Record<string, unknown> | undefined)?.country_code === 'string'
      ? String((obj.address as Record<string, unknown>).country_code).toUpperCase()
      : '';

  const cityCandidate =
    (typeof obj.city === 'string' && obj.city.trim()) ||
    (typeof obj.locality === 'string' && obj.locality.trim()) ||
    (typeof obj.principalSubdivision === 'string' && obj.principalSubdivision.trim()) ||
    '';

  if (cityCandidate) {
    return {
      label: countryCode ? `${cityCandidate}, ${countryCode}` : cityCandidate,
      countryCode,
    };
  }
  return { label: coordFallback, countryCode };
}

export function parseIpLocationResponse(payload: unknown): ResolvedLiveLocation | null {
  if (!payload || typeof payload !== 'object') return null;
  const obj = payload as Record<string, unknown>;
  if (obj.success === false) return null;

  const lat = typeof obj.latitude === 'number' ? obj.latitude : Number(obj.lat);
  const lon = typeof obj.longitude === 'number' ? obj.longitude : Number(obj.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

  const city = typeof obj.city === 'string' ? obj.city.trim() : '';
  const countryCode =
    typeof obj.country_code === 'string'
      ? obj.country_code.toUpperCase()
      : typeof obj.countryCode === 'string'
      ? obj.countryCode.toUpperCase()
      : '';

  const label = city
    ? countryCode
      ? `${city}, ${countryCode}`
      : city
    : `Live ${lat.toFixed(2)}°, ${lon.toFixed(2)}°`;

  return {
    lat,
    lon,
    label,
    countryCode,
    method: 'ip',
  };
}

export function parseOpenMeteoForecast(
  payload: unknown,
  locationLabel: string,
  now: Date = new Date(),
  externalAlerts: readonly WeatherAlert[] = []
): WeatherSnapshot | null {
  if (!payload || typeof payload !== 'object') return null;
  const record = payload as {
    timezone?: unknown;
    current?: Record<string, unknown>;
    hourly?: {
      time?: unknown;
      temperature_2m?: unknown;
      precipitation_probability?: unknown;
    };
    daily?: {
      time?: unknown;
      weather_code?: unknown;
      temperature_2m_max?: unknown;
      temperature_2m_min?: unknown;
      precipitation_probability_max?: unknown;
    };
    alerts?: unknown;
  };

  const current = record.current;
  if (!current || typeof current.temperature_2m !== 'number') return null;

  const currentTemp = Math.round(current.temperature_2m);
  const apparentTemp =
    typeof current.apparent_temperature === 'number'
      ? Math.round(current.apparent_temperature)
      : currentTemp;
  const weatherCode =
    typeof current.weather_code === 'number' ? Math.round(current.weather_code) : 1;
  const desc = describeWmoWeatherCode(weatherCode);
  const windKmh =
    typeof current.wind_speed_10m === 'number' ? Math.round(current.wind_speed_10m) : 10;
  const windGustsKmh =
    typeof current.wind_gusts_10m === 'number'
      ? Math.round(current.wind_gusts_10m)
      : windKmh;
  const windDir =
    typeof current.wind_direction_10m === 'number'
      ? Math.round(current.wind_direction_10m)
      : 180;
  const pressureHpa =
    typeof current.surface_pressure === 'number'
      ? Math.round(current.surface_pressure)
      : 1013;

  const hourlyTimes = Array.isArray(record.hourly?.time) ? record.hourly.time : [];
  const hourlyTemps = Array.isArray(record.hourly?.temperature_2m)
    ? record.hourly.temperature_2m
    : [];
  const hourlyPrecip = Array.isArray(record.hourly?.precipitation_probability)
    ? record.hourly.precipitation_probability
    : [];

  const currentHour = now.getHours();
  let startIndex = hourlyTimes.findIndex((t) => {
    if (typeof t !== 'string') return false;
    const match = t.match(/T(\d{2}):/);
    return match ? Number(match[1]) >= currentHour : false;
  });
  if (startIndex < 0) startIndex = 0;

  const hourly: HourlyWeatherPoint[] = [];
  for (let i = startIndex; i < Math.min(hourlyTimes.length, startIndex + 6); i += 1) {
    const rawTime = String(hourlyTimes[i] ?? '');
    const hourPart =
      rawTime.match(/T(\d{2}:\d{2})/)?.[1] ??
      `${String((currentHour + i) % 24).padStart(2, '0')}:00`;
    const tempVal =
      typeof hourlyTemps[i] === 'number'
        ? Math.round(hourlyTemps[i] as number)
        : currentTemp;
    const precipVal =
      typeof hourlyPrecip[i] === 'number' ? Math.round(hourlyPrecip[i] as number) : 0;
    hourly.push({
      hourLabel: hourPart,
      tempC: tempVal,
      precipProb: Math.max(0, Math.min(100, precipVal)),
    });
  }

  const dailyTimes = Array.isArray(record.daily?.time) ? record.daily.time : [];
  const dailyCodes = Array.isArray(record.daily?.weather_code) ? record.daily.weather_code : [];
  const dailyMaxs = Array.isArray(record.daily?.temperature_2m_max)
    ? record.daily.temperature_2m_max
    : [];
  const dailyMins = Array.isArray(record.daily?.temperature_2m_min)
    ? record.daily.temperature_2m_min
    : [];
  const dailyPrecip = Array.isArray(record.daily?.precipitation_probability_max)
    ? record.daily.precipitation_probability_max
    : [];

  const rawDaily: RawDailyWeatherInput[] = [];
  for (let i = 0; i < 5; i += 1) {
    const fallbackDate = formatIsoDate(new Date(now.getTime() + i * 86_400_000));
    const dateIso =
      typeof dailyTimes[i] === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(dailyTimes[i] as string)
        ? (dailyTimes[i] as string)
        : fallbackDate;
    const codeVal =
      typeof dailyCodes[i] === 'number' ? Math.round(dailyCodes[i] as number) : weatherCode;
    const maxVal =
      typeof dailyMaxs[i] === 'number'
        ? (dailyMaxs[i] as number)
        : currentTemp + 2 + Math.round(Math.sin(i * 1.1) * 2);
    const minVal =
      typeof dailyMins[i] === 'number'
        ? (dailyMins[i] as number)
        : currentTemp - 4 + Math.round(Math.cos(i * 0.9));
    const precipVal =
      typeof dailyPrecip[i] === 'number' ? (dailyPrecip[i] as number) : codeVal >= 50 ? 45 : 10;

    rawDaily.push({
      dateIso,
      weatherCode: codeVal,
      tempMinC: minVal,
      tempMaxC: maxVal,
      precipProbPct: precipVal,
    });
  }

  const daily = finalizeFiveDayForecast(rawDaily, currentTemp, now);

  const inlineApiAlerts: WeatherAlert[] = [];
  if (Array.isArray(record.alerts)) {
    for (const rawAlert of record.alerts) {
      if (!rawAlert || typeof rawAlert !== 'object') continue;
      const a = rawAlert as Record<string, unknown>;
      const title = typeof a.event === 'string' ? a.event.trim() : '';
      if (!title) continue;
      inlineApiAlerts.push({
        id: `api-alert-${inlineApiAlerts.length}`,
        severity: 'warning',
        title,
        description:
          typeof a.description === 'string'
            ? a.description.slice(0, 120).trim()
            : 'Active meteorological alert reported by feed.',
        source: 'Weather Alert API',
      });
    }
  }

  const metricAlerts = deriveWeatherAlertsFromMetrics({
    weatherCode,
    temperatureC: currentTemp,
    apparentTempC: apparentTemp,
    windKmh,
    windGustsKmh,
    pressureHpa,
    hourly,
    daily,
  });

  const mergedAlerts = [...externalAlerts, ...inlineApiAlerts, ...metricAlerts];
  const dedupedAlerts = mergedAlerts.filter(
    (alert, idx, arr) =>
      arr.findIndex((other) => other.title.toLowerCase() === alert.title.toLowerCase()) === idx
  );

  return {
    locationLabel,
    temperatureC: currentTemp,
    apparentTempC: apparentTemp,
    humidityPct:
      typeof current.relative_humidity_2m === 'number'
        ? Math.round(current.relative_humidity_2m)
        : 58,
    windKmh,
    windGustsKmh,
    windDirectionDeg: windDir,
    windCompass: degreesToCompass(windDir),
    pressureHpa,
    cloudCoverPct:
      typeof current.cloud_cover === 'number' ? Math.round(current.cloud_cover) : 24,
    weatherCode,
    conditionLabel: desc.label,
    conditionKind: desc.kind,
    isDay: current.is_day !== 0,
    hourly,
    daily,
    alerts: dedupedAlerts,
    source: 'live',
    updatedAt: formatClockTime(now),
  };
}

export function buildFallbackWeather(
  city: WeatherPresetCity,
  now: Date = new Date()
): WeatherSnapshot {
  const hour = now.getHours();
  const baseByCity: Record<
    string,
    {
      temp: number;
      humidity: number;
      wind: number;
      dir: number;
      code: number;
      weekOffsets: number[];
      weekCodes: number[];
    }
  > = {
    kolkata: {
      temp: 26,
      humidity: 64,
      wind: 11,
      dir: 145,
      code: 1,
      weekOffsets: [2, 3, 1, 0, 2],
      weekCodes: [1, 0, 2, 61, 1],
    },
    bengaluru: {
      temp: 23,
      humidity: 60,
      wind: 14,
      dir: 230,
      code: 2,
      weekOffsets: [2, 1, -1, 0, 2],
      weekCodes: [2, 80, 61, 2, 0],
    },
    'san-francisco': {
      temp: 16,
      humidity: 72,
      wind: 19,
      dir: 290,
      code: 45,
      weekOffsets: [1, 2, 0, -1, 1],
      weekCodes: [45, 2, 3, 61, 1],
    },
    tokyo: {
      temp: 18,
      humidity: 52,
      wind: 13,
      dir: 60,
      code: 0,
      weekOffsets: [2, 3, 2, 0, -2],
      weekCodes: [0, 0, 2, 3, 61],
    },
    london: {
      temp: 12,
      humidity: 76,
      wind: 18,
      dir: 240,
      code: 3,
      weekOffsets: [1, 0, -1, 1, 2],
      weekCodes: [3, 61, 80, 2, 1],
    },
  };
  const cfg = baseByCity[city.id] ?? {
    temp: 22,
    humidity: 58,
    wind: 12,
    dir: 180,
    code: 1,
    weekOffsets: [2, 3, 1, 0, 2],
    weekCodes: [1, 0, 2, 3, 1],
  };
  const desc = describeWmoWeatherCode(cfg.code);

  const hourly: HourlyWeatherPoint[] = Array.from({ length: 6 }, (_, idx) => {
    const h = (hour + idx) % 24;
    const offset = Math.round(Math.sin((idx / 5) * Math.PI) * 2 - (idx > 3 ? 1 : 0));
    return {
      hourLabel: `${String(h).padStart(2, '0')}:00`,
      tempC: cfg.temp + offset,
      precipProb: cfg.code >= 50 ? 40 : 10 + (idx % 2) * 5,
    };
  });

  const rawDaily: RawDailyWeatherInput[] = Array.from({ length: 5 }, (_, idx) => {
    const dateIso = formatIsoDate(new Date(now.getTime() + idx * 86_400_000));
    const maxT = cfg.temp + (cfg.weekOffsets[idx] ?? 0);
    const minT = maxT - (5 + (idx % 2));
    const code = cfg.weekCodes[idx] ?? cfg.code;
    return {
      dateIso,
      weatherCode: code,
      tempMinC: minT,
      tempMaxC: maxT,
      precipProbPct: code >= 51 ? 65 : code === 45 || code === 3 ? 25 : 8,
    };
  });

  const daily = finalizeFiveDayForecast(rawDaily, cfg.temp, now);
  const alerts = deriveWeatherAlertsFromMetrics({
    weatherCode: cfg.code,
    temperatureC: cfg.temp,
    apparentTempC: cfg.temp + 1,
    windKmh: cfg.wind,
    windGustsKmh: cfg.wind + 5,
    pressureHpa: 1014,
    hourly,
    daily,
  });

  return {
    locationLabel: `${city.name}, ${city.region}`,
    temperatureC: cfg.temp,
    apparentTempC: cfg.temp + 1,
    humidityPct: cfg.humidity,
    windKmh: cfg.wind,
    windGustsKmh: cfg.wind + 5,
    windDirectionDeg: cfg.dir,
    windCompass: degreesToCompass(cfg.dir),
    pressureHpa: 1014,
    cloudCoverPct: cfg.code === 0 ? 8 : cfg.code === 3 ? 82 : 28,
    weatherCode: cfg.code,
    conditionLabel: desc.label,
    conditionKind: desc.kind,
    isDay: hour >= 6 && hour < 18,
    hourly,
    daily,
    alerts,
    source: 'cached',
    updatedAt: formatClockTime(now),
  };
}

export function computeSignalBands(
  audioLevel: number,
  isListening: boolean,
  assistantState: AssistantState,
  phase: number,
  bandCount = 12
): number[] {
  const safeCount = Math.max(4, bandCount);
  const clampedAudio = Math.max(0, Math.min(1, Number.isFinite(audioLevel) ? audioLevel : 0));
  const stateGain =
    assistantState === 'stopped'
      ? 0.08
      : assistantState === 'thinking'
      ? 0.58
      : assistantState === 'speaking'
      ? 0.66
      : isListening
      ? Math.max(0.32, clampedAudio * 1.15)
      : 0.24;

  return Array.from({ length: safeCount }, (_, idx) => {
    if (assistantState === 'stopped') return 0.1;
    const normIdx = idx / (safeCount - 1);
    const waveA = 0.5 + 0.5 * Math.sin(phase * 1.4 + idx * 0.68);
    const waveB = 0.5 + 0.5 * Math.cos(phase * 0.9 - normIdx * 4.2);
    const energy = 0.14 + stateGain * (0.45 * waveA + 0.45 * waveB + clampedAudio * 0.35);
    return Number(Math.max(0.1, Math.min(1, energy)).toFixed(3));
  });
}
