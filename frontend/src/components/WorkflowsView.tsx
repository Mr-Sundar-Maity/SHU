import React from "react";
import {
  Ban,
  Check,
  FileSearch,
  Pencil,
  Play,
  RefreshCw,
  X,
} from "lucide-react";
import { useShu } from "../context/ShuContext";

export const WorkflowsView: React.FC = () => {
  const {
    setActiveTab,
    workflows,
    selectedWorkflowId,
    setSelectedWorkflowId,
    workflowPreviewText,
    refreshWorkflows,
    reviewWorkflow,
    editWorkflow,
    approveWorkflow,
    revokeWorkflow,
    replayWorkflow,
    openRuntimeControls,
  } = useShu();
  const selected = workflows.find((w) => w.id === selectedWorkflowId);
  const button =
    "inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-200 hover:border-sky-400/50 disabled:opacity-40";

  return (
    <section
      aria-label="Workflows manager"
      className="relative z-10 mx-auto flex h-full w-full max-w-6xl flex-col px-4 py-6 overflow-hidden"
    >
      <div className="holo-surface flex min-h-0 flex-1 flex-col rounded-2xl p-6 overflow-y-auto shu-scroll">
        <div className="flex items-start justify-between border-b border-slate-800 pb-3">
          <div>
            <h1 className="font-display text-xl font-semibold text-slate-100">
              Workflows
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              Saved SHU procedures. Edits require approval before replay.
            </p>
          </div>
          <button
            className={button}
            aria-label="Close Workflows popup"
            onClick={() => setActiveTab("assistant")}
          >
            <X size={16} />
          </button>
        </div>
        <div className="mt-4 overflow-auto rounded-xl border border-slate-800 shu-scroll">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-900 text-slate-400">
              <tr>
                <th className="p-3">Name</th>
                <th className="p-3">Approval</th>
                <th className="p-3">Steps</th>
              </tr>
            </thead>
            <tbody>
              {workflows.length === 0 && (
                <tr>
                  <td colSpan={3} className="p-8 text-center text-slate-500">
                    No saved workflows found.
                  </td>
                </tr>
              )}
              {workflows.map((w) => (
                <tr
                  key={w.id}
                  aria-selected={w.id === selectedWorkflowId}
                  className={
                    w.id === selectedWorkflowId
                      ? "bg-sky-500/15"
                      : "hover:bg-white/5"
                  }
                >
                  <td className="p-3">
                    <button
                      className="w-full text-left"
                      onClick={() => {
                        setSelectedWorkflowId(w.id);
                        reviewWorkflow(w.id);
                      }}
                    >
                      {w.name}
                    </button>
                  </td>
                  <td className="p-3">{w.status}</td>
                  <td className="p-3">{w.steps.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="my-4 flex flex-wrap gap-2">
          <button className={button} onClick={refreshWorkflows}>
            <RefreshCw size={14} />
            Refresh
          </button>
          <button
            className={button}
            disabled={!selected}
            onClick={() => selected && reviewWorkflow(selected.id)}
          >
            <FileSearch size={14} />
            Review
          </button>
          <button
            className={button}
            disabled={!selected}
            onClick={() =>
              selected &&
              editWorkflow(
                selected.id,
                selected.name,
                selected.tools,
                selected.steps,
              )
            }
          >
            <Pencil size={14} />
            Edit in SHU dialog
          </button>
          <button
            className={button}
            disabled={selected?.status !== "Pending approval"}
            onClick={() => selected && approveWorkflow(selected.id)}
          >
            <Check size={14} />
            Approve
          </button>
          <button
            className={button}
            disabled={!selected || selected.status === "Revoked"}
            onClick={() => selected && revokeWorkflow(selected.id)}
          >
            <Ban size={14} />
            Revoke
          </button>
          <button
            className={button}
            disabled={selected?.status !== "Approved"}
            onClick={() => selected && replayWorkflow(selected.id)}
          >
            <Play size={14} />
            Replay
          </button>
          <button
            className={button}
            onClick={() => openRuntimeControls("tasks")}
          >
            Task queue and recovery
          </button>
        </div>
        <pre className="min-h-40 flex-1 whitespace-pre-wrap rounded-xl border border-slate-800 bg-[#070d1b] p-4 text-xs text-slate-300">
          {workflowPreviewText ||
            "Select a workflow to review its actual steps."}
        </pre>
      </div>
    </section>
  );
};
