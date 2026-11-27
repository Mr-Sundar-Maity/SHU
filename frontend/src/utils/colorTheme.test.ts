import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_COLOR_THEME,
  HOLO_COLOR_THEMES,
  getHoloColorTheme,
  isValidHoloColorTheme,
} from './colorTheme';

test('HOLO_COLOR_THEMES exposes all 4 requested primary colors and palette gradients', () => {
  const ids = HOLO_COLOR_THEMES.map((t) => t.id);
  assert.deepEqual(ids, ['frost-blue', 'rose-crimson', 'abyssal-blue', 'luna-aqua']);

  const primaries = HOLO_COLOR_THEMES.map((t) => t.primaryCss);
  assert.deepEqual(primaries, ['#B9D7EA', '#EE6983', '#205295', '#61C0BF']);

  for (const theme of HOLO_COLOR_THEMES) {
    assert.ok(theme.gradientCss.startsWith('linear-gradient('));
  }
});

test('getHoloColorTheme resolves valid theme ids and falls back cleanly to default frost-blue', () => {
  assert.equal(getHoloColorTheme('frost-blue').primaryCss, '#B9D7EA');
  assert.equal(getHoloColorTheme('rose-crimson').primaryCss, '#EE6983');
  assert.equal(getHoloColorTheme('abyssal-blue').primaryCss, '#205295');
  assert.equal(getHoloColorTheme('luna-aqua').primaryCss, '#61C0BF');
  assert.equal(getHoloColorTheme('unknown-theme').id, DEFAULT_COLOR_THEME);
  assert.equal(getHoloColorTheme(undefined).id, DEFAULT_COLOR_THEME);
  assert.equal(isValidHoloColorTheme('rose-crimson'), true);
  assert.equal(isValidHoloColorTheme('cyber-gold'), false);
});
