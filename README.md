# SHU - Personal Voice Assistant

SHU is a local-first Windows voice assistant. The repository contains the
voice and AI path plus the v1 foundations for approved memory, task execution,
desktop tools, isolated public-page reading and form preparation, Office file generation, reminders,
communications drafts, and a React dashboard hosted by PySide6. The project tracks hardware and
account prerequisites, acceptance evidence across all 19 phases, and the point
where development should resume. [Delivery status](https://github.com/Mr-Sundar-Maity/SHU/blob/main/docs/STATUS.md) · [PRD traceability](https://github.com/Mr-Sundar-Maity/SHU/blob/main/docs/PRD_TRACEABILITY.md) · [Progress checkpoint](https://github.com/Mr-Sundar-Maity/SHU/blob/main/docs/PROJECT_PROGRESS.md)

Original planning references: [Master PRD v1.0](https://github.com/Mr-Sundar-Maity/SHU/blob/main/SHU_Master_PRD_Detailed_v1.pdf)
and [Technology and installation guide](https://github.com/Mr-Sundar-Maity/SHU/blob/main/SHU_Complete_Technology_and_Installation_Guide_v1.pdf).
Their prototype/install status is historical; use the dated progress checkpoint
for the verified implementation and current prerequisites.

## Requirements

- Windows 10/11 and Python 3.11 (the PowerShell setup script creates `.venv`)
- Node.js 22.12+ and npm for building the desktop dashboard
- Ollama with the configured local model (default: `qwen2.5:1.5b`)
- A microphone and speaker for live voice use
- Microsoft Office for Office document generation
- Internet access for first Whisper model download, Chromium installation,
  and Edge TTS playback

User data is stored separately under `C:\SHU_DATA` by default. Real settings
belong in `.env`; `.env` is ignored by Git. Start from `.env.example` if setup
creates the file for you.

## Full v1 setup

Run in PowerShell:

```powershell
cd C:\SHU
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The installer runs setup, creates `.venv` if needed, installs the pinned core and v1
dependencies, builds the frontend with npm, installs Playwright Chromium, initializes/upgrades the SQLite
schema with a pre-migration backup, checks package consistency, and creates a
current-user Start Menu shortcut. Use `-CoreOnly` for terminal chat and core
tools without the desktop integrations. Core-only setup creates no shortcuts
and cannot be paired with `-EnableStartup`.

Startup launch is opt-in. Running a full install without `-EnableStartup`
leaves any existing SHU startup registration in place.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -EnableStartup
```

Remove only the Start Menu and Startup shortcuts with `-RemoveShortcuts`; this
preserves the project, `.env`, virtual environment, database and user data:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -RemoveShortcuts
```

For dependency or database setup without creating shortcuts, run
`scripts\setup.ps1` directly.

Build a private, personal-use source bundle after editing the project. Use a
new unique output name each time; the builder refuses to overwrite an existing
ZIP or checksum:

```powershell
python scripts\package_personal.py --output dist\SHU_personal_source_YYYY-MM-DD.zip
```

The ZIP contains allowlisted source, tests, documentation and setup files. The
builder excludes `.env`, OAuth credentials, local databases, model files and
user data; it checks archive paths/CRC and Python syntax, then writes a SHA-256
sidecar. This is a source archive for personal testing; it is not a signed
binary installer.

When setup runs elevated, it also restricts `.env`, the configured Gmail OAuth
client JSON, and `SHU_DATA_DIR` access to the current user, SYSTEM, and
Administrators. If setup runs without elevation,
open an Administrator PowerShell and run
`powershell -ExecutionPolicy Bypass -File scripts\secure-data.ps1`; then rerun
`.\.venv\Scripts\python.exe -m app.cli doctor` and confirm `Private data ACL` passes. The script
refuses a data directory inside the source tree and refuses junctions or
symbolic links in private paths.

Activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run that activation command in each new PowerShell window before using the
`python -m app.cli ...` examples below. Without activation, `python` may point
to a different Python installation that does not contain SHU's dependencies.
Direct invocation also works: .\.venv\Scripts\python.exe -m app.cli ...

## Run SHU

Open the desktop dashboard:

```powershell
.\.venv\Scripts\python.exe -m app.cli gui
```

The direct command above uses the project environment even if it has not been
activated in this PowerShell session.

The default window now uses the UI from `frontend/`, connected directly to the
existing Python runtime through Qt WebChannel. It reads actual SHU records and
settings; empty stores stay empty. Demo conversations, contacts, metrics, weather
and simulated actions are removed from the running interface. Weather and audio
waveform telemetry are explicitly unavailable until integrated.

After updating frontend source, rebuild it once:

```powershell
cd C:\SHU\frontend
npm ci --ignore-scripts
npm run build
cd C:\SHU
.\.venv\Scripts\python.exe -m app.cli gui
```

`npm run dev` is a design preview without a connected Python runtime. The desktop
build needs no browser API key or HTTP bridge. The supplied `frontend/README.md`
is preserved unchanged; use this root README for integrated SHU setup.
Settings, task recovery, workflow editing, advanced messaging and sensitive
approvals open the existing native SHU controls. Closing that controls window
returns to the React dashboard; closing the dashboard shuts down the runtime.

Ollama must be running on the local machine for chat and voice AI. If `doctor`
reports the Ollama service unavailable, open Ollama or run `ollama serve` in a
separate PowerShell window and leave it running. On a new installation, fetch
the configured model once with `ollama pull qwen2.5:1.5b`.

Or use the keyboard chat / voice assistant:

```powershell
python -m app.cli chat
python -m app.cli voice --language bn
```

In CLI text chat, enter `/reset` (or `/clear`) to discard the recent
conversation context and start fresh; approved saved memories are not deleted.
The dashboard's **Reset conversation** button clears the same temporary context
and the visible transcript. Both controls are unavailable while a chat request
or voice session is active. When the 20-turn recent window fills, older turns
are folded into a short bounded summary that is sent as reference data, not as
instructions, so long conversations keep context without replaying the full
transcript.

The dashboard's **Ready** state is idle: it does not capture microphone audio or
run wake-word inference in the background. Audio and the optional custom wake
listener start only after you choose **Start listening**; stopping the session
returns SHU to Ready. The **Voice activity** line distinguishes recording,
transcription, AI processing and speech output. It also shows microphone mute
and whether voice interruptions are enabled during speech output.

The React **Voice engine** card displays that live activity and provides
**Pause speech / Resume speech** for the current voice session. After the voice
session ends, **Plan last voice request** submits its original recognized text
to the existing reviewed task-planning flow. That action stays disabled during
an active voice session or task, when automation is disabled, and after Emergency
stop. It does not execute a plan without the normal approval.

In Settings, **Detect spoken language automatically** enables language detection
for the next voice session. It is off by default and lasts only for the current
app session. When it is off, recognition uses **Default voice language**.
Greetings and clarification prompts start in that default language. During a
session, **Voice language** shows the selected or recognized language, or waits
for detection when recognition is uncertain. Greetings and repeat prompts also
appear in the transcript if speech output is unavailable.

To evaluate a trained local wake-word model offline, prepare consented mono
16 kHz PCM-16 WAV recordings. Put a JSON manifest next to the recordings with
relative file names. Use `label: "positive"` and an `activation_window_seconds`
range for a spoken wake phrase, or `label: "negative"` for recordings that
should never wake SHU. For example:

```json
[
  {"audio": "wake.wav", "label": "positive", "activation_window_seconds": [0.8, 1.8]},
  {"audio": "room.wav", "label": "negative"}
]
```

```powershell
python scripts\evaluate_wake_word.py C:\SHU_DATA\models\hey-shu.onnx C:\SHU_DATA\wake-evaluation\manifest.json --consented
```

The evaluator reports aggregate hits, misses, false activations per hour and
processing time using the live threshold and debounce rules. It requires the
model and runtime assets to be installed locally. Live microphone checks and
representative audio measurements are separate acceptance steps.

List microphone devices and supported speech languages. The mic-check command
lets you select an input and reports approximate level/clipping statistics
after typed confirmation; it keeps no recording or transcript. You can specify
--device INDEX --seconds 3, with a duration between 1 and 15 seconds. After
finding a working input, set SHU_MICROPHONE_DEVICE to that index in .env before
starting voice mode. The level result does not prove speech recognition accuracy.
Optional voice barge-in can interrupt Edge TTS when sustained speech is detected
on the selected microphone. It is off by default; enable it with
`SHU_VOICE_BARGE_IN=true` after the microphone check, or enable it in the
dashboard Settings tab for the next voice session. The dashboard choice lasts
only for the current app session; `.env` keeps the setting across restarts.
SHU keeps a short in-memory
pre-roll and phrase buffer (up to 15 seconds), passes it directly to local Whisper,
and does not save or upload the captured audio. Set `SHU_VOICE_BARGE_IN_RMS` to
adjust its local RMS threshold; speaker echo can cause false triggers, so verify
the threshold with the selected microphone and speaker setup.

In the dashboard, after a voice session ends, **Plan last voice request** sends
the latest recognized utterance to the task planner. Review the original request
and exact proposed steps in the confirmation dialog. SHU starts no task unless
you approve that plan; the voice handoff does not overwrite text already in the
chat input.

Dashboard Settings also provides friendly, casual, formal, serious, humorous
and supportive response styles. Friendly is the default. The dashboard selection
applies for the current session; set `SHU_RESPONSE_STYLE` in `.env` to choose the
startup default. The style changes wording only and does not alter tool approval
or security rules.

```powershell
python -m app.cli mic-list
python -m app.cli mic-check
python -m app.cli languages
```

### Evaluate speech recognition

Use recordings made for testing with each speaker's consent. Keep the WAVs,
reference text, and any deletion schedule in a private corpus directory outside
the source checkout. Use mono 16 kHz WAV clips up to 30 seconds. Put a UTF-8
JSON file beside them and use relative audio paths. For example:

```json
[
  {"audio": "en-01.wav", "language": "en", "reference": "The window is open."},
  {"audio": "bn-mixed.wav", "language": "bn", "cohort": "code-switch", "reference": "Chrome খোলো"}
]
```

```powershell
python scripts\evaluate_stt.py C:\SHU_DATA\speech-evaluation\manifest.json
```

Use `bn`, `hi`, `en`, `ta`, `te`, and `ml`. Omit `cohort` for `clean`, or
choose `noisy` or `code-switch`. For a mixed utterance, `language` is the
expected dominant language. The evaluator uses the cached Whisper model and
tests auto detection and forced language by default. Use `--mode auto` or
`--mode forced` to run only one. It prints per-group WER and CER, detection
results, and missing languages without printing any path, reference or
transcript in the report. WER uses normalized whitespace-delimited words. CER
counts normalized Unicode characters without spaces. Keep the corpus fixed
between comparison runs and have a native speaker review the results.

Measure the local voice path with a consented mono 16 kHz WAV of up to 30
seconds:

```powershell
python scripts\benchmark_voice.py C:\SHU_DATA\speech-evaluation\en-01.wav --consented --trials 3
```

The benchmark uses cached Whisper and an installed local Ollama model. It
reports aggregate file-read, transcription, local response and silent speech
handoff times. It does not capture a microphone, synthesize speech, play audio
or print file paths, transcripts or replies. Use the same clip and model for
comparisons. File-read timing is separate from live capture latency.

Measure local Ollama performance with fixed, non-sensitive prompts. The report
includes round-trip latency (median, p95, minimum and maximum), Ollama model
load/server/prompt/generation timings, installed model size, free space on the
SHU data volume, and Windows system-memory and whole-system CPU snapshots. It
refuses non-loopback endpoints and does not print or store model responses.
`--samples` accepts 1-100 requests; 20 requests provide a short extended run:

```powershell
python scripts\benchmark_local_ai.py --samples 3
```

Local Ollama and Whisper inference share a FIFO CPU-work queue so a long local
AI response does not overlap CPU-heavy transcription. Voice stop and dashboard
Emergency Stop cancel waiting inference for the active session or chat. SHU
discards responses from requests already in progress and skips provider fallback
after cancellation. A provider request already sent may take until its configured
timeout to return. Queue waits are bounded by `SHU_REQUEST_TIMEOUT_SECONDS`.

## Reminders and personal memory

Create a reminder with one of the supported natural-language time forms:

```powershell
python -m app.cli reminders add "Remind me to stretch in 20 minutes"
python -m app.cli reminders add "Call Sam tomorrow at 9 AM" --timezone Asia/Kolkata
python -m app.cli reminders add "Take medicine daily at 8:30 AM"
python -m app.cli reminders add "২০ মিনিট পরে ওষুধ খাও"
python -m app.cli reminders add "मुझे याद दिलाओ 2 घंटे बाद दवा लेना"
python -m app.cli reminders list
```

The parser accepts bounded today/tomorrow, daily, weekly and named-weekday
calendar forms with localized clock words in Bengali, Hindi, Tamil, Telugu and
Malayalam, along with English calendar forms and relative minutes, hours or
days in all six supported languages. For example:

```powershell
python -m app.cli reminders add "ওষুধ খাও আগামীকাল সকাল ৯টা"
python -m app.cli reminders add "दवा लो हर सोमवार शाम 5 बजे"
python -m app.cli reminders add "மருந்து எடுத்துக்கொள் நாளை காலை 9 மணிக்கு"
python -m app.cli reminders add "మందు ప్రతి రోజు ఉదయం 9 గంటలకు"
python -m app.cli reminders add "മരുന്ന് എല്ലാ ആഴ്ചയും തിങ്കളാഴ്ച രാവിലെ 9 മണിക്ക്"
```

English clock forms also accept explicit morning/afternoon/evening/night
dayparts and the unambiguous words noon, midday and midnight. Conflicting
daypart and AM/PM cues are rejected. Unclear or past same-day times are
rejected. These phrases are a bounded set of supported forms; unrecognized
grammar must be rephrased. The dashboard shows parsed text and time before
saving.
The dashboard must be running to deliver scheduled reminders. If quiet mode is
off, reminders are also spoken using the selected language's Edge TTS voice.
Daily and weekly reminders start at their saved date and time, then recur in
the saved time zone. For later occurrences, SHU skips a nonexistent local
time and uses the earlier occurrence of a repeated time. Dashboard reminders
use the Windows time zone, and the pending list displays each reminder in its
saved time zone with the UTC offset. Turning on Quiet mode before a queued
notification reaches the dashboard suppresses its speech.
Multiple SHU sessions share one delivery attempt for each reminder occurrence.
If SHU is interrupted during a one-time attempt, its status shows
**Delivery uncertain**. Use Snooze to schedule a new occurrence if needed.

When adding or correcting approved memories, SHU rejects known credential
formats and common password assignments in its six supported languages.
Memory expiry dates must include a timezone. Expired records are excluded from
retrieval, listing and export; permanent deletion requires a separate command:

```powershell
python -m app.cli memory retention MEMORY_ID --until 2027-01-01T00:00:00+05:30 --confirm
python -m app.cli memory retention MEMORY_ID --clear --confirm
python -m app.cli memory purge-expired --confirm
python -m app.cli memory review
```

Memory review reports lexical duplicate and possible-conflict suggestions for
manual comparison; it does not merge or change records. Deleting or expiring a
memory also removes episodic rows explicitly linked to that memory.

## Verify and recover data

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
python -m app.cli doctor
python -m app.cli db backup
python -m app.cli db backup --keep 20
```

`db backup` keeps the newest 10 timestamped SHU backups by default. Rotation
only removes files matching SHU's generated timestamped backup naming pattern.
In the dashboard, choose **SHU → Create database backup** to verify and save a
snapshot in SHU's private backups folder while the window stays responsive.
The dashboard keeps earlier backup copies.

The current Windows user has the SHU dashboard logon shortcut enabled. Run
these commands to recreate it or disable it (run setup first):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\manage-startup.ps1
powershell -ExecutionPolicy Bypass -File scripts\manage-startup.ps1 -Remove
python scripts\generate_license_inventory.py
```

The shortcut starts the dashboard with the project's `pythonw.exe`. The setup
script does not register it automatically on a fresh machine.
The license inventory captures metadata from the active virtual environment in
`docs/THIRD_PARTY_LICENSES.csv`. Review the listed license texts before release;
the report does not select a license for SHU itself.

## Persistent task queue

Task plans remain in SQLite with `planned` status until a user starts them.
Inspect the FIFO queue, then review and run only its oldest plan with an explicit
confirmation. Each modifying or separately approval-gated tool asks for its own
approval; refusing an action does not call its handler.

```powershell
python -m app.cli tasks queue
python -m app.cli tasks run-next --confirm
```

`tasks queue` is read-only. `tasks run-next` runs at most one task. Without
`--confirm`, it prints the next plan and exits without starting anything. The
dashboard Task Queue tab provides the same FIFO review and run controls.

The public webpage reader may retry a transient transport failure or HTTP
408/425/429/5xx response up to two times with bounded exponential backoff.
Automatic retries are available only to registered read-only tools; modifying
and external actions are never retried by this policy. SHU can interrupt a
backoff wait immediately when the emergency stop is triggered.

Interrupted tasks can be inspected and resumed only when SHU stopped between
verified steps. If the SHU process exits while a step is in flight, the next
startup marks that step as uncertain and never replays it automatically. Inspect
the target app, then explicitly record whether the action did not happen or
completed and was reviewed:

```powershell
python -m app.cli tasks status TASK_ID
python -m app.cli tasks resume TASK_ID --confirm
python -m app.cli tasks recover TASK_ID --action retry --confirm
python -m app.cli tasks recover TASK_ID --action accept-complete --confirm
python -m app.cli tasks feedback TASK_ID
```

Use `retry` only after confirming the uncertain action did not take effect;
use `accept-complete` only after checking its result. Both commands require a
typed `YES`. The former leaves a safe checkpoint for a separately reviewed
`tasks resume`; the latter records a manual-review result and does not replay
that step. If the stored task changes while its resume or recovery review is
open, SHU asks you to review the latest state before it proceeds.

Task feedback is stored in the local audit trail only after an explicit review
and confirmation. Credential-related correction text is rejected.

Close the dashboard and other SHU sessions before restoring the live database.
SHU checks the staged snapshot's schema and integrity, migrates an older
snapshot if needed, and retains a pre-restore backup before replacing the live
file. An existing SQLite journal or interrupted restore staging file stops the
operation for inspection.
Review the file path and pass the explicit confirmation flag:

```powershell
python -m app.cli db restore --from C:\SHU_DATA\memory\backups\shu-backup.db --confirm-restore
```

`doctor` prints `PASS`, `WARN`, or `FAIL`. Warnings call out optional features
that need an account, trained model, or user-specific choice; a `FAIL` means a
core setup check is broken. The delivery status linked above lists the live
checks still pending for each integration.

## Privacy and permissions

- Ollama is the default AI provider; sending local requests to Gemini after an
  Ollama failure stays disabled by default (`SHU_CLOUD_FALLBACK=false`). If
  Gemini is selected and unavailable, SHU tries local Ollama by default
  (`SHU_LOCAL_FALLBACK=true`) and reports that fallback in the console and
  status callback.
- Sensitive prompts and recent context stay local unless cloud personal-data
  processing is explicitly enabled in `.env`; detected sensitive text is also
  blocked from cloud speech synthesis.
- Cloud AI has an independent hard disable: set `SHU_CLOUD_AI_ENABLED=false`
  in `.env` or clear **Cloud AI enabled** in Dashboard Settings. Google-selected
  requests then route to local Ollama, and direct Google calls plus cloud
  fallback are blocked. The dashboard choice applies to new requests in the
  current session; `.env` controls startup defaults. This switch covers AI
  providers, not separate network services such as Edge TTS or email.
- Registered desktop/browser automation has a separate switch:
  `SHU_AUTOMATION_ENABLED=false` in `.env` or clear **SHU automation enabled**
  in Dashboard Settings. Queued tasks remain stopped and the tool registry
  rejects actions even if a caller bypasses disabled dashboard buttons. An
  action already in progress may finish; use Emergency stop to cancel active
  work. The dashboard choice lasts for the current session.
- Edge TTS requires internet and sends non-sensitive speech text to Microsoft's service.
- Edge TTS generation is bounded by `SHU_TTS_TIMEOUT_SECONDS` (20 seconds by
  default). If the service stalls or returns no audio, SHU keeps the text
  response available and removes any partial audio file.
- The dashboard offers speech-rate adjustment from -50% to +50% and playback
  volume from 0% to 100%; the values apply to the next voice session. Dashboard
  text size can be changed immediately from 8 to 24 points with
  `SHU_UI_FONT_SIZE=10` as the default. During a
  session, **Pause speech** and **Resume speech** hold or continue playback;
  Emergency stop still cancels it immediately. The defaults are
  `SHU_TTS_RATE_PERCENT=0` and `SHU_TTS_VOLUME=1.0`.
- Voice barge-in is opt-in (`SHU_VOICE_BARGE_IN=false` by default); when enabled,
  microphone onset detection and its bounded phrase buffer run locally and feed
  directly into Whisper. No microphone recording is written to disk or sent to
  the cloud, and the configured mute control disables the monitor.
- Model responses cannot execute shell commands. Automation is restricted to
  registered tools, validated arguments, explicit approvals, and audit records.
- The dashboard can inspect one exact visible window through UI Automation and,
  after approval, fill one unique empty non-password text field. SHU verifies the
  field value and never submits the form; existing or protected values are left alone.
- Physical mouse clicks require separate explicit approval, a unique named
  visible control in an exact-title non-minimized window, and an expected UIA
  state (`checked`, `unchecked`, `selected`, `unselected`, `hidden` or `disabled`).
  SHU rereads that state after clicking; if it cannot verify the result, the task
  stops as partial and does not repeat the click. If the expected state already
  holds, SHU skips the input.
- Screen OCR is limited to a user-selected rectangle, requires explicit approval,
  runs locally through Tesseract, and does not save the screenshot.
- The dashboard registers `Ctrl+Alt+Pause` as a system-wide emergency stop while
  it is open. If another application owns that key combination, the dashboard
  reports the conflict and its Emergency stop button remains available.
- During a voice session, use **Mute microphone** to pause wake-word/audio
  capture and discard any in-progress recording; **Unmute microphone** resumes it.
  This microphone control is independent of the cloud-AI and automation switches.
- Email mailbox access needs provider OAuth consent. WhatsApp needs a configured
  delivery route and authenticated user session. The Meta Cloud API adapter is
  available when a business phone number ID and access token are set.
- Never commit `.env`, databases, logs, backups, or generated private files.
- Windows ACLs for `.env` and the complete SHU data tree must pass the doctor
  check before storing credentials or relying on private data. The check also
  covers the configured Gmail OAuth client file when it exists.

## Preview, copy and move a file

Use existing regular files and an unused destination inside SHU's exports
directory. The preview prints size and SHA-256 without displaying file contents.
Replace `SHA256_FROM_PREVIEW` with the digest shown by the first command:

```powershell
python -m app.cli files preview C:\SHU_DATA\memory\exports\notes.txt
python -m app.cli files copy C:\SHU_DATA\memory\exports\notes.txt C:\SHU_DATA\memory\exports\notes-copy.txt --sha256 SHA256_FROM_PREVIEW --confirm
```

Review both paths and type `YES` to copy. SHU copies up to 64 MiB and compares
the source and staged bytes against the reviewed hash. The copy preserves the
source and requires a destination filesystem that supports hard links, such as
NTFS. Existing destination files are protected.

On a full Windows install, `files move` uses the same digest and confirmation
as copy. It renames the reviewed file to an unused path within the same
approved tree. To undo it, preview the file at its new path and move it back
with a new confirmation. It refuses to overwrite an occupied old path.

## Approved communications

`comms draft` prompts for the recipient and message without putting them in the
shell command history. Preview shows the exact text and its approval digest.
Send needs both that digest and the explicit `--confirm` flag. The WhatsApp
adapter follows Meta's versioned Cloud API `/messages` endpoint and bearer-token
authentication; using it requires a configured WhatsApp Business phone number.
See the [Meta WhatsApp Business Platform docs](https://developers.facebook.com/documentation/business-messaging/whatsapp/overview).
WhatsApp recipient names are resolved only by exact match from SHU's private
local contact book. Duplicate names require a numbered choice; unknown names are
never guessed. The dashboard's Communications tab also manages this contact
book, then provides the same local-draft, exact-preview, and explicit-send-
confirmation flow without attachments. For WhatsApp it can compose either a
text message or a template message; template mode adds accessible fields for
the approved template name, language, comma-separated ordered parameters and
the placeholder body, and the preview shows the rendered text before review. Provider-accepted sends produce a
dashboard status update and a Windows tray notice when the tray is available.

```powershell
python -m app.cli contacts add
python -m app.cli contacts list
python -m app.cli contacts delete CONTACT_ID --confirm-delete
python -m app.cli comms draft --channel whatsapp
python -m app.cli comms preview DRAFT_ID
python -m app.cli comms send DRAFT_ID --digest PREVIEW_DIGEST --confirm
```

WhatsApp templates are also supported. Submit a new template for Meta review,
then draft a reviewed template message with its exact rendered body. Template
text must use numbered placeholders such as `{{1}}`; pass each value in order
with a repeated `--param`. The preview digest binds the template name, language,
parameter values and rendered text, so a send is refused if any of them change
between review and delivery.

```powershell
python -m app.cli comms template-create --name order_ready --language en_US --category UTILITY --body "Hello {{1}}, order {{2}} is ready."
python -m app.cli comms draft-template --recipient CONTACT_OR_NUMBER --name order_ready --language en_US --param Asha --param A-42 --body-template "Hello {{1}}, order {{2}} is ready."
python -m app.cli comms preview DRAFT_ID
python -m app.cli comms send DRAFT_ID --digest PREVIEW_DIGEST --confirm
```

Creating a template needs `SHU_WHATSAPP_BUSINESS_ACCOUNT_ID` and an access
token. Sending an already-approved template needs only the phone number ID and
token. Meta reviews every new template before it can be delivered. If SHU has no
local copy of the template text, pass the exact rendered body with
`--preview-text` instead of `--body-template`.

If SHU cannot confirm that the provider accepted a send or draft save, it
records the outcome as `unknown`. Check the provider before creating another
copy. The original draft stays blocked from replay.

Set `SHU_EMAIL_PROVIDER=gmail` or `outlook` for email and configure the WhatsApp
Business phone number ID, optional business account ID for template creation,
and Graph API version in `.env`. Store the WhatsApp
access token with the hidden-input Credential Manager command below; do not put
the token in `.env` or chat.

For Gmail, enable the Gmail API, create a Desktop OAuth client, keep its JSON
outside the source folder, and set `SHU_GMAIL_OAUTH_CLIENT_SECRETS` to that
path. For Outlook, register a public-client app in Microsoft Entra, enable
device-code sign-in and set its application ID in
`SHU_MICROSOFT_OAUTH_CLIENT_ID`. Then authorize locally:

```powershell
python -m app.cli auth email login --provider gmail
python -m app.cli auth email login --provider outlook
python -m app.cli auth email status --provider gmail
python -m app.cli auth email verify --provider gmail
```

OAuth refresh data is kept in Windows Credential Manager. No access token is
printed. Gmail uses the `gmail.modify` scope; Outlook requests delegated
`User.Read`, `Mail.ReadWrite`, and `Mail.Send`. The login command asks the
provider for consent and does not send a message. The explicit `verify` command
makes a read-only profile request and reports only whether it succeeded; it
does not display or store account details. See Google's [Gmail OAuth
quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python)
and [Gmail scope descriptions](https://developers.google.com/workspace/gmail/api/auth/scopes),
and Microsoft's [MSAL Python token acquisition guide](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens).

With an authorized account, mailbox search, reading, attachment listing and
approval-gated attachment download are available. Messages and attachments are
untrusted external content; SHU does not execute or open downloaded files.

```powershell
python -m app.cli email search --query "newer_than:7d"
python -m app.cli email read MESSAGE_ID
python -m app.cli email reply MESSAGE_ID
python -m app.cli email forward MESSAGE_ID --to recipient@example.com
python -m app.cli email attachments MESSAGE_ID
python -m app.cli email download-attachment MESSAGE_ID ATTACHMENT_ID
```

Reply and forward commands print the untrusted source content, recipient,
message body, forwarded attachment metadata and delivery mode. Type `YES` to
create the reviewed unsent provider draft. With `--send`, type `SEND` to approve
the reviewed direct send. Gmail replies include
the source thread and RFC reply headers, and Gmail forwards carry source files
within SHU's 15 MB limit. Outlook uses its native reply/forward endpoints.
SHU records the approved reply or forward before dispatch and blocks identical
retries after success or an uncertain outcome. If a send or draft attempt is
uncertain, inspect the mailbox to confirm what the provider accepted.

Read a public web page in an isolated Chromium, Chrome, Edge or best-effort
Brave session. Public-page contexts are fresh and cookie-free; the read-only
page reader, tab session and form preparation disable JavaScript and block
requests other than GET/HEAD. The reader blocks local and private network
targets, does not retain downloads, and marks returned page text as untrusted.
Pages that require JavaScript may return incomplete content. Task plans can use the same read-only tool.
With a reviewed task plan, SHU can also fill one uniquely labeled, empty text
field on a public page. That form session has JavaScript disabled and blocks
non-GET/HEAD requests; SHU never submits the form or enters an authenticated
session. Sensitive prompts are routed locally by default.
Task previews show earlier-step dependencies, the tools' required resource
labels, and a rough serial tool-time estimate. After three successful runs of a
tool, SHU uses the median of up to 31 measured durations among its latest 1,000
successful tool runs; before that, it uses the registered default. Only the
tool name and elapsed milliseconds are added to the audit summary; arguments
and results are excluded. Estimates are historical guidance, not a runtime or
completion-time guarantee.

```powershell
python -m app.cli browser read https://example.com
python -m app.cli browser read https://example.com --channel msedge
python -m app.cli browser session --channel chromium
```

Run the synthetic prompt-injection planner probe with:

```powershell
python scripts\redteam_task_planner.py
```

This probe uses only the configured local Qwen model. It drafts plans but never
saves a task or executes a tool; the synthetic cases provide a repeatable
check, not a complete security proof.

`--channel` accepts `chromium` (the Playwright-installed browser), `chrome`,
`msedge`, or `brave`. Chrome and Edge must already be installed for their
channels. Brave is located in standard per-machine or per-user Windows paths
and passed to Playwright as a custom executable; Playwright does not guarantee
compatibility with this non-bundled browser, so this option is best-effort.
The visible tab session supports up to eight temporary tabs with `open URL`,
`goto TAB_ID URL`, `read TAB_ID`, `tabs`, `close TAB_ID`, and `quit`. It disables
JavaScript, cookies and downloads and blocks requests other than GET/HEAD.
Tabs exist only for that session; login and authenticated account workflows are
not available.

Sending remains a separate exact-preview and digest-confirmation workflow. Email
attachments must be in SHU's exports or attachments folder; preview includes
their names, sizes and SHA-256 digests, and each provider has its own size limit.
Use the local draft path and review its recipient, body and attachments before sending:

```powershell
python -m app.cli comms draft --channel email
python -m app.cli comms preview DRAFT_ID
python -m app.cli comms save-provider-draft DRAFT_ID --digest PREVIEW_DIGEST --confirm
python -m app.cli comms send DRAFT_ID --digest PREVIEW_DIGEST --confirm
```

The provider-draft command shows the exact email and attachment preview, checks
the digest and requires typing `YES`. It saves an unsent copy to Gmail or
Outlook and never sends it. Related email actions are handled with dedicated
provider-native commands above.

WhatsApp access tokens may still be entered with hidden input and stored in
Windows Credential Manager:

```powershell
python -m app.cli credentials set whatsapp_cloud_api_access_token
```

No send command is run without reviewing its preview and passing `--confirm`.
Check current delivery state with `python -m app.cli comms status DRAFT_ID`.

## Approved reusable workflows

Save only a fully completed and verified task as a reusable workflow, then
inspect the stored workflows and replay one by its ID. Replay prints the exact
steps, asks for explicit approval, and requests approval again for each
modifying step.

```powershell
python -m app.cli tasks save-workflow TASK_ID --name "Monthly report"
python -m app.cli workflows list
python -m app.cli workflows replay PROCEDURE_ID
```
