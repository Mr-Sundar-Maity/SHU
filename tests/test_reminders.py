from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.notifications.reminders import ReminderService, parse_natural_reminder
from database.database import Database


def test_reminders_persist_and_can_be_snoozed_or_cancelled(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    reminder_id = service.create("Take a break", due)

    reminder = service.list_pending()[0]
    assert reminder["reminder_id"] == reminder_id
    assert reminder["text"] == "Take a break"
    service.snooze(reminder_id, minutes=5)
    service.cancel(reminder_id)
    assert service.list_pending() == []


def test_overdue_reminder_requires_explicit_recovery_decision(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    reminder_id = service.create(
        "Old reminder",
        datetime.now(timezone.utc) - timedelta(minutes=3),
    )

    overdue = service.start()
    assert [row["reminder_id"] for row in overdue] == [reminder_id]
    service.confirm_overdue(reminder_id, still_relevant=False)
    assert service.list_pending() == []
    service.shutdown()


@pytest.mark.parametrize("still_relevant", [False, True])
def test_overdue_review_rejects_a_new_due_time(tmp_path, monkeypatch, still_relevant):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    other = ReminderService(Database(database.path))
    reminder_id = service.create("Reviewed", datetime.now(timezone.utc) - timedelta(days=1))
    service.scheduler.start(paused=True)
    try:
        reviewed, = service.start()
        other.snooze(reminder_id, 10)
        new_due_at = other.list_pending()[0]["due_at"]

        class AfterSnooze(datetime):
            @classmethod
            def now(cls, tz=None):
                return super().now(tz) + timedelta(minutes=11)

        # The modal can stay open until the snoozed occurrence is also overdue.
        monkeypatch.setattr("app.notifications.reminders.datetime", AfterSnooze)
        with pytest.raises(ValueError, match="schedule changed"):
            service.confirm_overdue(
                reminder_id, still_relevant=still_relevant, expected_due_at=reviewed["due_at"],
            )
        assert service.list_pending()[0]["due_at"] == new_due_at
        assert service.scheduler.get_jobs() == []
    finally:
        service.shutdown()


def test_overdue_decision_cannot_dismiss_an_inflight_delivery(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    other = ReminderService(Database(database.path))
    reminder_id = other.create("Reviewed", datetime.now(timezone.utc) - timedelta(days=1))
    reviewed, = other.list_pending()
    attempts = []

    def notify(*_args):
        attempts.append(reminder_id)
        with pytest.raises(ValueError, match="already has a delivery attempt"):
            other.confirm_overdue(reminder_id, still_relevant=False, expected_due_at=reviewed["due_at"])
        return "displayed"

    service = ReminderService(database, notifier=notify)
    service._deliver(reminder_id, reviewed["due_at"])
    assert attempts == [reminder_id]
    with database.connect() as connection:
        status, result = connection.execute(
            "SELECT status,result FROM reminders WHERE reminder_id=?", (reminder_id,),
        ).fetchone()
    assert (status, result) == ("delivered", "displayed")


def test_late_overdue_recovery_job_preserves_a_new_snooze(tmp_path, monkeypatch):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    calls = []
    service = ReminderService(database, notifier=lambda *args: calls.append(args))
    reminder_id = service.create("Reviewed", datetime.now(timezone.utc) - timedelta(days=1))
    service.scheduler.start(paused=True)
    try:
        reviewed, = service.start()
        original_add_job = service.scheduler.add_job

        def add_after_snooze(*args, **kwargs):
            monkeypatch.setattr(service.scheduler, "add_job", original_add_job)
            service.snooze(reminder_id, 10)
            return original_add_job(*args, **kwargs)

        monkeypatch.setattr(service.scheduler, "add_job", add_after_snooze)
        service.confirm_overdue(reminder_id, still_relevant=True, expected_due_at=reviewed["due_at"])
        jobs = service.scheduler.get_jobs()
        assert len(jobs) == 2
        recovery_job, = (job for job in jobs if job.id != reminder_id)
        recovery_job.func(*recovery_job.args)
        assert not calls
        new_due_at = service.list_pending()[0]["due_at"]
        assert new_due_at != reviewed["due_at"]
        assert service.scheduler.get_job(reminder_id).next_run_time == datetime.fromisoformat(new_due_at)
    finally:
        service.shutdown()


@pytest.mark.parametrize(("recurrence", "days_back"), [("daily", 2), ("weekly", 14)])
def test_recurring_reminders_resume_at_the_next_future_occurrence_after_restart(
    tmp_path, recurrence, days_back
):
    from zoneinfo import ZoneInfo

    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    due = datetime.now(ZoneInfo("Asia/Kolkata")) - timedelta(days=days_back)
    reminder_id = service.create(
        "Recurring reminder",
        due,
        timezone_name="Asia/Kolkata",
        recurrence=recurrence,
    )

    try:
        overdue = service.start()
        job = service.scheduler.get_job(reminder_id)

        assert overdue == []
        assert job is not None
        assert job.next_run_time > datetime.now(timezone.utc)
        interval = timedelta(days=1 if recurrence == "daily" else 7)
        assert job.trigger.get_next_fire_time(job.next_run_time, job.next_run_time) == (
            job.next_run_time + interval
        )

        # Even if a caller explicitly reviews a recurring item, it resumes
        # its recurrence instead of becoming a one-shot immediate job.
        service.confirm_overdue(reminder_id, still_relevant=True)
        resumed = service.scheduler.get_job(reminder_id)
        assert resumed is not None
        assert resumed.next_run_time > datetime.now(timezone.utc)
        assert resumed.trigger.get_next_fire_time(resumed.next_run_time, resumed.next_run_time) == (
            resumed.next_run_time + interval
        )
    finally:
        service.shutdown()


@pytest.mark.parametrize("recurrence", ["daily", "weekly"])
def test_recurrence_respects_the_stored_first_occurrence(tmp_path, recurrence):
    from zoneinfo import ZoneInfo

    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    due = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=10)).replace(
        second=37, microsecond=0
    )
    reminder_id = service.create("Future recurring reminder", due, recurrence=recurrence)

    try:
        service.start()

        job = service.scheduler.get_job(reminder_id)
        assert job is not None
        assert job.next_run_time == due
    finally:
        service.shutdown()


@pytest.mark.parametrize(("recurrence", "days"), [("daily", 1), ("weekly", 7)])
def test_recurrence_delivers_once_in_a_repeated_dst_hour(tmp_path, recurrence, days):
    zone = ZoneInfo("America/New_York")
    repeated = datetime(2026, 11, 1, 1, 30, 37, tzinfo=zone)
    first = repeated - timedelta(days=days)
    following = (repeated + timedelta(days=days)).astimezone(timezone.utc)
    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    reminder_id = service.create("Recurring reminder", first, timezone_name=zone.key, recurrence=recurrence)
    service._schedule(reminder_id)
    trigger = service.scheduler.get_job(reminder_id).trigger

    # When already running, the scheduler must still see the first fold as a
    # possible misfire even if its polling resumes during the second fold.
    first_fold = trigger.get_next_fire_time(first, repeated.replace(fold=1))
    assert first_fold.astimezone(timezone.utc) == repeated.astimezone(timezone.utc)
    assert trigger.get_next_fire_time(first_fold, first_fold) == following
    # Restart between the two occurrences. The default first fold is already past.
    restarted_at = repeated.replace(minute=15, fold=1)
    assert trigger.get_next_fire_time(None, restarted_at) == following


@pytest.mark.parametrize(("recurrence", "days"), [("daily", 1), ("weekly", 7)])
def test_recurrence_skips_nonexistent_dst_time_without_shifting(tmp_path, recurrence, days):
    zone = ZoneInfo("America/New_York")
    gap = datetime(2026, 3, 8, 2, 30, 37, tzinfo=zone)
    first = gap - timedelta(days=days)
    following = (gap + timedelta(days=days)).astimezone(timezone.utc)
    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    reminder_id = service.create("Recurring reminder", first, timezone_name=zone.key, recurrence=recurrence)
    service._schedule(reminder_id)
    trigger = service.scheduler.get_job(reminder_id).trigger

    assert trigger.get_next_fire_time(first, first) == following
    assert trigger.get_next_fire_time(None, gap.replace(hour=1)) == following


def test_recurrence_keeps_explicit_second_fold_as_first_occurrence(tmp_path):
    zone = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    reminder_id = service.create("Recurring reminder", first, timezone_name=zone.key, recurrence="daily")
    service._schedule(reminder_id)
    trigger = service.scheduler.get_job(reminder_id).trigger

    before_first = first.replace(minute=15, fold=0)
    assert trigger.get_next_fire_time(None, before_first) == first.astimezone(timezone.utc)


def test_daily_recurrence_skips_a_whole_nonexistent_local_date(tmp_path):
    zone = ZoneInfo("Pacific/Apia")
    first = datetime(2011, 12, 29, 9, tzinfo=zone)
    following = datetime(2011, 12, 31, 9, tzinfo=zone).astimezone(timezone.utc)
    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    reminder_id = service.create("Recurring reminder", first, timezone_name=zone.key, recurrence="daily")
    service._schedule(reminder_id)
    trigger = service.scheduler.get_job(reminder_id).trigger

    assert trigger.get_next_fire_time(first, first) == following


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [("cancel", "cancelled"), ("complete", "completed"), ("snooze", "pending")],
)
def test_delivery_preserves_changes_made_while_the_notifier_runs(
    tmp_path, action, expected_status
):
    database = Database(tmp_path / "shu.db")
    database.initialize()

    def notify(reminder_id, _text, _allow_speech):
        getattr(service, action)(reminder_id)
        return "displayed"

    service = ReminderService(database, notifier=notify)
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    reminder_id = service.create("Reminder", due)
    original_due = service.list_pending()[0]["due_at"]

    service._deliver(reminder_id, original_due)

    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM reminders WHERE reminder_id=?", (reminder_id,)
        ).fetchone()
    assert row["status"] == expected_status
    assert row["last_notified_at"] is None
    assert row["result"] is None
    if action == "snooze":
        assert row["due_at"] != original_due


