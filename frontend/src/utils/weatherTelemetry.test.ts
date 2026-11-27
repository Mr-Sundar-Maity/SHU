import test from 'node:test';
import assert from 'node:assert/strict';
import {
  WEATHER_PRESET_CITIES,
  buildFallbackWeather,
  computeSignalBands,
  degreesToCompass,
  describeWmoWeatherCode,
  deriveWeatherAlertsFromMetrics,
  finalizeFiveDayForecast,
  formatReverseGeocodeLabel,
  parseIpLocationResponse,
  parseNwsWeatherAlerts,
  parseOpenMeteoForecast,
} from './weatherTelemetry';

test('degreesToCompass maps meteorological azimuth degrees cleanly', () => {
  assert.equal(degreesToCompass(0), 'N');
  assert.equal(degreesToCompass(45), 'NE');
  assert.equal(degreesToCompass(90), 'E');
  assert.equal(degreesToCompass(180), 'S');
  assert.equal(degreesToCompass(315), 'NW');
});

test('describeWmoWeatherCode distinguishes clear, fog, rain, and storm codes', () => {
  assert.equal(describeWmoWeatherCode(0).kind, 'clear');
  assert.equal(describeWmoWeatherCode(45).kind, 'fog');
  assert.equal(describeWmoWeatherCode(63).kind, 'rain');
  assert.equal(describeWmoWeatherCode(95).kind, 'storm');
});

test('parseOpenMeteoForecast extracts current readings, 6-hour wave, 5-day outlook, and quiet alerts', () => {
  const samplePayload = {
    current: {
      temperature_2m: 27.4,
      apparent_temperature: 29.1,
      relative_humidity_2m: 62,
      is_day: 1,
      weather_code: 2,
      cloud_cover: 35,
      surface_pressure: 1011.6,
      wind_speed_10m: 14.3,
      wind_gusts_10m: 21.0,
      wind_direction_10m: 135,
    },
    hourly: {
      time: [
        '2026-11-25T08:00',
        '2026-11-25T09:00',
        '2026-11-25T10:00',
        '2026-11-25T11:00',
        '2026-11-25T12:00',
        '2026-11-25T13:00',
        '2026-11-25T14:00',
      ],
      temperature_2m: [25, 27, 29, 30, 31, 30, 29],
      precipitation_probability: [5, 10, 15, 20, 15, 10, 5],
    },
    daily: {
      time: [
        '2026-11-25',
        '2026-11-26',
        '2026-11-27',
        '2026-11-28',
        '2026-11-29',
      ],
      weather_code: [1, 0, 61, 2, 95],
      temperature_2m_max: [29, 31, 27, 27, 30],
      temperature_2m_min: [21, 22, 20, 19, 21],
      precipitation_probability_max: [10, 5, 70, 20, 85],
    },
  };

  const parsed = parseOpenMeteoForecast(
    samplePayload,
    'Kolkata, IN',
    new Date('2026-11-25T09:15:00')
  );
  assert.ok(parsed);
  assert.equal(parsed.temperatureC, 27);
  assert.equal(parsed.apparentTempC, 29);
  assert.equal(parsed.windCompass, 'SE');
  assert.equal(parsed.pressureHpa, 1012);
  assert.equal(parsed.source, 'live');
  assert.equal(parsed.hourly.length, 6);
  assert.equal(parsed.hourly[0].hourLabel, '09:00');
  assert.equal(parsed.daily.length, 5);
  assert.equal(parsed.daily[0].dayLabel, 'Today');
  assert.equal(parsed.daily[1].trendDirection, 'up');
  assert.equal(parsed.daily[1].trendDeltaC, 2);
  assert.equal(parsed.daily[2].trendDirection, 'down');
  assert.equal(parsed.daily[2].trendDeltaC, -4);
  assert.equal(parsed.daily[3].trendDirection, 'steady');
  assert.equal(parsed.alerts.length, 0);
});

