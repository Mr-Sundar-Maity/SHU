import test from 'node:test';
import assert from 'node:assert/strict';
import type { WorkflowItem } from '../types/shu';
import {
  clampPercentage,
  computeCircularStrokeGeometry,
  computeWorkflowCircularProgress,
  computeWorkflowRowProgressPct,
  type ActiveWorkflowExecution,
} from './workflowProgress';

const SAMPLE_WORKFLOWS: WorkflowItem[] = [
  {
    id: 'wf-301',
    name: 'Morning Daily Briefing',
    status: 'Approved',
    tools: ['memory.read', 'voice.speak'],
    steps: ['Load memories', 'Collect reminders', 'Read summary'],
    lastPreview: '',
  },
  {
    id: 'wf-302',
    name: 'Draft Weekly Follow-Up',
    status: 'Pending approval',
    tools: ['memory.read'],
    steps: ['Gather notes', 'Prepare draft'],
    lastPreview: '',
  },
  {
    id: 'wf-303',
    name: 'Legacy Shell Diagnostics',
    status: 'Revoked',
    tools: ['shell.exec'],
    steps: ['Run inspection'],
    lastPreview: '',
  },
];

test('clampPercentage clamps out-of-range and non-finite inputs', () => {
  assert.equal(clampPercentage(-12), 0);
  assert.equal(clampPercentage(142), 100);
  assert.equal(clampPercentage(66.6), 67);
  assert.equal(clampPercentage(Number.NaN), 0);
});

test('computeCircularStrokeGeometry calculates SVG circumference and dashOffset accurately', () => {
  const zero = computeCircularStrokeGeometry(40, 0);
  assert.equal(zero.dashOffset, zero.circumference);

  const half = computeCircularStrokeGeometry(40, 50);
  assert.ok(Math.abs(half.dashOffset - half.circumference * 0.5) < 0.01);

  const full = computeCircularStrokeGeometry(40, 100);
  assert.equal(full.dashOffset, 0);
});

test('computeWorkflowRowProgressPct reflects live active execution over static workflow status', () => {
  const runningExec: ActiveWorkflowExecution = {
    workflowId: 'wf-301',
    workflowName: 'Morning Daily Briefing',
    totalSteps: 3,
    completedSteps: 1,
    currentStepIndex: 1,
    currentStepLabel: 'Collect reminders',
    progressPct: 33,
    phase: 'running',
    startedAt: '2026-11-25 09:20',
    updatedAt: '2026-11-25 09:20',
  };

  const activeRow = computeWorkflowRowProgressPct(SAMPLE_WORKFLOWS[0], runningExec);
  assert.equal(activeRow.progressPct, 33);
  assert.equal(activeRow.tone, 'sky');
  assert.equal(activeRow.isRunning, true);

  const pendingRow = computeWorkflowRowProgressPct(SAMPLE_WORKFLOWS[1], runningExec);
  assert.equal(pendingRow.progressPct, 50);
  assert.equal(pendingRow.tone, 'amber');
  assert.equal(pendingRow.isRunning, false);

  const revokedRow = computeWorkflowRowProgressPct(SAMPLE_WORKFLOWS[2], runningExec);
  assert.equal(revokedRow.progressPct, 0);
  assert.equal(revokedRow.tone, 'rose');
});

test('computeWorkflowCircularProgress prioritizes running execution and computes queue readiness fallback', () => {
  const idleMonitor = computeWorkflowCircularProgress({
    selectedWorkflow: null,
    activeExecution: null,
    workflows: SAMPLE_WORKFLOWS,
  });
  assert.equal(idleMonitor.progressPct, 33); // 1 of 3 approved
  assert.equal(idleMonitor.statusLabel, 'Queue Readiness');
  assert.equal(idleMonitor.isAnimating, false);

  const runningExec: ActiveWorkflowExecution = {
    workflowId: 'wf-301',
    workflowName: 'Morning Daily Briefing',
    totalSteps: 3,
    completedSteps: 2,
    currentStepIndex: 2,
    currentStepLabel: 'Read summary',
    progressPct: 67,
    phase: 'running',
    startedAt: '2026-11-25 09:20',
    updatedAt: '2026-11-25 09:20',
  };
  const activeMonitor = computeWorkflowCircularProgress({
    selectedWorkflow: SAMPLE_WORKFLOWS[1],
    activeExecution: runningExec,
    workflows: SAMPLE_WORKFLOWS,
  });
  assert.equal(activeMonitor.progressPct, 67);
  assert.equal(activeMonitor.statusLabel, 'Executing');
  assert.equal(activeMonitor.stepCounterLabel, '3/3 steps');
  assert.equal(activeMonitor.isAnimating, true);

  const completedMonitor = computeWorkflowCircularProgress({
    selectedWorkflow: SAMPLE_WORKFLOWS[0],
    activeExecution: { ...runningExec, phase: 'completed', completedSteps: 3, progressPct: 100 },
    workflows: SAMPLE_WORKFLOWS,
  });
  assert.equal(completedMonitor.progressPct, 100);
  assert.equal(completedMonitor.tone, 'teal');
  assert.equal(completedMonitor.dashOffset, 0);
});