def test_stale_delivery_job_skips_a_snoozed_reminder(tmp_path):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    notifications = []
    service = ReminderService(
        database, notifier=lambda *_args: notifications.append("displayed")
    )
    reminder_id = service.create("Reminder", datetime.now(timezone.utc) + timedelta(hours=1))
    service._schedule(reminder_id)
    job = service.scheduler.get_job(reminder_id)
    assert job is not None

    service.snooze(reminder_id)
    job.func(*job.args)

    assert notifications == []
    assert [row["reminder_id"] for row in service.list_pending()] == [reminder_id]


@pytest.mark.parametrize("recurrence", [None, "daily"])
def test_two_sessions_claim_one_delivery_of_the_same_occurrence(tmp_path, recurrence):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    path = tmp_path / "shu.db"
    database = Database(path)
    database.initialize()
    entered = Event()
    release = Event()
    calls = []

    def first_notice(*_args):
        calls.append("first")
        entered.set()
        assert release.wait(5)
        return "displayed"

    def second_notice(*_args):
        calls.append("second")
        return "displayed"

    first = ReminderService(database, notifier=first_notice)
    second = ReminderService(Database(path), notifier=second_notice)
    due = datetime.now(timezone.utc).replace(microsecond=0)
    reminder_id = first.create("private fixture", due - timedelta(days=1), recurrence=recurrence)
    scheduled_due = first.list_pending()[0]["due_at"]
    with ThreadPoolExecutor(max_workers=2) as workers:
        delivery = workers.submit(first._deliver, reminder_id, scheduled_due, scheduled_occurrence=due)
        try:
            assert entered.wait(5)
            duplicate = workers.submit(second._deliver, reminder_id, scheduled_due, scheduled_occurrence=due)
            duplicate.result(timeout=5)
            assert calls == ["first"]
        finally:
            release.set()
        delivery.result(timeout=5)

    with database.connect() as connection:
        claims = connection.execute(
            "SELECT * FROM audit_logs WHERE tool='reminder_delivery'"
        ).fetchall()
    assert len(claims) == 1
    assert claims[0]["result"] == "delivered"
    assert "private fixture" not in str(tuple(claims[0]))

    if recurrence:
        second._deliver(reminder_id, scheduled_due, scheduled_occurrence=due + timedelta(days=1))
        assert calls == ["first", "second"]


