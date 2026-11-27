import React, { useState } from 'react';
import { BookmarkCheck, Eye, Send, Trash2, Users, X } from 'lucide-react';
import { useShu } from '../context/ShuContext';
import type { CommunicationChannel } from '../types/shu';

export const CommunicationsView: React.FC = () => {
  const {
    setActiveTab,
    draft,
    canSendDraft,
    canSaveDraft,
    updateDraftField,
    createAndPreviewDraft,
    saveReviewedEmailToProviderDrafts,
    confirmAndSendExactPreview,
    whatsappContacts,
    addWhatsAppContact,
    removeWhatsAppContact,
    openRuntimeControls,
  } = useShu();

  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [contactsOpen, setContactsOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newPhone, setNewPhone] = useState('');
  const [contactError, setContactError] = useState<string | null>(null);

  const handleCreatePreview = () => {
    const res = createAndPreviewDraft();
    setErrorMsg(res.ok ? null : res.error ?? 'Validation error');
  };

  const handleSaveProvider = () => {
    const res = saveReviewedEmailToProviderDrafts();
    setErrorMsg(res.ok ? null : res.error ?? 'Save failed');
  };

  const handleConfirmSend = () => {
    const res = confirmAndSendExactPreview();
    setErrorMsg(res.ok ? null : res.error ?? 'Dispatch failed');
  };

  const handleAddContact = (e: React.FormEvent) => {
    e.preventDefault();
    const res = addWhatsAppContact(newName, newPhone);
    if (!res.ok) {
      setContactError(res.error ?? 'Invalid contact');
      return;
    }
    setContactError(null);
    setNewName('');
    setNewPhone('');
  };

  return (
    <section
      aria-label="Communications drafts"
      className="relative z-10 mx-auto flex h-full w-full max-w-6xl flex-col px-4 py-6 overflow-hidden"
    >
      <div className="holo-surface flex flex-1 min-h-0 flex-col rounded-2xl p-6 overflow-y-auto shu-scroll">
        <div className="flex items-start justify-between gap-4 border-b border-slate-800/80 pb-3">
          <div>
            <h1 className="font-display text-xl font-semibold text-slate-100">
              Communications
            </h1>
            <p className="mt-0.5 text-sm text-slate-400">
              Create a local draft, review its exact preview, then confirm sending. Provider authorization is still required.
            </p>
          </div>
          <button
            type="button"
            data-testid="close-popup-card"
            onClick={() => setActiveTab('assistant')}
            aria-label="Close Communications popup"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/15 bg-white/5 text-slate-300 transition-colors hover:border-sky-400/50 hover:bg-sky-500/15 hover:text-white focus-visible:outline-2 focus-visible:outline-sky-400"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        {/* Form Fields */}
        <button type="button" className="mt-3 text-left text-sm text-sky-300" onClick={() => openRuntimeControls('communications')}>
          Open template composer and advanced communications controls
        </button>
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
            <label htmlFor="comm-channel" className="text-xs font-medium text-slate-300">
              Channel
            </label>
            <select
              id="comm-channel"
              value={draft.channel}
              onChange={(e) => updateDraftField('channel', e.target.value as CommunicationChannel)}
              className="holo-input rounded-lg px-3.5 py-2 text-sm"
            >
              <option value="Email">Email</option>
              <option value="WhatsApp">WhatsApp</option>
            </select>
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
            <label htmlFor="comm-recipient" className="text-xs font-medium text-slate-300">
              Recipient
            </label>
            <input
              id="comm-recipient"
              type="text"
              value={draft.recipient}
              onChange={(e) => updateDraftField('recipient', e.target.value)}
              placeholder="Email address or +E.164 phone number"
              className="holo-input rounded-lg px-3.5 py-2 text-sm"
            />
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[120px_1fr] sm:items-center">
            <label htmlFor="comm-subject" className="text-xs font-medium text-slate-300">
              Subject
            </label>
            <input
              id="comm-subject"
              type="text"
              value={draft.subject}
              disabled={draft.channel === 'WhatsApp'}
              onChange={(e) => updateDraftField('subject', e.target.value)}
              placeholder={
                draft.channel === 'WhatsApp'
                  ? 'Not used for WhatsApp'
                  : 'Email subject'
              }
              className="holo-input rounded-lg px-3.5 py-2 text-sm disabled:opacity-45"
            />
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[120px_1fr]">
            <label htmlFor="comm-message" className="pt-2 text-xs font-medium text-slate-300">
              Message
            </label>
            <textarea
              id="comm-message"
              rows={4}
              value={draft.message}
              onChange={(e) => updateDraftField('message', e.target.value)}
              placeholder="Message text"
              className="holo-input rounded-lg px-3.5 py-2 text-sm resize-none"
            />
          </div>
        </div>

        {errorMsg && (
          <p role="alert" className="mt-2 text-xs text-rose-300">
            {errorMsg}
          </p>
        )}

        {/* Action Row */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleCreatePreview}
            className="inline-flex items-center gap-1.5 rounded-lg border border-sky-400/50 bg-sky-500/20 px-4 py-2 text-xs font-medium text-sky-100 hover:bg-sky-500/30 whitespace-nowrap shrink-0"
          >
            <Eye className="h-3.5 w-3.5" aria-hidden="true" />
            Create and preview draft
          </button>

          <button
            type="button"
            disabled={!draft.exactPreview || !canSaveDraft}
            onClick={handleSaveProvider}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/70 px-4 py-2 text-xs font-medium text-slate-200 hover:border-sky-400/40 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap shrink-0"
          >
            <BookmarkCheck className="h-3.5 w-3.5" aria-hidden="true" />
            Save reviewed email to provider drafts
          </button>

          <button
            type="button"
            disabled={!draft.exactPreview || !canSendDraft}
            onClick={handleConfirmSend}
            className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/45 bg-teal-500/15 px-4 py-2 text-xs font-medium text-teal-100 hover:bg-teal-500/25 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap shrink-0"
          >
            <Send className="h-3.5 w-3.5" aria-hidden="true" />
            Confirm and send exact preview
          </button>
        </div>

        {/* Exact Draft Preview Pane */}
        <div className="mt-4 flex-1 min-h-[120px] rounded-xl border border-slate-800/80 bg-[#070d1b] p-4">
          {draft.exactPreview ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Exact draft preview</span>
                <span>
                  {draft.sent
                    ? 'Dispatched'
                    : draft.savedToProviderDrafts
                    ? 'Saved to provider drafts'
                    : canSendDraft ? 'Ready for confirmation' : 'See runtime result below'}
                </span>
              </div>
              <pre className="font-mono text-xs text-slate-200 whitespace-pre-wrap">
                {draft.exactPreview}
              </pre>
            </div>
          ) : (
            <p className="text-sm text-slate-500">Exact draft preview appears here.</p>
          )}
        </div>

        {/* Manage Local WhatsApp Contacts */}
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setContactsOpen((v) => !v)}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700/80 bg-slate-900/70 px-4 py-2 text-xs font-medium text-slate-200 hover:border-sky-400/40"
          >
            <Users className="h-3.5 w-3.5" aria-hidden="true" />
            Manage local WhatsApp contacts
          </button>

          {contactsOpen && (
            <div className="mt-3 holo-surface-subtle rounded-xl p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-display text-sm font-medium text-slate-200">
                  Local WhatsApp contacts
                </h2>
                <button
                  type="button"
                  onClick={() => setContactsOpen(false)}
                  aria-label="Close WhatsApp contacts drawer"
                  className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-white/15 bg-white/5 text-slate-300 hover:border-sky-400/45 hover:text-white"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>

              <div className="space-y-1.5">
                {whatsappContacts.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 px-3 py-2 text-xs"
                  >
                    <div>
                      <span className="font-medium text-slate-200">{c.name}</span>
                      <span className="ml-3 font-mono text-sky-300">{c.phone}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          updateDraftField('channel', 'WhatsApp');
                          updateDraftField('recipient', c.phone);
                          setContactsOpen(false);
                        }}
                        className="rounded-md border border-sky-400/40 px-2.5 py-1 text-xs text-sky-200 hover:bg-sky-500/20"
                      >
                        Use contact
                      </button>
                      <button
                        type="button"
                        aria-label={`Remove ${c.name}`}
                        onClick={() => removeWhatsAppContact(c.id)}
                        className="text-slate-400 hover:text-rose-300 p-1"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <form onSubmit={handleAddContact} className="flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Contact name"
                  aria-label="WhatsApp contact name"
                  className="holo-input flex-1 min-w-[140px] rounded-lg px-3 py-1.5 text-xs"
                />
                <input
                  type="text"
                  value={newPhone}
                  onChange={(e) => setNewPhone(e.target.value)}
                  placeholder="+14155550199"
                  aria-label="WhatsApp +E.164 phone number"
                  className="holo-input font-mono flex-1 min-w-[150px] rounded-lg px-3 py-1.5 text-xs"
                />
                <button
                  type="submit"
                  className="rounded-lg border border-sky-400/50 bg-sky-500/20 px-3.5 py-1.5 text-xs font-medium text-sky-100 hover:bg-sky-500/30"
                >
                  Add contact
                </button>
              </form>
              {contactError && <p className="text-xs text-rose-300">{contactError}</p>}
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
