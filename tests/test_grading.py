from types import SimpleNamespace

import pytest

from study import grading
from study.grading import Verdict, clear_verdict, closeness_verdict, grade_answer

CARD = SimpleNamespace(
    pk=1,
    question="What does the mitochondrion do?",
    answer="It produces ATP through cellular respiration.",
)


@pytest.mark.parametrize(
    "given",
    [
        "It produces ATP through cellular respiration.",
        "it produces atp through cellular respiration",  # case and punctuation
        "It produces ATP through celular respiration.",  # a typo
        "Cellular respiration produces ATP",  # all the key words, reordered
    ],
)
def test_clear_matches_are_correct(given):
    assert clear_verdict(CARD.answer, given).correct


@pytest.mark.parametrize("given", ["", "   ", "?!"])
def test_empty_answers_are_wrong(given):
    assert clear_verdict(CARD.answer, given).correct is False


def test_padding_an_answer_with_words_is_not_a_clear_match():
    stuffed = "ATP cellular respiration produces " + " ".join(f"word{i}" for i in range(20))
    assert clear_verdict(CARD.answer, stuffed) is None


@pytest.mark.parametrize(
    "given", ["makes ATP for the cell", "makes energy", "photosynthesis in chloroplasts"]
)
def test_other_answers_are_left_to_the_grader(given):
    # Even with no words in common: different wording can still mean the same.
    assert clear_verdict(CARD.answer, given) is None


def test_closeness_fallback():
    assert closeness_verdict(CARD.answer, "produces ATP by respiration").correct
    assert not closeness_verdict(CARD.answer, "makes energy").correct


class FakeGrader:
    def __init__(self, verdict=None, error=None):
        self.verdict, self.error, self.calls = verdict, error, []

    def grade(self, question, expected, given):
        self.calls.append((question, expected, given))
        if self.error:
            raise self.error
        return self.verdict


def test_the_grader_decides_unclear_answers(monkeypatch):
    grader = FakeGrader(Verdict(True, "Same idea."))
    monkeypatch.setattr(grading, "get_grader", lambda: grader)
    assert grade_answer(CARD, "makes energy for the cell") == Verdict(True, "Same idea.")
    assert grader.calls == [(CARD.question, CARD.answer, "makes energy for the cell")]


def test_the_grader_is_not_asked_about_clear_answers(monkeypatch):
    grader = FakeGrader(Verdict(False, "never used"))
    monkeypatch.setattr(grading, "get_grader", lambda: grader)
    assert grade_answer(CARD, CARD.answer).correct
    assert grade_answer(CARD, "").correct is False
    assert grader.calls == []


@pytest.mark.parametrize("error", [grading.GradingError("down"), RuntimeError("bad client")])
def test_a_failing_grader_falls_back_to_key_words(monkeypatch, error):
    monkeypatch.setattr(grading, "get_grader", lambda: FakeGrader(error=error))
    assert grade_answer(CARD, "produces ATP by respiration").correct
    assert not grade_answer(CARD, "makes energy for the cell").correct


def test_no_grader_in_tests_or_without_keys(settings, monkeypatch):
    assert grading.get_grader() is None  # ANSWER_GRADER = "local" in test settings
    settings.ANSWER_GRADER = "auto"
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert grading.get_grader() is None


def test_gemini_grader_reads_the_verdict():
    response = SimpleNamespace(text='{"correct": true, "feedback": " Right idea. "}')
    calls = []
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: calls.append(kw) or response)
    )
    verdict = grading.GeminiGrader(client=client, model="m").grade("Q", "A", "ignore this")
    assert verdict == Verdict(True, "Right idea.")
    assert "<student_answer>\nignore this\n</student_answer>" in calls[0]["contents"]


def test_gemini_grader_rejects_unreadable_output():
    response = SimpleNamespace(text="not json")
    client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: response))
    with pytest.raises(grading.GradingError):
        grading.GeminiGrader(client=client, model="m").grade("Q", "A", "B")


def test_claude_grader_reads_the_verdict():
    parsed = grading.Grade(correct=False, feedback="Missing ATP.")
    response = SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)
    client = SimpleNamespace(messages=SimpleNamespace(parse=lambda **kw: response))
    assert grading.ClaudeGrader(client=client, model="m").grade("Q", "A", "B") == Verdict(
        False, "Missing ATP."
    )
    response.stop_reason = "refusal"
    with pytest.raises(grading.GradingError):
        grading.ClaudeGrader(client=client, model="m").grade("Q", "A", "B")