def test_interrupted_claim_is_not_replayed_on_restart_but_can_be_snoozed(tmp_path):
    path = tmp_path / "shu.db"
    database = Database(path)
    database.initialize()
    attempts = []

    def interrupted_notice(*_args):
        attempts.append("interrupted")
        raise SystemExit("Simulate a process exiting before recording delivery")

    first = ReminderService(database, notifier=interrupted_notice)
    due = datetime.now(timezone.utc) - timedelta(minutes=2)
    reminder_id = first.create("fixture", due)
    scheduled_due = first.list_pending()[0]["due_at"]
    with pytest.raises(SystemExit):
        first._deliver(reminder_id, scheduled_due)

    # Reopening SQLite sees the claim even though the notifier never returned.
    second = ReminderService(Database(path), notifier=lambda *_args: attempts.append("retried"))
    try:
        assert second.start() == []
        assert second.scheduler.get_job(reminder_id) is None
        row, = second.list_pending()
        assert row["reminder_id"] == reminder_id
        assert row["result"] == "outcome_unknown"
        second._deliver(reminder_id, scheduled_due, scheduled_occurrence=due + timedelta(minutes=1))
        assert attempts == ["interrupted"]
    finally:
        second.shutdown()

    second.snooze(reminder_id)
    new_due = second.list_pending()[0]["due_at"]
    assert new_due != scheduled_due
    second._deliver(reminder_id, new_due)
    assert attempts == ["interrupted", "retried"]
    with database.connect() as connection:
        assert sorted(row[0] for row in connection.execute(
            "SELECT result FROM audit_logs WHERE tool='reminder_delivery'"
        )) == ["delivered", "outcome_unknown"]


