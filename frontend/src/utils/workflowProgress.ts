import type { WorkflowItem, WorkflowStatus } from '../types/shu';

export type WorkflowExecutionPhase = 'idle' | 'running' | 'completed' | 'halted';

export interface ActiveWorkflowExecution {
  workflowId: string;
  workflowName: string;
  totalSteps: number;
  completedSteps: number;
  currentStepIndex: number;
  currentStepLabel: string;
  progressPct: number;
  phase: WorkflowExecutionPhase;
  startedAt: string;
  updatedAt: string;
}

export type CircularTone = 'sky' | 'teal' | 'amber' | 'rose';

export interface CircularProgressViewModel {
  progressPct: number;
  clampedPct: number;
  circumference: number;
  dashOffset: number;
  tone: CircularTone;
  statusLabel: string;
  title: string;
  subtitle: string;
  stepCounterLabel: string;
  isAnimating: boolean;
}

export function clampPercentage(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function computeCircularStrokeGeometry(
  radius: number,
  progressPct: number
): {
  circumference: number;
  dashOffset: number;
  clampedPct: number;
} {
  const safeRadius = Math.max(1, radius);
  const circumference = Number((2 * Math.PI * safeRadius).toFixed(3));
  const clampedPct = clampPercentage(progressPct);
  const dashOffset = Number((circumference * (1 - clampedPct / 100)).toFixed(3));
  return { circumference, dashOffset, clampedPct };
}

function statusToRowDefaults(status: WorkflowStatus): {
  progressPct: number;
  tone: CircularTone;
  phaseLabel: string;
  isRunning: boolean;
} {
  if (status === 'Approved') {
    return { progressPct: 100, tone: 'teal', phaseLabel: 'Ready', isRunning: false };
  }
  if (status === 'Pending approval') {
    return { progressPct: 50, tone: 'amber', phaseLabel: 'Pending', isRunning: false };
  }
  return { progressPct: 0, tone: 'rose', phaseLabel: 'Revoked', isRunning: false };
}

export function computeWorkflowRowProgressPct(
  workflow: WorkflowItem,
  activeExecution: ActiveWorkflowExecution | null
): {
  progressPct: number;
  tone: CircularTone;
  phaseLabel: string;
  isRunning: boolean;
} {
  if (activeExecution && activeExecution.workflowId === workflow.id) {
    if (activeExecution.phase === 'running') {
      return {
        progressPct: clampPercentage(activeExecution.progressPct),
        tone: 'sky',
        phaseLabel: 'Running',
        isRunning: true,
      };
    }
    if (activeExecution.phase === 'halted') {
      return {
        progressPct: clampPercentage(activeExecution.progressPct),
        tone: 'rose',
        phaseLabel: 'Halted',
        isRunning: false,
      };
    }
    if (activeExecution.phase === 'completed') {
      return {
        progressPct: 100,
        tone: 'teal',
        phaseLabel: 'Completed',
        isRunning: false,
      };
    }
  }

  return statusToRowDefaults(workflow.status);
}

export function computeWorkflowCircularProgress(options: {
  selectedWorkflow: WorkflowItem | null;
  activeExecution: ActiveWorkflowExecution | null;
  workflows: WorkflowItem[];
  radius?: number;
}): CircularProgressViewModel {
  const { selectedWorkflow, activeExecution, workflows, radius = 48 } = options;

  if (
    activeExecution &&
    (activeExecution.phase === 'running' ||
      !selectedWorkflow ||
      selectedWorkflow.id === activeExecution.workflowId)
  ) {
    const geom = computeCircularStrokeGeometry(radius, activeExecution.progressPct);
    const tone: CircularTone =
      activeExecution.phase === 'running'
        ? 'sky'
        : activeExecution.phase === 'completed'
        ? 'teal'
        : activeExecution.phase === 'halted'
        ? 'rose'
        : 'sky';
    const statusLabel =
      activeExecution.phase === 'running'
        ? 'Executing'
        : activeExecution.phase === 'completed'
        ? 'Completed'
        : activeExecution.phase === 'halted'
        ? 'Halted'
        : 'Standby';
    const stepDisplay =
      activeExecution.phase === 'running'
        ? Math.min(activeExecution.totalSteps, activeExecution.currentStepIndex + 1)
        : activeExecution.completedSteps;

    return {
      progressPct: geom.clampedPct,
      clampedPct: geom.clampedPct,
      circumference: geom.circumference,
      dashOffset: geom.dashOffset,
      tone,
      statusLabel,
      title: activeExecution.workflowName,
      subtitle: activeExecution.currentStepLabel,
      stepCounterLabel: `${stepDisplay}/${Math.max(1, activeExecution.totalSteps)} steps`,
      isAnimating: activeExecution.phase === 'running',
    };
  }

  if (selectedWorkflow) {
    const rowState = statusToRowDefaults(selectedWorkflow.status);
    const geom = computeCircularStrokeGeometry(radius, rowState.progressPct);
    const subtitle =
      selectedWorkflow.status === 'Approved'
        ? `Ready to replay (${selectedWorkflow.steps.length} steps)`
        : selectedWorkflow.status === 'Pending approval'
        ? 'Awaiting operator approval before execution'
        : 'Revoked by tool allowlist policy';

    return {
      progressPct: geom.clampedPct,
      clampedPct: geom.clampedPct,
      circumference: geom.circumference,
      dashOffset: geom.dashOffset,
      tone: rowState.tone,
      statusLabel: rowState.phaseLabel,
      title: selectedWorkflow.name,
      subtitle,
      stepCounterLabel: `${selectedWorkflow.steps.length} step(s)`,
      isAnimating: false,
    };
  }

  const totalCount = workflows.length;
  const approvedCount = workflows.filter((w) => w.status === 'Approved').length;
  const readinessPct = totalCount > 0 ? Math.round((approvedCount / totalCount) * 100) : 0;
  const geom = computeCircularStrokeGeometry(radius, readinessPct);

  return {
    progressPct: geom.clampedPct,
    clampedPct: geom.clampedPct,
    circumference: geom.circumference,
    dashOffset: geom.dashOffset,
    tone: readinessPct > 0 ? 'teal' : 'amber',
    statusLabel: 'Queue Readiness',
    title: 'Active Task Monitor',
    subtitle: 'Select a workflow and press Replay for live step execution',
    stepCounterLabel: `${approvedCount}/${totalCount} approved`,
    isAnimating: false,
  };
}
