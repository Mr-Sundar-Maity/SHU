import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_PRIVACY_STATE,
  buildPersonalDataExportPayload,
  buildPrivacyDataFlows,
  executeGdprPurgeState,
  getPrivacyPermissionItems,
  normalizePrivacyState,
  toggleGdprDeletionState,
  togglePrivacyPermissionInState,
} from './privacyDashboard';

test('privacy permissions toggle cleanly and reflect in real-time data flows', () => {
  const toggled = togglePrivacyPermissionInState(DEFAULT_PRIVACY_STATE, 'weatherGeo');
  assert.equal(toggled.permissions.weatherGeo, false);

  const items = getPrivacyPermissionItems(toggled);
  const weatherItem = items.find((item) => item.key === 'weatherGeo');
  assert.equal(weatherItem?.enabled, false);

  const flows = buildPrivacyDataFlows({
    state: toggled,
    isListening: true,
    bridgeConnected: false,
    memoryCount: 4,
    transcriptCount: 3,
    voiceLogCount: 2,
  });
  const weatherFlow = flows.find((f) => f.id === 'flow-weather');
  assert.equal(weatherFlow?.active, false);
  assert.equal(weatherFlow?.volumeLabel, 'Location masked');
});

test('GDPR deletion request toggle and purge execution manage ticket and timestamps', () => {
  const requested = toggleGdprDeletionState(DEFAULT_PRIVACY_STATE, '2026-11-26 10:15');
  assert.equal(requested.gdprDeletionRequested, true);
  assert.ok(requested.erasureTicketId?.startsWith('GDPR-ART17-'));
  assert.equal(requested.gdprDeletionRequestedAt, '2026-11-26 10:15');

  const purged = executeGdprPurgeState(requested, '2026-11-26 10:16');
  assert.equal(purged.lastPurgedAt, '2026-11-26 10:16');

  const cancelled = toggleGdprDeletionState(purged, '2026-11-26 10:17', false);
  assert.equal(cancelled.gdprDeletionRequested, false);
  assert.equal(cancelled.erasureTicketId, null);

  const normalized = normalizePrivacyState({ gdprDeletionRequested: true });
  assert.equal(normalized.gdprDeletionRequested, true);
  assert.equal(normalized.permissions.microphone, true);

  const exportJson = buildPersonalDataExportPayload({
    exportedAt: '2026-11-26 10:18',
    privacyState: purged,
    memoryCount: 0,
    reminderCount: 0,
    transcriptCount: 1,
  });
  assert.ok(exportJson.includes('shu.gdpr.article20.export.v1'));
});
