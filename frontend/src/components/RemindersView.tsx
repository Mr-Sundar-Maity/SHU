import React, { useMemo, useState } from 'react';
import { AlarmClock, CheckCircle2, Clock, Sparkles, X, XCircle } from 'lucide-react';
import { useShu } from '../context/ShuContext';

export const RemindersView: React.FC = () => {
  const {
    setActiveTab,
    reminders,
    selectedReminderId,
    setSelectedReminderId,
    quietMode,
    setQuietMode,
    addReminder,
    scheduleNaturalPhrase,
    snoozeReminder,
    completeReminder,
    cancelReminder,
  } = useShu();

  const [naturalPhrase, setNaturalPhrase] = useState('');
  const [reminderText, setReminderText] = useState('');
  const [dueLocal, setDueLocal] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [phrasePreview, setPhrasePreview] = useState<string | null>(null);

  const selectedReminder = useMemo(
    () => reminders.find((r) => r.id === selectedReminderId) ?? null,
    [reminders, selectedReminderId]
  );

  const handleAddReminder = (e: React.FormEvent) => {
    e.preventDefault();
    const res = addReminder(reminderText, dueLocal);
    if (!res.ok) {
      setFormError(res.error ?? 'Unable to add reminder.');
      return;
    }
    setFormError(null);
    setReminderText('');
  };

  const handleReviewAndSchedulePhrase = () => {
    if (!naturalPhrase.trim()) {
      setFormError('Enter a natural language phrase first.');
      return;
    }
    setPhrasePreview('Review the parsed time in the native SHU confirmation dialog.');
    const res = scheduleNaturalPhrase(naturalPhrase);
    if (res.ok) {
      setFormError(null);
      setNaturalPhrase('');
    }
  };

  return (
    <section
      aria-label="Reminders scheduler"
      className="relative z-10 mx-auto flex h-full w-full max-w-6xl flex-col px-4 py-6 overflow-hidden"
    >
      <div className="holo-surface flex flex-1 min-h-0 flex-col rounded-2xl p-6">
        <div className="flex items-center justify-between gap-4 border-b border-slate-800/80 pb-3">
          <h1 className="font-display text-xl font-semibold text-slate-100">
            Reminders
          </h1>
          <button
            type="button"
            data-testid="close-popup-card"
            onClick={() => setActiveTab('assistant')}
            aria-label="Close Reminders popup"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/15 bg-white/5 text-slate-300 transition-colors hover:border-sky-400/50 hover:bg-sky-500/15 hover:text-white focus-visible:outline-2 focus-visible:outline-sky-400"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        {/* Reminder Creation Form */}
        <form onSubmit={handleAddReminder} className="mt-4 space-y-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[150px_1fr] sm:items-center">
            <label htmlFor="rem-natural-input" className="text-xs font-medium text-slate-300">
              Natural language
            </label>
            <input
              id="rem-natural-input"
              type="text"
              value={naturalPhrase}
              onChange={(e) => setNaturalPhrase(e.target.value)}
              placeholder="Remind me to stretch in 20 minutes, or call Sam tomorrow at 9 AM"
              className="holo-input rounded-lg px-3.5 py-2 text-sm"
            />
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[150px_1fr] sm:items-center">
            <label htmlFor="rem-text-input" className="text-xs font-medium text-slate-300">
              Reminder
            </label>
            <input
              id="rem-text-input"
              type="text"
              value={reminderText}
              onChange={(e) => setReminderText(e.target.value)}
              placeholder="What should SHU remind you about?"
              className="holo-input rounded-lg px-3.5 py-2 text-sm"
            />
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[150px_1fr] sm:items-center">
            <label htmlFor="rem-due-input" className="text-xs font-medium text-slate-300">
              Due time (local)
            </label>
            <input
              id="rem-due-input"
              type="text"
              value={dueLocal}
              onChange={(e) => setDueLocal(e.target.value)}
              placeholder="2026-11-24 20:31"
              className="holo-input font-mono rounded-lg px-3.5 py-2 text-sm"
            />
          </div>

          {formError && (
            <p role="alert" className="text-xs text-rose-300">
              {formError}
            </p>
          )}
          {phrasePreview && (
            <p className="text-xs text-sky-300 font-mono">{phrasePreview}</p>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 rounded-lg border border-sky-400/50 bg-sky-500/20 px-4 py-2 text-xs font-medium text-sky-100 hover:bg-sky-500/30 whitespace-nowrap shrink-0"
            >
              <Clock className="h-3.5 w-3.5" aria-hidden="true" />
              Add reminder
            </button>

            <button
              type="button"
              onClick={handleReviewAndSchedulePhrase}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-4 py-2 text-xs font-medium text-slate-200 hover:border-sky-400/40 whitespace-nowrap shrink-0"
            >
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              Review and schedule phrase
            </button>

            <label className="ml-auto inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={quietMode}
                onChange={(e) => setQuietMode(e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 accent-sky-400"
              />
              Quiet mode (show reminder without speaking)
            </label>
          </div>
        </form>

        {/* Reminders Table */}
        <div className="mt-4 flex-1 min-h-0 overflow-auto shu-scroll rounded-xl border border-slate-800/80">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="sticky top-0 bg-[#0b1324] text-xs font-medium text-slate-400 border-b border-slate-800">
              <tr>
                <th scope="col" className="w-44 px-4 py-3">Due</th>
                <th scope="col" className="px-4 py-3">Reminder</th>
                <th scope="col" className="w-32 px-4 py-3">Status</th>
                <th scope="col" className="w-28 px-4 py-3 text-right">ID</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {reminders.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-sm text-slate-400">
                    No reminders scheduled. Add one above or speak a reminder to SHU.
                  </td>
                </tr>
              ) : (
                reminders.map((item) => {
                  const selected = item.id === selectedReminderId;
                  return (
                    <tr
                      key={item.id}
                      onClick={() => setSelectedReminderId(selected ? null : item.id)}
                      aria-selected={selected}
                      className={`cursor-pointer transition-colors ${
                        selected
                          ? 'bg-sky-500/15 text-slate-100'
                          : 'hover:bg-slate-900/50 text-slate-300'
                      }`}
                    >
                      <td className="px-4 py-2.5 font-mono text-xs text-sky-300">
                        {item.due}
                      </td>
                      <td className="px-4 py-2.5 text-sm">{item.reminder}</td>
                      <td className="px-4 py-2.5 text-xs">
                        <span
                          className={
                            item.status === 'Completed'
                              ? 'text-teal-300'
                              : item.status === 'Cancelled'
                              ? 'text-slate-500'
                              : item.status === 'Snoozed'
                              ? 'text-amber-300'
                              : 'text-slate-300'
                          }
                        >
                          {item.status}
                        </span>
                      </td>
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

        {/* Bottom 3 Actions matching reference */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={!selectedReminder}
            onClick={() => selectedReminder && snoozeReminder(selectedReminder.id)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-4 py-2 text-xs font-medium text-slate-200 hover:border-sky-400/40 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap shrink-0"
          >
            <AlarmClock className="h-3.5 w-3.5" aria-hidden="true" />
            Snooze 10m
          </button>

          <button
            type="button"
            disabled={!selectedReminder}
            onClick={() => selectedReminder && completeReminder(selectedReminder.id)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-4 py-2 text-xs font-medium text-teal-200 hover:border-teal-400/50 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap shrink-0"
          >
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            Complete
          </button>

          <button
            type="button"
            disabled={!selectedReminder}
            onClick={() => selectedReminder && cancelReminder(selectedReminder.id)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-4 py-2 text-xs font-medium text-rose-200 hover:border-rose-400/50 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap shrink-0"
          >
            <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
            Cancel
          </button>
        </div>
      </div>
    </section>
  );
};
