# SHU PRD v1.0 Progress Checkpoint

Updated: 2026-11-26 (Asia/Kolkata)

## Goal and current checkpoint

The active goal remains the complete SHU PRD v1.0 across all 19 phases. The
project is **not yet at v1.0 acceptance**. This checkpoint resumes from the
existing implementation and records the newest verified state; it does not
replace the requirement-level evidence in [PRD_TRACEABILITY.md](PRD_TRACEABILITY.md)
or the delivery summary in [STATUS.md](STATUS.md).

The latest full `scripts\verify.ps1` run passed. Its pytest stage passed
**650 tests in 45.62 seconds**. `pip check`, Python compilation, SQLite
integrity (`ok`) and schema version 5 also passed. Doctor passed its core
environment checks. Its remaining warnings are the missing WhatsApp access
token and missing trained `Hey SHU` model.

## GitHub checkpoint on 2026-11-26 (r10c)

- Phase 18. Final `scripts\verify.ps1` passed 650 tests in 45.62 seconds,
  dependency and compile checks, SQLite integrity at schema v5 and Doctor.
  Doctor still warns about the missing WhatsApp token and trained wake model.
- Phases 5 and 18. Restore now opens the source once and validates the staged
  snapshot's SHU columns, integrity and foreign keys. It migrates and checks
  that same snapshot before preserving or replacing the live file. A competing
  or interrupted restore cannot reuse a reserved staging path, and a SQLite
  journal on the destination stops replacement. Legacy v2 restore, missing
  columns, occupied staging, three journal cases and concise CLI errors were
  covered in the 91-test focused restore/dashboard run with isolated databases.
- Phase 7. `scripts\evaluate_wake_word.py` measures hits, misses, false
  activations per hour and inference time on consented labelled WAVs. It shares
  the live listener's threshold and debounce behavior. Fifty focused wake and
  voice tests passed. A bundled generic ONNX model processed 25 blocks of
  synthetic silence with zero observed hits. This only verifies the local
  loader and inference path. The trained Hey SHU model, representative false
  activation rate, live microphone and target CPU acceptance remain open.
- Phases 13 and 17. APScheduler now passes each exact scheduled occurrence to
  one durable SQLite claim before a notifier can run. Competing sessions do not
  replay the same occurrence. A one-time interrupted attempt remains visible
  as **Delivery uncertain**, and Snooze schedules a fresh occurrence. Tests
  simulated competing sessions, a notifier interruption and explicit snooze.
  Initial runs also found two Cancel/Complete cases that kept the uncertain
  flag. Both actions now clear the flag while retaining the audit claim.
  The corrected reminder/dashboard group passed all 160 tests. Delivery to
  the Windows notification surface remains to be verified live.
- Phases 1 and 19. A disposable full Windows setup from the verified r9
  source installed all 25 direct dependencies at their pinned versions and
  passed `pip check` and isolated SQLite integrity at schema v5. Its fresh
  Playwright browser opened an offline page, and the actual dashboard opened
  and closed offscreen. This used the existing Windows account in scratch
  paths. Elevated ACL behavior, shortcuts and a different profile remain to
  be checked for this setup.
- Phase 19. The local r10c ZIP contains 116 allowlisted files and 314,609 bytes.
  SHA-256 is `503a483e87123f96a9a811b7fd9c069c340e3adf141990ab39b2b52fe086789c`.
  Member bytes match the merged checkout. A checksum-verified comparison with
  r10b found only the README title from incoming GitHub commit `ab34d7f`.
  The r10b extraction passed all 650 tests in 48.76 seconds using the fresh
  full Windows setup's venv. Its `pip check` passed. The merged r10c extraction
  initialized and verified a separate schema v5 database with no credentials.

## Earlier GitHub checkpoint on 2026-11-26 (r9)

- Phase 18. Full `scripts\verify.ps1` passed 630 tests in 118.26 seconds,
  dependency and compilation checks, SQLite integrity at schema v5, and Doctor.
  Doctor still reports the missing WhatsApp token and trained wake model.