def test_scheduler_forwards_exact_recurring_run_time_to_claim(tmp_path):
    from threading import Event

    database = Database(tmp_path / "shu.db")
    database.initialize()
    delivered = Event()
    service = ReminderService(database, notifier=lambda *_args: delivered.set())
    anchor = datetime.now(timezone.utc) + timedelta(days=2)
    reminder_id = service.create("future recurring fixture", anchor, recurrence="weekly")
    service.scheduler.start(paused=True)
    try:
        service._schedule(reminder_id)
        scheduled_time = datetime.now(timezone.utc) - timedelta(milliseconds=10)
        service.scheduler.modify_job(reminder_id, next_run_time=scheduled_time)
        service.scheduler.resume()
        assert delivered.wait(5)
    finally:
        service.shutdown()

    with database.connect() as connection:
        claim = connection.execute(
            "SELECT log_id FROM audit_logs WHERE tool='reminder_delivery'"
        ).fetchone()
    assert claim["log_id"].endswith(scheduled_time.isoformat())


def test_quiet_mode_suppresses_speech_signal(tmp_path):
    import threading

    database = Database(tmp_path / "shu.db")
    database.initialize()
    calls = []
    completed = threading.Event()

    def notify(_reminder_id, _text, allow_speech):
        calls.append(allow_speech)
        completed.set()
        return "displayed"

    service = ReminderService(
        database,
        notifier=notify,
        quiet_mode=lambda: True,
    )
    reminder_id = service.create(
        "Quiet reminder",
        datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    service.start()
    service.confirm_overdue(reminder_id, still_relevant=True)
    try:
        assert completed.wait(2)
        assert calls == [False]
    finally:
        service.shutdown()


def test_natural_reminder_parser_handles_relative_and_calendar_times():
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    relative = parse_natural_reminder("Remind me to stretch in 20 minutes", now=now)
    assert relative.text == "stretch"
    assert relative.due_at == now + timedelta(minutes=20)
    assert relative.recurrence is None

    tomorrow = parse_natural_reminder("call my sister tomorrow at 9 PM", now=now)
    assert tomorrow.text == "call my sister"
    assert tomorrow.due_at == datetime(2026, 11, 17, 21, 0, tzinfo=now.tzinfo)

    daily = parse_natural_reminder("take medicine daily at 8:30 AM", now=now)
    assert daily.recurrence == "daily"
    assert daily.due_at == datetime(2026, 11, 16, 8, 30, tzinfo=now.tzinfo)

    weekly = parse_natural_reminder(
        "send report every week on Monday at 9 AM", now=now
    )
    assert weekly.recurrence == "weekly"
    assert weekly.due_at == datetime(2026, 11, 16, 9, 0, tzinfo=now.tzinfo)


@pytest.mark.parametrize(("month", "day", "hour"), [(3, 8, 1), (11, 1, 0)])
@pytest.mark.parametrize(
    "phrase",
    [
        "stretch in 2 hours",
        "stretch in two hours",
        "১২০ মিনিট পরে ওষুধ খাও",
        "मुझे याद दिलाओ 2 घंटे बाद दवा लेना",
        "120 நிமிடம் கழித்து மாத்திரை எடு",
        "120 నిమిషాలు తర్వాత మందు తీసుకో",
        "120 മിനിറ്റ് കഴിഞ്ഞ് മരുന്ന് കഴിക്കുക",
    ],
)
def test_relative_reminder_measures_elapsed_time_across_dst(month, day, hour, phrase):
    zone = ZoneInfo("America/New_York")
    now = datetime(2026, month, day, hour, 45, tzinfo=zone)
    parsed = parse_natural_reminder(phrase, now=now, timezone_name=zone.key)

    assert parsed.due_at.astimezone(timezone.utc) == (
        now.astimezone(timezone.utc) + timedelta(hours=2)
    )
    assert parsed.due_at.tzinfo == zone


@pytest.mark.parametrize("phrase", ["stretch tomorrow at 2:30 AM", "stretch daily at 2:30 AM"])
def test_natural_reminder_rejects_a_nonexistent_local_time(phrase):
    zone = ZoneInfo("America/New_York")
    now = datetime(2026, 3, 7, 14, tzinfo=zone)

    with pytest.raises(ValueError, match="local time does not exist"):
        parse_natural_reminder(phrase, now=now, timezone_name=zone.key)


@pytest.mark.parametrize("due", ["2026-03-08T02:30:00", datetime(2026, 3, 8, 2, 30)])
def test_reminder_creation_rejects_a_nonexistent_local_time(tmp_path, due):
    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)

    with pytest.raises(ValueError, match="local time does not exist"):
        service.create("Stretch", due, timezone_name="America/New_York", recurrence="daily")
    assert service.list_pending() == []


