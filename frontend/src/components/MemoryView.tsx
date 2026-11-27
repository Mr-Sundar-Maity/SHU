import React, { useMemo, useState } from 'react';
import {
  Download,
  GitMerge,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { useShu } from '../context/ShuContext';
import type { MemoryCategory } from '../types/shu';

const CATEGORIES: MemoryCategory[] = ['Preference', 'Fact'];

export const MemoryView: React.FC = () => {
  const {
    setActiveTab,
    memories,
    selectedMemoryId,
    setSelectedMemoryId,
    addApprovedMemory,
    correctSelectedMemory,
    deleteSelectedMemory,
    refreshMemories,
    exportApprovedMemories,
    duplicatePairs,
    refreshDuplicateScan,
    mergeDuplicatePair,
  } = useShu();

  const [query, setQuery] = useState('');
  const [editorMode, setEditorMode] = useState<'none' | 'add' | 'edit'>('none');
  const [draftType, setDraftType] = useState<MemoryCategory>('Preference');
  const [draftContent, setDraftContent] = useState('');
  const [duplicatesOpen, setDuplicatesOpen] = useState(false);

  const selectedMemory = useMemo(
    () => memories.find((m) => m.id === selectedMemoryId) ?? null,
    [memories, selectedMemoryId]
  );

  const filteredMemories = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return memories;
    return memories.filter(
      (m) =>
        m.content.toLowerCase().includes(q) ||
        m.type.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q)
    );
  }, [memories, query]);

  const openAdd = () => {
    setDraftType('Preference');
    setDraftContent('');
    setEditorMode('add');
  };

  const openCorrect = () => {
    if (!selectedMemory) return;
    setDraftType(selectedMemory.type);
    setDraftContent(selectedMemory.content);
    setEditorMode('edit');
  };

  const handleSaveEditor = (e: React.FormEvent) => {
    e.preventDefault();
    if (!draftContent.trim()) return;
    if (editorMode === 'add') {
      addApprovedMemory(draftType, draftContent);
    } else if (editorMode === 'edit' && selectedMemory) {
      correctSelectedMemory(selectedMemory.id, draftType, draftContent);
    }
    setEditorMode('none');
    setDraftContent('');
  };

  const handleReviewDuplicates = () => {
    refreshDuplicateScan();
  };

  return (
    <section
      aria-label="Memory vault"
      className="relative z-10 mx-auto flex h-full w-full max-w-6xl flex-col px-4 py-6 overflow-hidden"
    >
      <div className="holo-surface flex flex-1 min-h-0 flex-col rounded-2xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
          <div>
            <h1 className="font-display text-xl font-semibold text-slate-100">
              Memory
            </h1>
            <p className="mt-0.5 text-sm text-slate-400">
              Only approved memories are shown here.
            </p>
          </div>

          <div className="flex w-full sm:w-auto items-center justify-end gap-2">
            <div className="relative flex-1 sm:w-64 sm:flex-initial">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
                aria-hidden="true"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter memories..."
                aria-label="Filter approved memories"
                className="holo-input w-full rounded-lg pl-8 pr-3 py-1.5 text-xs"
              />
            </div>

            <button
              type="button"
              data-testid="close-popup-card"
              onClick={() => setActiveTab('assistant')}
              aria-label="Close Memory popup"
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/15 bg-white/5 text-slate-300 transition-colors hover:border-sky-400/50 hover:bg-sky-500/15 hover:text-white focus-visible:outline-2 focus-visible:outline-sky-400"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Inline Add / Correct Memory Editor */}
        {editorMode !== 'none' && (
          <form
            onSubmit={handleSaveEditor}
            className="mt-4 holo-surface-subtle rounded-xl p-4 flex flex-col gap-3"
          >
            <div className="flex flex-wrap items-center gap-3">
              <label htmlFor="memory-type-select" className="text-xs font-medium text-slate-300">
                Type
              </label>
              <select
                id="memory-type-select"
                disabled={editorMode === 'edit'}
                value={draftType}
                onChange={(e) => setDraftType(e.target.value as MemoryCategory)}
                className="holo-input rounded-lg px-3 py-1.5 text-xs"
              >
                {CATEGORIES.map((cat) => (
                  <option key={cat} value={cat}>
                    {cat}
                  </option>
                ))}
              </select>
              <span className="text-xs text-slate-400">
                {editorMode === 'add'
                  ? 'New approved memory'
                  : `Correcting ${selectedMemory?.id}`}
              </span>
            </div>

            <label htmlFor="memory-content-input" className="sr-only">
              Memory content
            </label>
            <input
              id="memory-content-input"
              type="text"
              value={draftContent}
              onChange={(e) => setDraftContent(e.target.value)}
              placeholder="Enter memory statement..."
              className="holo-input w-full rounded-lg px-3.5 py-2 text-sm"
            />

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditorMode('none')}
                className="rounded-lg border border-slate-700 px-3.5 py-1.5 text-xs text-slate-300 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg border border-sky-400/50 bg-sky-500/20 px-4 py-1.5 text-xs font-medium text-sky-100 hover:bg-sky-500/30"
              >
                {editorMode === 'add' ? 'Save approved memory' : 'Apply correction'}
              </button>
            </div>
          </form>
        )}

        {/* Duplicate Review Drawer */}
        {duplicatesOpen && (
          <div className="mt-4 holo-surface-subtle rounded-xl p-4">
            <div className="flex items-center justify-between gap-2 mb-2">
              <h2 className="font-display text-sm font-medium text-sky-200">
                Possible duplicates ({duplicatePairs.length})
              </h2>
              <button
                type="button"
                onClick={() => setDuplicatesOpen(false)}
                aria-label="Close duplicates review"
                className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-white/15 bg-white/5 text-slate-300 hover:border-sky-400/45 hover:text-white"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
            {duplicatePairs.length === 0 ? (
              <p className="text-xs text-slate-400">
                No overlapping memory pairs detected.
              </p>
            ) : (
              <div className="space-y-2 max-h-36 overflow-y-auto shu-scroll">
                {duplicatePairs.map((pair) => (
                  <div
                    key={`${pair.a.id}-${pair.b.id}`}
                    className="flex flex-wrap items-center justify-between gap-3 border border-slate-800 rounded-lg px-3 py-2 text-xs"
                  >
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <p className="text-slate-200 truncate">
                        <span className="font-mono text-sky-300 mr-2">{pair.a.id}</span>
                        {pair.a.content}
                      </p>
                      <p className="text-slate-400 truncate">
                        <span className="font-mono text-slate-500 mr-2">{pair.b.id}</span>
                        {pair.b.content}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => mergeDuplicatePair(pair.a.id, pair.b.id)}
                      className="rounded-md border border-teal-400/40 bg-teal-500/15 px-3 py-1.5 text-xs text-teal-200 hover:bg-teal-500/25 whitespace-nowrap shrink-0"
                    >
                      Keep {pair.a.id} · Remove {pair.b.id}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Table */}
        <div className="mt-4 flex-1 min-h-0 overflow-auto shu-scroll rounded-xl border border-slate-800/80">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="sticky top-0 bg-[#0b1324] text-xs font-medium text-slate-400 border-b border-slate-800">
              <tr>
                <th scope="col" className="w-32 px-4 py-3">Type</th>
                <th scope="col" className="px-4 py-3">Content</th>
                <th scope="col" className="w-28 px-4 py-3 text-right">ID</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {filteredMemories.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-10 text-center text-sm text-slate-400">
                    No approved memories match your filter. Add a memory below to begin.
                  </td>
                </tr>
              ) : (
                filteredMemories.map((item) => {
                  const selected = item.id === selectedMemoryId;
                  return (
                    <tr
                      key={item.id}
                      onClick={() => setSelectedMemoryId(selected ? null : item.id)}
                      aria-selected={selected}
                      className={`cursor-pointer transition-colors ${
                        selected
                          ? 'bg-sky-500/15 text-slate-100'
                          : 'hover:bg-slate-900/50 text-slate-300'
                      }`}
                    >
                      <td className="px-4 py-2.5 text-xs font-medium text-sky-300">
                        {item.type}
                      </td>
                      <td className="px-4 py-2.5 text-sm">{item.content}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-400">
                        {item.id}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Bottom 6 Action Buttons matching reference */}
        <div className="mt-4 flex flex-wrap lg:flex-nowrap items-center gap-1.5 pt-1">
          <button
            type="button"
            onClick={openAdd}
            className="inline-flex items-center gap-1.5 rounded-lg border border-sky-400/50 bg-sky-500/20 px-2.5 py-2 text-xs font-medium text-sky-100 hover:bg-sky-500/30 whitespace-nowrap shrink-0"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Add approved memory
          </button>

          <button
            type="button"
            disabled={!selectedMemory}
            onClick={openCorrect}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-2 text-xs font-medium text-slate-200 hover:border-sky-400/40 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap shrink-0"
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            Correct selected memory
          </button>

          <button
            type="button"
            disabled={!selectedMemory}
            onClick={() => selectedMemory && deleteSelectedMemory(selectedMemory.id)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-2 text-xs font-medium text-rose-200 hover:border-rose-400/50 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap shrink-0"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            Delete selected memory
          </button>

          <button
            type="button"
            onClick={exportApprovedMemories}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-2 text-xs font-medium text-slate-200 hover:border-sky-400/40 whitespace-nowrap shrink-0"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Export approved memories
          </button>

          <button
            type="button"
            onClick={handleReviewDuplicates}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-2 text-xs font-medium text-slate-200 hover:border-sky-400/40 whitespace-nowrap shrink-0"
          >
            <GitMerge className="h-3.5 w-3.5" aria-hidden="true" />
            Review possible duplicates
          </button>

          <button
            type="button"
            onClick={refreshMemories}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-2 text-xs font-medium text-slate-200 hover:border-sky-400/40 whitespace-nowrap shrink-0 lg:ml-auto"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Refresh
          </button>
        </div>
      </div>
    </section>
  );
};