test('deriveWeatherAlertsFromMetrics triggers severe thunderstorm and wind warnings only when thresholds trip', () => {
  const alerts = deriveWeatherAlertsFromMetrics({
    weatherCode: 95,
    temperatureC: 24,
    apparentTempC: 26,
    windKmh: 48,
    windGustsKmh: 76,
    pressureHpa: 993,
    hourly: [{ hourLabel: '10:00', tempC: 24, precipProb: 85 }],
    daily: [
      {
        dateIso: '2026-11-25',
        dayLabel: 'Today',
        weatherCode: 95,
        conditionLabel: 'Thunderstorm',
        conditionKind: 'storm',
        tempMinC: 20,
        tempMaxC: 26,
        precipProbPct: 90,
        trendDeltaC: 0,
        trendDirection: 'steady',
        rangeStartPct: 0,
        rangeWidthPct: 100,
      },
    ],
  });
  assert.ok(alerts.some((a) => a.severity === 'warning' && a.title.includes('Thunderstorm')));
  assert.ok(alerts.some((a) => a.severity === 'warning' && a.title.includes('Wind')));
  assert.ok(alerts.some((a) => a.title.includes('Heavy Rain')));
  assert.ok(alerts.some((a) => a.title.includes('Low Pressure')));
});

test('parseNwsWeatherAlerts parses active NWS GeoJSON alert properties safely', () => {
  const alerts = parseNwsWeatherAlerts({
    features: [
      {
        properties: {
          id: 'urn-123',
          event: 'Severe Thunderstorm Warning',
          severity: 'Severe',
          headline: 'Severe Thunderstorm Warning issued until 18:30',
          ends: '2026-11-25T18:30:00-08:00',
        },
      },
    ],
  });
  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].severity, 'warning');
  assert.equal(alerts[0].title, 'Severe Thunderstorm Warning');
  assert.equal(alerts[0].expiresLabel, 'Until 18:30');
});

test('formatReverseGeocodeLabel and parseIpLocationResponse format live user location cleanly', () => {
  const rev = formatReverseGeocodeLabel(
    { city: 'Hyderabad', countryCode: 'IN' },
    17.385,
    78.4867
  );
  assert.equal(rev.label, 'Hyderabad, IN');
  assert.equal(rev.countryCode, 'IN');

  const ipLoc = parseIpLocationResponse({
    city: 'Mumbai',
    country_code: 'IN',
    latitude: 19.076,
    longitude: 72.8777,
  });
  assert.ok(ipLoc);
  assert.equal(ipLoc.label, 'Mumbai, IN');
  assert.equal(ipLoc.method, 'ip');
});

test('finalizeFiveDayForecast bounds bar percentages cleanly inside [0, 100]', () => {
  const days = finalizeFiveDayForecast(
    [
      { dateIso: '2026-11-25', weatherCode: 0, tempMinC: 18, tempMaxC: 25, precipProbPct: 5 },
      { dateIso: '2026-11-26', weatherCode: 2, tempMinC: 20, tempMaxC: 28, precipProbPct: 15 },
      { dateIso: '2026-11-27', weatherCode: 61, tempMinC: 16, tempMaxC: 22, precipProbPct: 65 },
      { dateIso: '2026-11-28', weatherCode: 3, tempMinC: 15, tempMaxC: 22, precipProbPct: 30 },
      { dateIso: '2026-11-29', weatherCode: 0, tempMinC: 17, tempMaxC: 26, precipProbPct: 10 },
    ],
    23,
    new Date('2026-11-25T10:00:00')
  );
  assert.equal(days.length, 5);
  for (const d of days) {
    assert.ok(d.rangeStartPct >= 0 && d.rangeStartPct <= 86);
    assert.ok(d.rangeWidthPct >= 14 && d.rangeStartPct + d.rangeWidthPct <= 100.1);
  }
});

test('buildFallbackWeather returns deterministic cached snapshot with 5 daily entries', () => {
  const snap = buildFallbackWeather(WEATHER_PRESET_CITIES[0], new Date('2026-11-25T14:00:00'));
  assert.equal(snap.source, 'cached');
  assert.equal(snap.hourly.length, 6);
  assert.equal(snap.daily.length, 5);
  assert.equal(snap.daily[0].dayLabel, 'Today');
  assert.ok(snap.locationLabel.includes('Kolkata'));
});

test('computeSignalBands scales cleanly across listening and stopped states', () => {
  const listening = computeSignalBands(0.8, true, 'listening', 1.2, 12);
  const stopped = computeSignalBands(0.8, false, 'stopped', 1.2, 12);
  assert.equal(listening.length, 12);
  assert.ok(listening.every((v) => v >= 0.1 && v <= 1));
  assert.ok(stopped.every((v) => v === 0.1));
});