def test_calendar_reminder_does_not_schedule_an_earlier_fold_as_future():
    zone = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 1, 1, 15, fold=1, tzinfo=zone)

    with pytest.raises(ValueError, match="time has already passed"):
        parse_natural_reminder("stretch today at 1:30 AM", now=now, timezone_name=zone.key)

    parsed = parse_natural_reminder("stretch at 1:30 AM", now=now, timezone_name=zone.key)
    assert parsed.due_at == datetime(2026, 11, 2, 1, 30, tzinfo=zone)


@pytest.mark.parametrize(
    ("phrase", "expected_text", "expected_due", "expected_recurrence"),
    [
        (
            "Remind me tomorrow at 9 AM to call mom",
            "call mom",
            datetime(2026, 11, 17, 9, 0),
            None,
        ),
        (
            "Remind me at 9 AM to call mom",
            "call mom",
            datetime(2026, 11, 16, 9, 0),
            None,
        ),
        (
            "Remind me daily at 8 AM to take medicine",
            "take medicine",
            datetime(2026, 11, 17, 8, 0),
            "daily",
        ),
        (
            "Remind me every week on Monday at 9 AM to water plants",
            "water plants",
            datetime(2026, 11, 16, 9, 0),
            "weekly",
        ),
        (
            "Remind me tomorrow morning at 9 to check the oven",
            "check the oven",
            datetime(2026, 11, 17, 9, 0),
            None,
        ),
    ],
)
def test_english_schedule_first_reminder_phrases(
    phrase, expected_text, expected_due, expected_recurrence
):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text == expected_text
    assert parsed.due_at == expected_due.replace(tzinfo=now.tzinfo)
    assert parsed.recurrence == expected_recurrence


def test_english_schedule_first_parser_rejects_unbounded_schedule_words():
    with pytest.raises(ValueError, match="Time is unclear"):
        parse_natural_reminder(
            "Remind me sometime tomorrow at 9 AM to call mom"
        )


@pytest.mark.parametrize(
    ("phrase", "expected_text"),
    [
        (
            "আগামীকাল সকাল 9টায় ওষুধ খাও মনে করিয়ে দাও",
            "ওষুধ খাও",
        ),
        (
            "कल सुबह 9 बजे दवा लेना याद दिलाओ",
            "दवा लेना",
        ),
        (
            "நாளை காலை 9 மணிக்கு மருந்து எடுக்க நினைவூட்டு",
            "மருந்து எடுக்க",
        ),
        (
            "రేపు ఉదయం 9 గంటలకు మందు తీసుకోమని గుర్తు చేయండి",
            "మందు తీసుకోమని",
        ),
        (
            "നാളെ രാവിലെ 9 മണിക്ക് മരുന്ന് കഴിക്കാൻ ഓർമ്മിപ്പിക്കൂ",
            "മരുന്ന് കഴിക്കാൻ",
        ),
    ],
)
def test_localized_schedule_first_reminder_phrases(phrase, expected_text):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text == expected_text
    assert parsed.due_at == datetime(2026, 11, 17, 9, 0, tzinfo=now.tzinfo)
    assert parsed.recurrence is None


