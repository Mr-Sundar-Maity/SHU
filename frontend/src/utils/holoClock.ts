export interface HoloClockSnapshot {
  timeText: string;
  compactTimeText: string;
  hours: string;
  minutes: string;
  seconds: string;
  period: 'AM' | 'PM' | null;
  dateLabel: string;
  tzAbbr: string;
  utcOffset: string;
  ianaZone: string;
}

export interface HoloClockFormatOptions {
  use12Hour?: boolean;
  timeZone?: string;
}

export function formatUtcOffsetFromMinutes(offsetMinutes: number): string {
  // Date.getTimezoneOffset() returns (UTC - local) in minutes; invert sign for standard UTC+/- label
  const signedMinutes = -offsetMinutes;
  if (signedMinutes === 0) return 'UTC+0';
  const sign = signedMinutes > 0 ? '+' : '-';
  const abs = Math.abs(signedMinutes);
  const hrs = Math.floor(abs / 60);
  const mins = abs % 60;
  return mins === 0
    ? `UTC${sign}${hrs}`
    : `UTC${sign}${hrs}:${String(mins).padStart(2, '0')}`;
}

export function formatHoloClockSnapshot(
  date: Date,
  options: HoloClockFormatOptions = {}
): HoloClockSnapshot {
  const { use12Hour = false, timeZone } = options;

  const resolvedOpts = new Intl.DateTimeFormat().resolvedOptions();
  const ianaZone = timeZone || resolvedOpts.timeZone || 'UTC';

  const timeParts = new Intl.DateTimeFormat('en-US', {
    timeZone: ianaZone,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: use12Hour,
  }).formatToParts(date);

  const partValue = (type: Intl.DateTimeFormatPartTypes) =>
    timeParts.find((p) => p.type === type)?.value ?? '';

  const rawHours = partValue('hour') || String(date.getHours()).padStart(2, '0');
  const hours = rawHours === '24' ? '00' : rawHours.padStart(2, '0');
  const minutes = (partValue('minute') || String(date.getMinutes()).padStart(2, '0')).padStart(
    2,
    '0'
  );
  const seconds = (partValue('second') || String(date.getSeconds()).padStart(2, '0')).padStart(
    2,
    '0'
  );
  const dayPeriodRaw = partValue('dayPeriod').toUpperCase();
  const period: 'AM' | 'PM' | null =
    use12Hour && (dayPeriodRaw === 'AM' || dayPeriodRaw === 'PM')
      ? dayPeriodRaw
      : null;

  const timeText = period
    ? `${hours}:${minutes}:${seconds} ${period}`
    : `${hours}:${minutes}:${seconds}`;
  const compactTimeText = period ? `${hours}:${minutes} ${period}` : `${hours}:${minutes}`;

  const dateLabel = new Intl.DateTimeFormat('en-US', {
    timeZone: ianaZone,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  }).format(date);

  const tzParts = new Intl.DateTimeFormat('en-US', {
    timeZone: ianaZone,
    timeZoneName: 'short',
  }).formatToParts(date);
  const tzAbbr = tzParts.find((p) => p.type === 'timeZoneName')?.value || 'LOCAL';

  let utcOffset = formatUtcOffsetFromMinutes(date.getTimezoneOffset());
  if (timeZone) {
    try {
      const longOffsetParts = new Intl.DateTimeFormat('en-US', {
        timeZone,
        timeZoneName: 'shortOffset',
      }).formatToParts(date);
      const offsetToken = longOffsetParts.find((p) => p.type === 'timeZoneName')?.value;
      if (offsetToken) {
        utcOffset = offsetToken.replace('GMT', 'UTC');
        if (utcOffset === 'UTC') utcOffset = 'UTC+0';
      }
    } catch {
      // Fallback to local offset if shortOffset is unsupported
    }
  }

  return {
    timeText,
    compactTimeText,
    hours,
    minutes,
    seconds,
    period,
    dateLabel,
    tzAbbr,
    utcOffset,
    ianaZone,
  };
}
