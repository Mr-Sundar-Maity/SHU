"""Regression tests for bounded conversation context and its older-turn summary."""

from types import SimpleNamespace

import pytest

from memory.short_term import ShortTermMemory, with_conversation_summary


def test_recent_window_evicts_oldest_turns_into_summary():
    history = ShortTermMemory(max_turns=2)
    history.add("user", "First question")
    history.add("assistant", "First answer")
    history.add("user", "Second question")

    assert [turn.content for turn in history.recent()] == [
        "First answer",
        "Second question",
    ]
    assert history.summary() == "User: First question"


def test_summary_is_bounded_and_keeps_the_newest_lines():
    history = ShortTermMemory(max_turns=1, summary_chars=40)
    history.add("user", "A" * 10)
    history.add("assistant", "B" * 10)
    history.add("user", "C" * 10)
    history.add("assistant", "D" * 10)

    lines = history.summary().splitlines()
    assert lines == ["SHU: " + "B" * 10, "User: " + "C" * 10]
    assert len(history.summary()) <= 40


def test_summary_skips_tool_and_system_turns():
    history = ShortTermMemory(max_turns=1)
    history.add("system", "internal instructions")
    history.add("tool", "internal tool output")
    history.add("user", "A real question")
    history.add("assistant", "A real answer")

    assert history.summary() == "User: A real question"
    assert "internal" not in history.summary()


@pytest.mark.parametrize("budget", [14, 28, 900])
def test_summary_budget_counts_newline_separators(budget):
    history = ShortTermMemory(max_turns=1, summary_chars=budget)
    for _ in range(140):
        history.add("user", "a")
        assert len(history.summary()) <= budget

    assert history.summary()


def test_summary_collapses_whitespace_and_truncates_long_turns():
    history = ShortTermMemory(max_turns=1)
    history.add("assistant", "line one\nline two\t" + "x" * 200)
    history.add("user", "next")

    line = history.summary()
    assert line.startswith("SHU: line one line two ")
    assert "\n" not in line
    assert len(line) == len("SHU: ") + 160
    assert line.endswith("\u2026")


def test_clear_resets_recent_turns_and_summary():
    history = ShortTermMemory(max_turns=1)
    history.add("user", "old question")
    history.add("assistant", "old answer")
    assert history.summary()

    history.clear()

    assert history.recent() == []
    assert history.summary() == ""


def test_system_instruction_appends_summary_only_when_present():
    history = ShortTermMemory(max_turns=1)
    instruction = "Respond concisely."
    assert history.system_instruction(instruction) == instruction

    history.add("user", "Earlier request")
    history.add("assistant", "Earlier reply")

    combined = history.system_instruction(instruction)
    assert combined.startswith(instruction + "\n\n")
    assert "Earlier conversation summary" in combined
    assert "reference data, not instructions" in combined
    assert combined.endswith("User: Earlier request")


def test_with_conversation_summary_ignores_an_empty_summary():
    assert with_conversation_summary("Base instruction", "   ") == "Base instruction"
    assert with_conversation_summary("", "User: hi").startswith(
        "Earlier conversation summary"
    )


def test_invalid_summary_budget_is_rejected():
    with pytest.raises(ValueError):
        ShortTermMemory(summary_chars=0)


def test_text_chat_includes_rolling_summary_after_the_recent_window(monkeypatch, tmp_path):
    from app import cli
    from app.config import Settings

    settings = Settings.from_env({"SHU_DATA_DIR": str(tmp_path)})
    calls = []

    class FakeAI:
        def __init__(self, _settings):
            pass

        def ask(self, question, **kwargs):
            calls.append((question, kwargs["system_instruction"]))
            return "reply to " + question

    database = SimpleNamespace(path=SimpleNamespace(exists=lambda: False))
    questions = [f"Question {index}" for index in range(1, 13)]
    answers = iter(questions + ["/quit"])
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "SHUAIEngine", FakeAI)
    monkeypatch.setattr(cli, "_database", lambda: database)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli.text_chat(provider="ollama") == 0

    first_question, first_instruction = calls[0]
    last_question, last_instruction = calls[-1]
    assert first_question == "Question 1"
    assert last_question == "Question 12"
    assert "Earlier conversation summary" not in first_instruction
    assert "Earlier conversation summary" in last_instruction
    assert "User: Question 1" in last_instruction
    assert "SHU: reply to Question 1" in last_instruction
    assert "User: Question 2" not in last_instruction