def test_localized_schedule_first_requires_a_known_reminder_suffix_or_task():
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    with pytest.raises(ValueError, match="Time is unclear"):
        parse_natural_reminder("আগামীকাল সকাল 9টায় হয়তো", now=now)
    with pytest.raises(ValueError, match="Reminder text cannot be empty"):
        parse_natural_reminder("আগামীকাল সকাল 9টায় মনে করিয়ে দাও", now=now)


@pytest.mark.parametrize(
    ("phrase", "expected_due", "expected_recurrence"),
    [
        (
            "remind me to take vitamins tomorrow morning at 9",
            datetime(2026, 11, 17, 9, 0),
            None,
        ),
        (
            "call the clinic today at 5 in the evening",
            datetime(2026, 11, 16, 17, 0),
            None,
        ),
        (
            "practice piano daily at 7 in the morning",
            datetime(2026, 11, 17, 7, 0),
            "daily",
        ),
        (
            "send the report every week on Monday evening at 5",
            datetime(2026, 11, 16, 17, 0),
            "weekly",
        ),
        (
            "pay the bill tomorrow at noon",
            datetime(2026, 11, 17, 12, 0),
            None,
        ),
        (
            "check the door at midnight",
            datetime(2026, 11, 17, 0, 0),
            None,
        ),
    ],
)
def test_english_reminder_parser_accepts_clear_dayparts_and_clock_words(
    phrase, expected_due, expected_recurrence
):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.due_at == expected_due.replace(tzinfo=now.tzinfo)
    assert parsed.recurrence == expected_recurrence


@pytest.mark.parametrize(
    "phrase",
    [
        "take medicine tomorrow morning at 9 PM",
        "call home today at 17 in the morning",
        "practice piano daily at 0 in the evening",
        "pay the bill tomorrow afternoon at midnight",
    ],
)
def test_english_reminder_parser_rejects_conflicting_dayparts(phrase):
    with pytest.raises(ValueError, match="daypart|clock"):
        parse_natural_reminder(phrase)


@pytest.mark.parametrize(
    ("phrase", "expected_text", "delta"),
    [
        ("Remind me to stretch in ten minutes", "stretch", timedelta(minutes=10)),
        ("in 10 minutes remind me to call home", "call home", timedelta(minutes=10)),
        ("take medicine after half an hour", "take medicine", timedelta(minutes=30)),
        ("check the oven in an hour", "check the oven", timedelta(hours=1)),
        ("call my sister in a couple of hours", "call my sister", timedelta(hours=2)),
        ("water plants in twenty-one minutes", "water plants", timedelta(minutes=21)),
        ("remind me in 2 days to submit the form", "submit the form", timedelta(days=2)),
    ],
)
def test_english_spoken_relative_reminder_phrases(phrase, expected_text, delta):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text == expected_text
    assert parsed.due_at == now + delta
    assert parsed.recurrence is None


@pytest.mark.parametrize(
    "phrase",
    [
        "remind me to exercise tomorrow",
        "take medicine today at 25:00",
        "stretch in 0 minutes",
        "call someone around lunch",
        "stretch in 6000 days",
        "stretch in zero minutes",
        "stretch in half a minute",
        "backup in 366 days",
    ],
)
def test_natural_reminder_parser_rejects_ambiguous_or_invalid_times(phrase):
    with pytest.raises(ValueError):
        parse_natural_reminder(phrase)


def test_natural_reminder_is_persisted_only_after_parsing(tmp_path):
    from zoneinfo import ZoneInfo

    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    reminder_id, parsed = service.create_from_text(
        "Remind me to pay the bill in 2 hours", now=now
    )
    row = service.list_pending()[0]
    assert row["reminder_id"] == reminder_id
    assert row["text"] == "pay the bill"
    assert row["source"] == "natural_language"
    assert datetime.fromisoformat(row["due_at"]) == parsed.due_at.astimezone(timezone.utc)