- The hosted Windows check for source commit `98121b2` stopped before a
  runner started. GitHub again reported an account billing lock.
  [r9 Windows CI](https://github.com/Mr-Sundar-Maity/SHU/actions/runs/45729727797)
- Phases 5 and 17. The dashboard's **Create database backup** action copies
  SQLite on a worker thread and reports the verified snapshot without rotating
  earlier backups. CLI and dashboard share timestamped naming. Each backup has
  its own staged file and passes SQLite integrity verification before publishing.
  A late destination cannot replace another file. Isolated tests covered a
  corrupt source, a late collision, and dashboard backup and restore into a
  separate database with the expected record. The focused database and dashboard
  run passed all 42 tests.
- Phase 9. `files move` adds an approval-bound Windows rename within one
  approved exports tree. SHU checks the previewed SHA-256 on the opened file,
  renames to an unused destination, and verifies the moved object. The
  original path can be restored by reviewing and approving the inverse move.
  A real Windows scratch test covered forward and inverse moves. Automated
  cases covered refusal, content and modification time, and a destination
  created just before the rename. Delete and overwrite remain unavailable.
  Physical recovery after power loss remains untested. [Windows rename flags](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info)
- Phases 11 and 16. Shared communication drafts now require a usable
  provider reference before reporting success. Ambiguous failures record
  `unknown`, block replay of the same draft, and direct the user to inspect
  the provider. The combined fake-provider email, messaging and CLI run passed
  all 93 tests. No live message was sent and no account was accessed.
- Phases 1 and 19. CoreOnly now avoids importing desktop-only document,
  reminder or dashboard dependencies for terminal commands, and creates no
  desktop shortcuts. It rejects `-EnableStartup` before setup. Full setup and
  startup registration check dashboard imports before writing shortcuts.
  Isolated fixture and CLI coverage passed in the 122-test integration run.
  A disposable fresh `install.ps1 -CoreOnly` installed the pinned dependencies
  from PyPI, passed dependency and SQLite checks, and verified the CLI without
  PySide6, Word libraries or APScheduler. `gui` returned the full-setup hint.
- The local r9 ZIP includes 114 allowlisted files and 304,670 bytes. SHA-256 is
  `90ae17140090d7379d92f09226460f1f4dff3a8338b770403851e9c3e4d23dc3`.
  Member bytes match the checkout. Extraction initialized and verified a
  separate schema v5 database without `.env` or a credential directory.
  The extracted source passed all 630 tests in 87.75 seconds with the local venv.

## Earlier GitHub checkpoint on 2026-11-26 (r8)

- Phase 18. Full `scripts\verify.ps1` passed 613 tests in 39.25 seconds,
  dependency and compile checks, SQLite integrity at schema v5 and Doctor.
  Doctor still reports the missing WhatsApp token and trained wake model.
- The hosted Windows check for r8 source commit `99b4255` again ended before
  the runner started. GitHub's annotation reports an account billing lock.
  [r8 Windows CI](https://github.com/Mr-Sundar-Maity/SHU/actions/runs/45690641058)
- Phases 4 and 18. `scripts\benchmark_voice.py` makes the synthetic voice
  latency test repeatable for a consented WAV. It uses cached Whisper and an
  installed loopback Ollama model with a silent speech sink. Three trials of
  the existing English sample all succeeded. The median/p95 to the silent
  handoff was 6.640/10.713 seconds, including the first load. The median file
  read, transcription and Ollama times were 0.472 ms, 4.851 s and 1.789 s.
  The probe did not record, synthesize, play audio or print speech content.
  A separate fixed synthetic Gemini request again returned HTTP 503.
- Phase 6. Memory retrieval now compares complete Unicode-normalized terms
  on both sides. Correction and purge use writer transactions, and expiry
  checks retain subsecond precision. The 39 focused tests passed on isolated
  SQLite, including seven new matching, expiry and concurrent-writer cases.
  Native-language relevance and long-term owner acceptance remain open.
- Phase 9. `files preview` lists size and SHA-256 for a regular file in the
  approved exports directory. `files copy` shows the exact paths and hash,
  requires typed approval, verifies the reviewed bytes and uses exclusive
  publication. A disposable Windows CLI smoke confirmed matching hashes,
  refusal without approval, retention of the source and staging cleanup.
  Copy is limited to 64 MiB and requires hard-link support. Generic move,
  delete and overwrite are outside the current file tool.
- Phases 2 and 17. The dashboard has a separately labelled Voice activity
  line for wake mode, capture, transcription, AI and speech output. The
  recording signal comes from an opened input stream, and mute stays visible
  when a late capture signal arrives. Fixed and dynamic streams were tested
  with local fakes. Actual microphone, speaker and screen reader tests remain open.
- Phase 18. A focused test run that put dashboard tests before barge-in
  aborted in Python. The old r7 extraction reproduced it. Keeping the Qt
  application alive and draining and collecting dashboard objects on the
  main thread after the module allowed two repeats of the exact 82-test order
  to pass. This corrects test teardown. It supplies no live audio evidence.
- Phase 19. Local `dist\SHU_personal_source_2026-11-26_r8.zip` contains 112
  allowlisted files and 296,851 bytes. SHA-256 is
  `e960bacfb0d33aae31bc13552c6b130a2babccd2e0b35fef44c318e61ec9a7f4`.
  Bytes match the checkout and an extraction initialized and verified a
  separate schema v5 database without `.env` or a credential directory.
  All 613 tests also passed there in 39.69 seconds using the local venv.

## Earlier GitHub checkpoint on 2026-11-26 (r7)

- Phase 18. `scripts\verify.ps1` passed 591 tests in 39.32 seconds,
  dependency and compile checks, SQLite integrity at schema v5, and Doctor.
  The remaining Doctor warnings are the WhatsApp token and trained wake model.
- The enabled GitHub workflow created a check for r7 source commit `4494ba8`.
  GitHub again reported an account billing lock before assigning a runner, so
  hosted installation and tests remain unverified. [r7 Windows CI](https://github.com/Mr-Sundar-Maity/SHU/actions/runs/45688064116)
- Phases 4 and 18. Five trials took an existing 1.945-second synthetic
  English WAV through `SHUVoiceAssistant`, cached Whisper small and loopback
  `qwen2.5:1.5b`. All five matched the fixture and produced a nonempty reply at
  the speech handoff. The first turn took 10.501 seconds (5.405 Whisper and
  5.095 Qwen). Four warm turns had a 5.361-second median and 5.879-second p95
  from file input to speech handoff. This probe used a TTS sink, with no
  microphone recording, synthesis or playback. Representative speech, full
  stage timing and the exact 16 GB baseline remain open.
- Phase 13. Daily and weekly recurrence preserves the saved first instant,
  skips later nonexistent local times and fires only once when a later hour
  repeats. A restart between folds does not deliver the same occurrence
  again. The dashboard resolves the Windows IANA zone through Qt, stores the
  editor's exact selected instant and displays each pending reminder in its
  saved zone. An unavailable zone stops scheduling with a clear message.
  The focused dashboard, communications and reminders run passed 174 tests.
  [Qt system time zone API](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTimeZone.html#PySide6.QtCore.QTimeZone.systemTimeZoneId)
- Phase 15. `tasks resume` and `tasks recover` bind the user's typed approval
  to the same reviewed request, plan and checkpoint in SQLite. A task that
  changes during review requires a fresh preview before it can resume or a
  recovery choice can be stored. The 79 focused CLI and task tests passed.
- Phases 16 and 17. Dashboard send and provider-draft confirmations display
  literal message text, recipient and attachment details. They default to No
  and cannot start a provider action after the reviewed draft changes. Tests
  covered both operations with an isolated local draft and no provider calls.
- Phase 19. Local `dist\SHU_personal_source_2026-11-26_r7.zip` contains 110
  allowlisted files and 283,904 bytes. SHA-256 is
  `5140650a40b403db26014e87cb3cb0d72d1cdd67e47249199ee5fa6310ddb3db`.
  Bytes match the checkout. The extracted copy initialized and verified an
  isolated schema v5 database. All 591 tests passed there in 54.84 seconds
  using the existing local venv, with no project `.env` or credential directory.

## Earlier GitHub checkpoint on 2026-11-26 (r6)

- Phase 3. `scripts\evaluate_stt.py` scores consented local WAV corpora with
  cached Whisper. It reports aggregate WER, CER, language detection and the
  live voice confidence rule by language, cohort and mode. The 44 focused
  speech tests passed. A synthetic English clip produced WER/CER `0.0/0.0`
  in auto and forced modes, with one correct auto detection. This is one
  sample. The evaluator reported the other five languages missing. A consented
  six-language corpus and native review are still needed.
  The r6 follow-up rejects absolute, UNC and parent-traversal paths before
  resolving any clip. Seven focused evaluator tests passed for this version.
- Phase 13. Relative durations now use elapsed time even when a DST change
  intervenes. Calendar previews and manual saves reject local times that do
  not exist. Calendar comparisons use UTC through the repeated hour. All
  118 reminder tests passed, including 19 new DST cases. Recurrence on later
  clock transitions and live Windows notification acceptance remain open.
- Phase 15. Task recovery uses persisted in-flight state even when the old
  checkpoint says cancelled. A subprocess crash after a resumed step's side
  effect now requires review. A concurrent resume also fails if its verified
  checkpoint advanced while it was waiting. All 48 focused task/database
  tests passed with isolated SQLite. Physical power-loss testing remains open.
- Phases 18 and 19. Full `scripts\verify.ps1` passed 573 tests in 51.27
  seconds, compilation, dependency checks, live SQLite integrity at schema v5
  and Doctor. Doctor still reports the missing WhatsApp token and wake model.
  The Windows CI workflow installs both manifests in a fresh Python 3.11 venv
  and runs tests with an isolated database. Two ACL fixtures now select their
  test checkout explicitly. A clean r4 Git archive with those fixes replayed
  all 545 r4 tests using the local venv. Hosted runs are tracked under GitHub Actions.
- The first hosted Windows CI run for `387b54b` ended before runner allocation
  and executed zero steps. GitHub's check annotation attributes the failure to
  an account billing lock. Hosted clean installation and test results remain
  pending until the account can start a job. [Windows CI run 45685254990](https://github.com/Mr-Sundar-Maity/SHU/actions/runs/45685254990)
- The local r6 source ZIP has 110 entries and 279,744 bytes. SHA-256 is
  `8b4b05ec5fec6b105306b62d30fbb2ee827a69f628dca5f58cc1ef951dc10252`.
  It matches the package allowlist. The extracted copy initialized and
  verified a separate schema v5 database. The clean r6 extraction also passed
  all 573 tests in 36.30 seconds using the existing local venv, without a
  project `.env` or credential directory. GitHub carries the CI workflow and
  documentation alongside the application source.

## Earlier GitHub checkpoint on 2026-11-26 (r4)

- Phase 18. `scripts\verify.ps1` passed all 545 tests, dependency and
  compilation checks, SQLite integrity at schema v5, and Doctor. The two
  Doctor warnings are the missing WhatsApp token and custom wake model.
- Phase 16. Outlook native replies now create a draft with one reviewed To
  address and empty Cc and Bcc. SHU checks the returned envelope, applies a
  correction when Graph supplies different defaults, and checks the corrected
  draft before a confirmed send. The 51 focused email tests used mock
  providers and passed. Live Outlook authorization, routing and delivery
  still need acceptance. A provider side change between verification and send
  is outside this check.
- Phase 17. Dashboard shutdown now stops new work, requests emergency stop
  once and lets Qt workers finish while the window still responds. Late worker
  results open no dialogs. Notifications already queued can appear visually
  with speech suppressed. Already dispatched provider calls retain their normal
  timeouts. The 24 offscreen tests passed, including two running Qt workers.
- Phase 19. Local `dist\SHU_personal_source_2026-11-26_r4.zip` has 108 entries
  and 272,545 bytes. Its SHA-256 is
  `32c51ee175c2bf5f542f966e1263b0f612ff3ab3924305dee2467d56e5875c1d`.
  ZIP contents match the final checkout's package allowlist. An extracted copy
  initialized and verified an isolated schema v5 database. The earlier r3 ZIP
  was built before the last dashboard edit and was superseded by r4.
- The GitHub destination is `Mr-Sundar-Maity/SHU`, branch `main`. The initial
  remote commit is the parent for the project snapshot. Publish source, tests,
  setup scripts and these Markdown notes. The repository ignores credentials,
  databases, local outputs and diagnostic files. This checkpoint records the
  software evidence and the remaining personal-use acceptance work.

## Earlier continuation on 2026-11-26 (r2)

- Phase 18. The full `scripts\verify.ps1` run finished with 537 passing tests
  in 37.08 seconds. Dependency, compilation, live SQLite integrity/schema and
  Doctor checks passed. Earlier sandbox attempts hit permission errors for
  bytecode, the application log and Playwright. The final run used writable
  temporary paths and ordinary Windows account access. Doctor's two warnings
  remain the missing WhatsApp token and trained Hey SHU model.
- Phases 7 and 17. Dashboard Emergency stop now targets the current voice
  assistant. Finished sessions can release their audio engines and Whisper
  model. The transcript preserves literal text and line breaks, including
  text that looks like a link or image tag. Offscreen regressions cover both.
- Phase 13. Daily and weekly reminders retain their first scheduled date,
  timezone and second. Stale jobs skip delivery after a reschedule. An active
  notifier can finish without overwriting a concurrent cancel, completion or
  snooze. Quiet mode uses a thread safe state and the dashboard checks it
  again before starting speech. The 99 reminder tests and the offscreen
  queued notification regression passed.
- Phases 6 and 8. Creating or correcting memory rejects known authentication
  formats and common password assignments in the six supported languages.
  Approved local contact and health notes still work. The 66 focused tests
  checked creation, correction, retention, retrieval, privacy and learning.
  The existing memory database was not scanned for credential content.
- Phase 16. Reply and forward previews bind the recipient, subject and
  delivery mode to the approval digest. CLI users see whether the action saves
  an unsent provider draft or sends the message. A changed mode or field is
  rejected before a provider write. The 78 focused email, communications and
  CLI tests used test providers. Outlook native reply routing and end to end
  Gmail reply, forward and send still need live acceptance.
- Phase 19. Built `dist\SHU_personal_source_2026-11-26_r2.zip` with 108
  allowlisted entries and 270,587 bytes. SHA-256 is
  `1ff2fddffd5dfa732261cb0cceb47464dddb2c7d8eb4488316c538d9dcc36063`.
  Verified checksum, member bytes against the checkout, path and private file
  checks, ZIP CRCs and Python syntax. Database initialization and verification
  from the extracted copy passed at schema v5 with isolated temporary data.

## Earlier continuation on 2026-11-26 (r1)

- PRD audit: re-read and visually checked the Version 1.0 Definition of Done and Immediate Development Plan. Closed two local gaps: CLI `/reset`/`/clear` and an accessible dashboard control clear only temporary conversation context while retaining approved memories; dashboard Ready is idle and does not start microphone capture or wake-word inference until the user explicitly starts a voice session.
- Focused reset/idle regressions passed. Full verification passed **506 tests in 32.19 seconds**, `pip check`, compilation, SQLite integrity (`ok`), schema v5 and Doctor core checks. Doctor warns only about the missing WhatsApp access token and trained `Hey SHU` model.
- One initial full-verification attempt aborted while creating an APScheduler thread with less than 700 MiB available RAM. The idle-only test now uses a no-op reminder service; retrying the full verification completed. No external Python process was stopped.
- Built `dist\SHU_personal_source_2026-11-26_r1.zip`: 108 allowlisted entries, 267,812 bytes, SHA-256 `43ddc48c88a2476526a873f0a65d3edee1b714843c642d6aa891f7716f072ed4`; private-member check returned zero. ZIP checks passed, and extracted-copy database init/verify passed at schema v5 in isolated temporary data.
- Resume audit: re-read the progress, delivery-status and PRD-traceability notes before continuing. Both phase matrices contain all 19 phases with valid column counts; the current test count, bundle path, size and SHA-256 agree. Temporary PRD text/render artifacts remain under `tmp\prd_audit_2026-11-25.txt` and `tmp\prd_audit_pages` because the cleanup command was blocked; `tmp\pdfs` and source bundles were left untouched.
- Gemini recheck: one direct, non-sensitive generation ping with a 10-second request timeout returned HTTP 503. No response content or credential was printed; cloud-generation acceptance remains open.

- PRD resource-observability gap closed in `scripts\benchmark_local_ai.py`: sample and soak reports include Ollama API load/server/prompt/generation durations, installed model footprint, SHU data-volume free space, round-trip p95, CPU and RAM. Output contains response lengths only. The focused benchmark suite passes all 15 tests.
- Post-queue live Qwen sample: installed model size 940.4 MiB; one cold round trip took 7.146 s (server model load 3.896 s, server total 5.096 s); minimum available RAM was 4,682.7 MiB and peak system memory load 76%. A post-queue 10-second soak completed 3/3 requests with no failures (median/p95 2.622/2.989 s), minimum available RAM 4,276.8 MiB and peak system memory load 78%; response text was not emitted.
- A shared FIFO CPU-work queue now serializes local Ollama inference and Whisper transcription, with bounded waits and stop-event cancellation for transcription still waiting. Queue, AI, STT, voice and benchmark regressions passed in the focused 101-test suite.
- At the preceding 2026-11-25 checkpoint, verification passed 501 tests in 88.58 seconds and r16 was built with 108 entries, 266,462 bytes, SHA-256 `5599f80254538d55b450eb2cf29b9748709a01ffde819ea2325ae16e711a4508`; its archive and extracted-copy schema-v5 database checks passed.
- PRD Section 4.3 performance evidence now includes p95 latency. `benchmark_local_ai.py` reports inclusive, linearly interpolated p95 in both short runs and soak reports; focused regressions pass for empty/single samples, interpolation and invalid percentile bounds. Recomputing the archived 60 successful request timings gives p95 2.921 s (median 2.666 s, maximum 3.093 s).
- Current host check: Windows 11 Home, a 12th-generation Intel Core i5 and 19.7 GiB installed RAM. OS/CPU family match the PRD target; installed memory exceeds its 16 GB assumption, so these measurements do not establish headroom on an exact 16 GB configuration. A fresh 3-request local-Qwen smoke measured 6.897/2.529/2.564 s, median 2.564 s, p95 6.464 s, with peak memory load 71%.
- Voice task handoff: the dashboard stores the latest recognized request, enables an accessible planner button only after the voice session stops, and previews the original utterance plus exact tool steps. A focused offscreen GUI test confirms the No choice leaves the task queue empty and preserves existing chat input.
- Response-style controls now support friendly (default), casual, formal, serious, humorous and supportive modes in dashboard chat, CLI chat and voice AI. `.env` validates `SHU_RESPONSE_STYLE`; Dashboard Settings applies a session override. Focused configuration/dashboard/CLI/voice/provider tests passed (137 tests), and the latest full verification includes these changes. The style affects response wording only; task approvals and safety instructions stay in force.

- Added ten reminder regressions for schedule-first daily and weekly phrases
  with recognized reminder endings in Bengali, Hindi, Tamil, Telugu and
  Malayalam. The focused reminder suite passes all 93 tests. An isolated
  temporary database smoke also persisted all ten phrases with the expected
  reminder text and recurrence; no scheduler or notification was started.
- At the preceding checkpoint, full verification passed 488 tests in 67.55 seconds, `pip check`,
  Python compilation, database integrity/schema version 5, and Doctor's core
  checks. Doctor's only warnings are the missing WhatsApp API access token and
  trained `Hey SHU` model. It detected 12 microphone inputs and a valid
  configured index; the owner-deferred spoken test remains open.
- Built `dist\SHU_personal_source_2026-11-25_r12.zip` with 106 entries and
  258,904 bytes. SHA-256:
  `51b909bc389ece48c2ad67bbfb759e61ef3a823798ea435585bbd641e2e63b6a`.
  Archive checks passed, and an isolated extracted-copy database init/verify
  passed with schema version 5.
- The one-hour local-Qwen soak completed its full 3,600-second target. All 60
  requests succeeded with no failures; the model was resident before and after.
  Median/p95/max latency was 2.666/2.921/3.093 s. Available RAM ranged from
  3,834.0 MiB at start to a 2,774.2 MiB minimum and 3,936.9 MiB at end, with
  peak memory load of 86%. Whole-system CPU median/peak was 34.8%/82.2%. The
  response text was not emitted and stderr is empty.

- Phase 15 live-safe planning smoke: local Qwen drafted one read-only `list_windows` plan; strict validation, isolated SQLite persistence, FIFO queue listing and preview/estimate all passed. Cloud AI and automation were disabled; the executor and desktop handler were not called. The temporary DB passed integrity and schema-v5 verification.
- Phase 15 target execution smoke: a separately validated read-only `list_windows` step ran through the actual Windows handler in an isolated schema-v5 database; the task completed and the FIFO queue emptied. Automation was enabled only for this isolated process. Window titles and the handler result were suppressed, no AI request was made, and the project database was not touched. The first diagnostic used global Python without project dependencies; rerunning with `.venv` passed.

- Phase 15 retry hardening: `ToolSpec.retry_limit` is bounded to two and can be enabled only for registered read-only tools. The planner derives retry metadata from that registry policy; the public-page GET tool retries classified transient network failures and HTTP 408/425/429/5xx with 0.5 s then 1.0 s backoff. Permanent failures are not retried, modifying tools cannot opt in, and the emergency stop interrupts the wait. Focused retry/browser/emergency-stop tests pass (81 tests); README documents the policy.
- At the preceding checkpoint, `scripts\verify.ps1` passed 488 tests in 67.55 seconds, `pip check`, Python compilation, database integrity/schema v5, and Doctor core checks. Doctor's only warnings are the missing WhatsApp API access token and trained `Hey SHU` model. The first Doctor run found Ollama stopped; a hidden `ollama serve` restart restored the local `qwen2.5:1.5b` endpoint. The model was confirmed present and one local inference succeeded with response text suppressed; the final full verification reported Ollama PASS.

- PRD Section 9.2 asks the planner to estimate time and resource needs where possible. The planner provides per-step registered resource requirements and a task-level union; these labels identify required capabilities and are not a live CPU/RAM capacity forecast.

## Work completed at this checkpoint

- Gemini-to-local recovery: `SHU_LOCAL_FALLBACK=true` is the default when
  Gemini is selected; local-to-Gemini fallback remains opt-in and disabled by
  default. A live, non-sensitive Gemini request returned HTTP 503, then the
  Qwen local fallback returned a nonempty result. Response content and provider
  secrets were suppressed. Unit tests cover fallback success, opt-out, clear
  failure status and error redaction.
- Voice controls: TTS now supports playback pause/resume, adjustable playback
  volume from 0% to 100%, and speech rate from -50% to +50%. The dashboard has
  accessible controls. Rate and volume apply to the next voice session, while
  dashboard text size can be adjusted immediately from 8 to 24 points. A
  regression verifies playback stays paused until resumed.
- The settings defaults are `SHU_TTS_RATE_PERCENT=0` and
  `SHU_TTS_VOLUME=1.0`; environment values are range-validated.
- Independent privacy controls: the dashboard can mute microphone capture,
  force Google-selected AI requests through local Ollama, and disable cloud AI
  calls/fallback. A separate automation switch blocks registered desktop and
  browser actions in the registry and leaves queued tasks untouched. Startup
  defaults are `SHU_CLOUD_AI_ENABLED` and `SHU_AUTOMATION_ENABLED`; dashboard
  choices apply to the current session. An already-running tool can finish, so
  Emergency stop remains the control for stopping active work.
- Task duration estimates now use the median of up to 31 timings from the
  latest 1,000 successful tool runs after three samples. Audit summaries store
  only the tool name and elapsed milliseconds for this estimate; arguments and
  results are excluded. Resource tags are declared per tool and aggregated into task previews; they describe required capabilities, not live host-capacity predictions.
- Reminder parsing now handles explicit English dayparts, noon/midday/midnight,
  and bounded schedule-first forms such as “tomorrow at 9 AM to call mom” and
  “daily at 8 AM to take medicine.” Bengali, Hindi, Tamil, Telugu and Malayalam
  schedule-first forms are also supported when they end in a recognized
  reminder cue. Unknown endings, conflicting dayparts and empty task names are
  rejected. The focused reminder suite passes all 93 tests; ten new cases
  cover localized daily/weekly schedule-first recurrence. Live Windows
  notification/audio and owner-side spoken acceptance remain open.
- Earlier verification after adding the soak harness passed 451 tests in 98.99 s. Dependency check, compilation, database integrity/
  schema verification and doctor also completed successfully. Doctor still
  warns about the missing WhatsApp token and trained wake-word model.
- Phase 18 now has a repeatable `benchmark_local_ai.py --soak-seconds ...`
  mode. It queries only loopback Ollama with a fixed benign prompt, omits
  response text, records median/p95/max latency/whole-system CPU/available memory, stops after
  three consecutive request failures, and aborts below 2 GiB available RAM. A
  10-second live smoke completed 2/2 requests (8.485 s cold, 2.783 s next);
  available RAM was 5,241.5 to 4,059.8 MiB and peak memory load was 79%. The
  one-hour run at 60-second intervals completed 3,600 seconds.
  Its JSON report is in `tmp\local_ai_soak_2026-11-25_r1\stdout.jsonl`; all 60
  requests succeeded, no failures occurred, and `stderr.log` is empty. Median
  median/p95/max latency was 2.666/2.921/3.093 s. Available RAM ranged 3,834.0/2,774.2/3,936.9
  3,936.9 MiB (start/minimum/end), reaching 86% system-memory load; whole-system
  CPU median/peak was 34.8%/82.2%. The model remained resident.
- Expanded `scripts\redteam_task_planner.py`, a local-only, non-persisting
  planner probe. Three earlier 10-case runs and one 20-case expanded run
  rejected 50 draft attempts; a fifth 30-case run rejected all 30 as InvalidPlan,
  left task count unchanged and ran no executor or tool handler. The expanded
  corpus now covers screenshot OCR, tool results, attachments, claimed consent,
  Bengali/Hindi/Tamil/Telugu/Malayalam text, hidden HTML, PDF metadata, calendar
  descriptions, role spoofing, nested quotes, voice transcripts, encoded
  payloads, code comments, zero-width Unicode, HTML attributes, Markdown/YAML
  metadata, filenames, accessibility labels, fake approval tokens and multi-step
  exfiltration requests. A regression protects the 30-case corpus. Broader
  threat-model and other-target/model acceptance remains; dry runs do not prove
  injection resistance.
- Earlier built `dist\SHU_personal_source_2026-11-25_r12.zip` with 106 entries
  (258,904 bytes), including the expanded prompt-injection corpus and its
  regression test. Its verified sidecar SHA-256 is
  `51b909bc389ece48c2ad67bbfb759e61ef3a823798ea435585bbd641e2e63b6a`; earlier
  bundles were preserved.
  archive CRC, paths and Python syntax pass. `.env`, credentials, databases,
  models, user data and internal progress docs are absent. An extracted-copy
  `db init` and `db verify` smoke passed with temporary isolated data. The source ZIP
  is unsigned; package allowlist/CRC/Python syntax checks and an extracted-copy
  database init/verify smoke passed at schema v5; packaging tests pass.
- Gmail OAuth was live-verified after consent: token refresh, profile access and
  read-only inbox search succeeded with account data suppressed.
- Current project evidence includes tested Office COM create/revise/export,
  SQLite backup/restore, task recovery, emergency stop, browser safety and
  local AI privacy routing. See the traceability matrix for exact evidence.

## Phase-by-phase status

| Phase | Current status | Remaining acceptance work |
|---|---|---|
| 1. Foundation | Current checkout verified on Windows 11 Home Single Language with Python 3.11. CoreOnly now avoids desktop imports for core CLI operations and leaves shortcuts alone, verified with desktop modules withheld. A separate fresh full Windows venv installed all 25 direct pins and verified managed Chromium, SQLite and dashboard imports. | Validate a clean Windows profile and measure against the PRD's exact 16 GB RAM baseline. |
| 2. Voice baseline | Prototype; controls and simulated paths pass. Voice activity now shows an opened microphone stream separately from transcription, AI and speech output. | Owner-run microphone/speaker test, repeated capture, barge-in threshold and echo acceptance. The owner deferred spoken testing; the prior short capture was near-silent. |
| 3. Multilingual | Partial; forced/detected paths exist. Offline WAV evaluation reports grouped WER, CER and auto detection behavior. It passed a single synthetic English smoke with cached Whisper. | Consented native-speaker test sets for all six languages, measured thresholds, code-switching and noise/accent validation. Synthetic results did not meet quality acceptance. |
| 4. AI providers | Local Qwen path and shared FIFO inference gate work; Gemini failover is implemented. Five synthetic file-input trials passed with local Whisper and Qwen. Four warm trials reached the speech handoff in 5.361 seconds median and 5.879 seconds p95. Repeatable synthetic WAV benchmark passed 3/3 with cached Whisper and local Qwen to a silent sink. A separate direct Gemini probe returned HTTP 503. | Gemini generation itself is currently unreliable with HTTP 503; local fallback works. Complete provider and voice-to-answer acceptance when the cloud service responds. |
| 5. Memory foundation | Verified subsystem; schema v5 and restore checks pass. SQLite snapshots stage separately, pass integrity verification before publication and preserve late destinations. Dashboard backup restored a seeded record into a separate database. Restore validates and migrates the same staged snapshot, guards the staging path against another restore and rejects destination journals before replacement. | Restore and verify ACL/environment on another Windows profile. |
| 6. Memory intelligence | Implemented with approvals, provenance, retrieval and deletion controls. New memory records and corrections reject known credential formats and common password assignments in all six supported languages. Retrieval matches complete Unicode-normalized words. Correction and purge serialize against retention changes and use precise expiry checks. | Improve heuristic conflict matching only with measured need; complete owner-side persistence and real-session acceptance. |
| 7. Conversation | Continuous loop, cancellation, mute and explicit context reset exist; dashboard Ready is idle and starts no audio/wake listener until the user chooses Start listening. Dashboard stop targets the active voice session and releases its reference when the session finishes. The offline evaluator shares live ONNX threshold and debounce rules. A generic model passed the synthetic wiring smoke. | A trained `Hey SHU` model, false-trigger/CPU measurements and live wake/mute acceptance are still absent. |
| 8. Security | Allowlist, approvals, audit, credentials, independent automation disable and stop controls implemented | Press the global hotkey during a live dashboard task and complete the target-user stop acceptance. |
| 9. Desktop automation | Allowlisted/UIA/OCR paths and synthetic checks pass. A live isolated Windows CLI smoke verified approval-gated copy of reviewed bytes to an unused export path without showing file contents. Windows file moves now bind to the approved SHA-256 and an unused path in the same export tree. An isolated forward and inverse move passed. | Validate real target-application workflows, field entry and screen OCR quality. Generic delete and overwrite are unavailable. |
| 10. Browser | Safe reader, tabs and non-submitting form preparation implemented; four earlier local-Qwen dry-runs rejected 50 attempts; a fifth 30-case local-only probe rejected all 30 as InvalidPlan with no persistence or execution | Broader threat-model coverage, other-target/model acceptance and a user-reviewed authenticated workflow remain; repeated local dry runs do not prove injection resistance. |
| 11. WhatsApp | Contact book, exact preview and digest-confirmed send path implemented. When the provider result cannot establish acceptance, the shared draft records unknown and blocks the same draft from replay. | Store the token locally in Windows Credential Manager, confirm recipient consent and test live delivery. No token is stored; do not paste one into chat. |
| 12. Office | Verified subsystem | No open gap for the phase exit check; retain the current Office smoke evidence. |
| 13. Reminders | Persistence, recurrence, recovery and quiet-mode controls implemented; parser accepts bounded English schedule-first forms and localized Bengali/Hindi/Tamil/Telugu/Malayalam schedule-first forms with recognized reminder endings; ten regressions cover localized schedule-first daily/weekly recurrence; conflicting, vague and empty reminders are rejected. Daily and weekly recurrence preserves the first date and second. Stale scheduler jobs are skipped and a notifier cannot overwrite a later cancel, completion or snooze. The queued dashboard notification rechecks Quiet mode before speech. Relative durations follow elapsed time across DST. Calendar previews and manual saves reject nonexistent local times, with 19 DST regressions. Daily and weekly jobs skip future DST gaps and fire once at repeated times. The dashboard uses the Windows system zone and shows the saved zone offset. An exact scheduled occurrence is claimed in SQLite before delivery. Interrupted one-time attempts stay visible as uncertain and are not replayed. | Additional colloquial forms and live Windows notification/audio behavior, including quiet-mode behavior, still need acceptance. |
| 14. Learning | Approval-gated preferences and version-bound workflow replay implemented | Complete target desktop accessibility and longer-term owner acceptance. |
| 15. Task planner | Validation, FIFO queue, checkpoints, approval binding and crash recovery implemented; duration estimates use measured medians after three successful samples; registered read-only tools can use up to two transient-only retries with exponential backoff and an interruptible emergency-stop wait; local-Qwen plan-to-isolated-queue/preview smoke passed with cloud and automation disabled; isolated read-only `list_windows` target execution completed and drained the FIFO queue, with titles/results suppressed; focused retry/browser/stop suite passes 81 tests. Crash recovery prioritizes persisted in-flight state and resume claims bind the verified checkpoint. Subprocess and concurrent resume regressions pass. Resume and recovery approvals now bind the complete reviewed snapshot to the SQLite write. | Registered resource labels identify required tool capabilities and aggregate per task; they do not claim live CPU/RAM capacity. Modifying target-app workflows and physical power-loss recovery remain. |
| 16. Email | Gmail OAuth, search/read and confirmed draft/send paths implemented. CLI reply and forward approvals bind the recipient, subject and delivery mode. Changes are rejected before a provider write. Outlook reply tests check one reviewed To address and empty Cc/Bcc on the returned draft before send. Dashboard send and provider-draft dialogs display literal text and attachment details and decline stale approval. Provider-draft saves and direct sends now require a usable provider reference and block replay of uncertain actions. | Broader Gmail reply/forward/attachment/send acceptance; Outlook registration/consent remains unverified. The verified draft routing still requires a live Outlook acceptance check. |
| 17. Dashboard | Voice, task, memory, reminder, communication, Cloud AI and automation controls implemented, including six response-style modes and a post-session voice request planner handoff with exact-step preview and approval; dashboard text size is adjustable from 8–24 points. The conversation transcript displays literal text and line breaks. Voice stop and queued Quiet mode have offscreen regression coverage. Offscreen shutdown tests confirm responsive closing with two active Qt workers and no new work. Offscreen tests verify time zone persistence and exact, plain-text communication confirmations. A labelled Voice activity line distinguishes capture, processing and speech output and preserves the mute indicator. The SHU menu can create a verified SQLite backup on a worker thread without rotating earlier backups. The reminder list surfaces uncertain delivery separately from pending and permits explicit rescheduling. | Target-desktop keyboard/screen-reader acceptance and full interactive/provider acceptance remain. |
| 18. Hardening | Latest full verification: 650 tests in 45.62 seconds; dependency, compile, database and Doctor checks pass; local Qwen benchmark/soak reports Ollama timings, model footprint, SHU data-volume free space, CPU/RAM and latency; a FIFO gate prevents Ollama and Whisper CPU overlap | Target-device RAM headroom, full hardware voice path, wake-word acceptance, complete threat-model run and physical power-loss test remain. |
| 19. Release | Setup/startup/recovery tooling, verified 2026-11-26 r10c personal source ZIP and extracted-copy schema-5 database CLI smoke exist. GitHub Windows CI installs pinned dependencies and runs offline tests with a separate database. See GitHub Actions for hosted execution. A full disposable setup from the prior release used fresh PyPI packages and launched an isolated managed browser and offscreen dashboard on this host. | A signed binary installer, another-profile/machine acceptance and future redistribution/license review remain. |

## External and hardware prerequisites

- **Microphone:** a valid input-device index is detected, but the spoken test is
  deferred by the owner. Do not infer microphone acceptance from enumeration.
- **Wake word:** no trained `Hey SHU` ONNX model is available. Keep wake-word
  acceptance pending until one is supplied or trained.
- **WhatsApp:** business phone number ID is configured, but the access token is
  absent from Windows Credential Manager. Store it only with SHU's hidden-input
  CLI credential command; never place it in chat or logs.
- **Gmail:** consent and read-only live verification are complete; broader
  mailbox workflow tests still need a reviewed test account/action.
- **Gemini:** the configured model is listed by Google's model documentation,
  but current generation returned 503. Do not treat that provider outage as a
  successful cloud-generation acceptance.
- **Licensing:** personal use only is selected. Choose and review a license and
  Qt/vendor terms before distributing SHU.

## Resume point

Resume from the r10c software checkpoint and compare the working tree with
`origin/main`. Continue with the acceptance items in the phase rows and publish
verified source and progress updates to the same branch. Rerun Windows CI after
GitHub restores runner access. Live checks still
need owner audio and consented six-language speech, the custom wake model,
WhatsApp setup and recipient consent, reviewed Gmail actions and Outlook
authorization. The phase rows also track target accessibility, recovery and
release checks. Keep existing bundles, private user data and the one-hour soak
report in the local workspace.
