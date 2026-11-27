export type HoloColorThemeId =
  | 'frost-blue'
  | 'rose-crimson'
  | 'abyssal-blue'
  | 'luna-aqua';

export interface HoloColorThemeDefinition {
  id: HoloColorThemeId;
  name: string;
  tagline: string;
  primaryHex: number;
  secondaryHex: number;
  accentHex: number;
  primaryCss: string;
  secondaryCss: string;
  accentCss: string;
  primaryRgb: string;
  secondaryRgb: string;
  accentRgb: string;
  softRgb: string;
  gradientCss: string;
  swatches: [string, string, string];
  shaderMixRgb: [number, number, number];
  shaderAccentRgb: [number, number, number];
}

export const DEFAULT_COLOR_THEME: HoloColorThemeId = 'frost-blue';

export const HOLO_COLOR_THEMES: readonly HoloColorThemeDefinition[] = [
  {
    id: 'frost-blue',
    name: 'Frost Blue',
    tagline: 'Glacier blue gradient (#F7FBFC -> #B9D7EA -> #769FCD)',
    primaryHex: 0xb9d7ea,
    secondaryHex: 0x769fcd,
    accentHex: 0xd6e6f2,
    primaryCss: '#B9D7EA',
    secondaryCss: '#769FCD',
    accentCss: '#D6E6F2',
    primaryRgb: '185, 215, 234',
    secondaryRgb: '118, 159, 205',
    accentRgb: '214, 230, 242',
    softRgb: '247, 251, 252',
    gradientCss: 'linear-gradient(135deg, #F7FBFC 0%, #D6E6F2 35%, #B9D7EA 70%, #769FCD 100%)',
    swatches: ['#B9D7EA', '#D6E6F2', '#769FCD'],
    shaderMixRgb: [0.73, 0.84, 0.92],
    shaderAccentRgb: [0.84, 0.9, 0.95],
  },
  {
    id: 'rose-crimson',
    name: 'Rose Crimson',
    tagline: 'Warm blush-to-crimson gradient (#FFF5E4 -> #EE6983 -> #850E35)',
    primaryHex: 0xee6983,
    secondaryHex: 0x850e35,
    accentHex: 0xffc4c4,
    primaryCss: '#EE6983',
    secondaryCss: '#850E35',
    accentCss: '#FFC4C4',
    primaryRgb: '238, 105, 131',
    secondaryRgb: '133, 14, 53',
    accentRgb: '255, 196, 196',
    softRgb: '255, 245, 228',
    gradientCss: 'linear-gradient(135deg, #FFF5E4 0%, #FFC4C4 34%, #EE6983 68%, #850E35 100%)',
    swatches: ['#EE6983', '#FFC4C4', '#850E35'],
    shaderMixRgb: [0.93, 0.41, 0.51],
    shaderAccentRgb: [1.0, 0.77, 0.77],
  },
  {
    id: 'abyssal-blue',
    name: 'Abyssal Blue',
    tagline: 'Deep maritime gradient (#0A2647 -> #205295 -> #2C74B3)',
    primaryHex: 0x205295,
    secondaryHex: 0x144272,
    accentHex: 0x2c74b3,
    primaryCss: '#205295',
    secondaryCss: '#144272',
    accentCss: '#2C74B3',
    primaryRgb: '32, 82, 149',
    secondaryRgb: '20, 66, 114',
    accentRgb: '44, 116, 179',
    softRgb: '185, 215, 234',
    gradientCss: 'linear-gradient(135deg, #0A2647 0%, #144272 34%, #205295 68%, #2C74B3 100%)',
    swatches: ['#205295', '#2C74B3', '#144272'],
    shaderMixRgb: [0.13, 0.32, 0.58],
    shaderAccentRgb: [0.17, 0.45, 0.7],
  },
  {
    id: 'luna-aqua',
    name: 'Luna Aqua',
    tagline: 'Luna ocean gradient (#A7EBF2 -> #61C0BF -> #011C40)',
    primaryHex: 0x61c0bf,
    secondaryHex: 0x167d8d,
    accentHex: 0xa7ebf2,
    primaryCss: '#61C0BF',
    secondaryCss: '#167D8D',
    accentCss: '#A7EBF2',
    primaryRgb: '97, 192, 191',
    secondaryRgb: '22, 125, 141',
    accentRgb: '167, 235, 242',
    softRgb: '185, 228, 232',
    gradientCss: 'linear-gradient(135deg, #A7EBF2 0%, #61C0BF 35%, #26658C 70%, #011C40 100%)',
    swatches: ['#61C0BF', '#A7EBF2', '#167D8D'],
    shaderMixRgb: [0.38, 0.75, 0.75],
    shaderAccentRgb: [0.65, 0.92, 0.95],
  },
];

export function isValidHoloColorTheme(value: unknown): value is HoloColorThemeId {
  return (
    value === 'frost-blue' ||
    value === 'rose-crimson' ||
    value === 'abyssal-blue' ||
    value === 'luna-aqua'
  );
}

export function getHoloColorTheme(themeId?: string | null): HoloColorThemeDefinition {
  const found = HOLO_COLOR_THEMES.find((t) => t.id === themeId);
  return found ?? HOLO_COLOR_THEMES[0];
}