@pytest.mark.parametrize(
    ("phrase", "expected_text", "amount"),
    [
        ("take medicine in 20 minutes", "take medicine", 20),
        ("২০ মিনিট পরে ওষুধ খাও", "ওষুধ খাও", 20),
        ("मुझे याद दिलाओ 2 घंटे बाद दवा लेना", "दवा लेना", 120),
        ("30 நிமிடம் கழித்து மாத்திரை எடு", "மாத்திரை எடு", 30),
        ("30 నిమిషాల తర్వాత మందు తీసుకో", "మందు తీసుకో", 30),
        ("ദയവായി എന്നെ ഓർമ്മിപ്പിക്കൂ 45 മിനിറ്റ് കഴിഞ്ഞ് മരുന്ന് കഴിക്കുക", "മരുന്ന് കഴിക്കുക", 45),
    ],
)
def test_localized_relative_reminders_cover_supported_voice_languages(phrase, expected_text, amount):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text == expected_text
    assert parsed.due_at == now + timedelta(minutes=amount)
    assert parsed.recurrence is None


@pytest.mark.parametrize(
    ("phrase", "expected_text"),
    [
        ("ওষুধ খাও আগামীকাল সকাল ৯টা", "ওষুধ খাও"),
        ("दवा लो कल सुबह 9 बजे", "दवा लो"),
        ("மருந்து எடுத்துக்கொள் நாளை காலை 9 மணிக்கு", "மருந்து எடுத்துக்கொள்"),
        ("మందు తీసుకో రేపు ఉదయం 9 గంటలకు", "మందు తీసుకో"),
        ("മരുന്ന് കഴിക്കുക നാളെ രാവിലെ 9 മണിക്ക്", "മരുന്ന് കഴിക്കുക"),
    ],
)
def test_localized_calendar_tomorrow_phrases(phrase, expected_text):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text == expected_text
    assert parsed.due_at == datetime(2026, 11, 17, 9, 0, tzinfo=now.tzinfo)
    assert parsed.recurrence is None


@pytest.mark.parametrize(
    "phrase",
    [
        "ওষুধ খাও আজ সকাল ৯টা",
        "दवा लो आज सुबह 9 बजे",
        "மருந்து எடுத்துக்கொள் இன்று காலை 9 மணிக்கு",
        "మందు తీసుకో ఈరోజు ఉదయం 9 గంటలకు",
        "മരുന്ന് കഴിക്കുക ഇന്ന് രാവിലെ 9 മണിക്ക്",
    ],
)
def test_localized_calendar_today_phrases(phrase):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.due_at == datetime(2026, 11, 16, 9, 0, tzinfo=now.tzinfo)
    assert parsed.recurrence is None


@pytest.mark.parametrize(
    ("phrase", "expected_text"),
    [
        ("ওষুধ খাও প্রতিদিন সকাল ৯টা", "ওষুধ খাও"),
        ("दवा लो हर दिन सुबह 9 बजे", "दवा लो"),
        ("மருந்து தினமும் காலை 9 மணிக்கு", "மருந்து"),
        ("మందు ప్రతి రోజు ఉదయం 9 గంటలకు", "మందు"),
        ("മരുന്ന് ദിവസവും രാവിലെ 9 മണിക്ക്", "മരുന്ന്"),
    ],
)
def test_localized_daily_recurrence_phrases(phrase, expected_text):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text == expected_text
    assert parsed.due_at == datetime(2026, 11, 16, 9, 0, tzinfo=now.tzinfo)
    assert parsed.recurrence == "daily"


def test_localized_calendar_reminder_is_persisted_with_recurrence(tmp_path):
    from zoneinfo import ZoneInfo

    database = Database(tmp_path / "shu.db")
    database.initialize()
    service = ReminderService(database)
    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    reminder_id, parsed = service.create_from_text(
        "ওষুধ খাও প্রতিদিন সকাল ৯টা",
        timezone_name="Asia/Kolkata",
        now=now,
    )

    row = service.list_pending()[0]
    assert row["reminder_id"] == reminder_id
    assert row["text"] == "ওষুধ খাও"
    assert row["recurrence"] == "daily"
    assert datetime.fromisoformat(row["due_at"]) == parsed.due_at.astimezone(timezone.utc)


@pytest.mark.parametrize(
    ("phrase", "expected_text"),
    [
        ("ওষুধ খাও প্রতি সপ্তাহে সোমবার সকাল ৯টা", "ওষুধ খাও"),
        ("दवा लो हर सप्ताह सोमवार सुबह 9 बजे", "दवा लो"),
        ("மருந்து ஒவ்வொரு வாரமும் திங்கட்கிழமை காலை 9 மணிக்கு", "மருந்து"),
        ("మందు ప్రతి వారం సోమవారం ఉదయం 9 గంటలకు", "మందు"),
        ("മരുന്ന് എല്ലാ ആഴ്ചയും തിങ്കളാഴ്ച രാവിലെ 9 മണിക്ക്", "മരുന്ന്"),
    ],
)
def test_localized_weekly_recurrence_phrases(phrase, expected_text):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text == expected_text
    assert parsed.due_at == datetime(2026, 11, 16, 9, 0, tzinfo=now.tzinfo)
    assert parsed.recurrence == "weekly"


@pytest.mark.parametrize(
    ("phrase", "expected_text", "expected_recurrence"),
    [
        ("প্রতিদিন সকাল ৯টায় ওষুধ খাও মনে করিয়ে দাও", "ওষুধ খাও", "daily"),
        ("প্রতি সপ্তাহে সোমবার সকাল ৯টায় ওষুধ খাও মনে করিয়ে দাও", "ওষুধ খাও", "weekly"),
        ("हर दिन सुबह 9 बजे दवा लेना याद दिलाओ", "दवा लेना", "daily"),
        ("हर सप्ताह सोमवार सुबह 9 बजे दवा लेना याद दिलाओ", "दवा लेना", "weekly"),
        ("தினமும் காலை 9 மணிக்கு மருந்து எடுக்க நினைவூட்டு", "மருந்து எடுக்க", "daily"),
        ("ஒவ்வொரு வாரமும் திங்கட்கிழமை காலை 9 மணிக்கு மருந்து எடுக்க நினைவூட்டு", "மருந்து எடுக்க", "weekly"),
        ("ప్రతి రోజు ఉదయం 9 గంటలకు మందు తీసుకోమని గుర్తు చేయండి", "మందు తీసుకోమని", "daily"),
        ("ప్రతి వారం సోమవారం ఉదయం 9 గంటలకు మందు తీసుకోమని గుర్తు చేయండి", "మందు తీసుకోమని", "weekly"),
        ("ദിവസവും രാവിലെ 9 മണിക്ക് മരുന്ന് കഴിക്കാൻ ഓർമ്മിപ്പിക്കൂ", "മരുന്ന് കഴിക്കാൻ", "daily"),
        ("എല്ലാ ആഴ്ചയും തിങ്കളാഴ്ച രാവിലെ 9 മണിക്ക് മരുന്ന് കഴിക്കാൻ ഓർമ്മിപ്പിക്കൂ", "മരുന്ന് കഴിക്കാൻ", "weekly"),
    ],
)
def test_localized_schedule_first_recurrence_phrases(
    phrase, expected_text, expected_recurrence
):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text == expected_text
    assert parsed.due_at == datetime(2026, 11, 16, 9, 0, tzinfo=now.tzinfo)
    assert parsed.recurrence == expected_recurrence


@pytest.mark.parametrize(
    ("phrase", "expected_hour"),
    [
        ("ওষুধ খাও প্রতি সোমবার বিকেল ৫টায়", 17),
        ("दवा लो हर सोमवार शाम 5 बजे", 17),
        ("மருந்து ஒவ்வொரு திங்கட்கிழமையும் மாலை 5 மணிக்கு", 17),
        ("మందు ప్రతి సోమవారం సాయంత్రం 5 గంటలకు", 17),
        ("മരുന്ന് എല്ലാ തിങ്കളാഴ്ചയും വൈകുന്നേരം 5 മണിക്ക്", 17),
    ],
)
def test_localized_weekday_recurrence_and_pm_clock(phrase, expected_hour):
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 16, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_reminder(phrase, now=now)

    assert parsed.text
    assert parsed.due_at == datetime(2026, 11, 16, expected_hour, 0, tzinfo=now.tzinfo)
    assert parsed.recurrence == "weekly"


@pytest.mark.parametrize(
    "phrase",
    [
        "প্রতিদিন সকাল ৯টা",
        "हर दिन सुबह 9 बजे",
        "தினமும் காலை 9 மணிக்கு",
        "ప్రతి రోజు ఉదయం 9 గంటలకు",
        "ദിവസവും രാവിലെ 9 മണിക്ക്",
    ],
)
def test_localized_schedule_without_reminder_text_is_rejected(phrase):
    with pytest.raises(ValueError, match="Reminder text cannot be empty"):
        parse_natural_reminder(phrase)


@pytest.mark.parametrize(
    "phrase",
    ["০ মিনিট পরে ওষুধ খাও", "540 দিন পরে ওষুধ খাও"],
)
def test_localized_relative_reminders_reject_invalid_amounts(phrase):
    with pytest.raises(ValueError):
        parse_natural_reminder(phrase)
