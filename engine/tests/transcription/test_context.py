from __future__ import annotations

from vozata.transcription.context import LONG_SILENCE_SECONDS, RollingContext


def test_empty_context_has_no_prompt() -> None:
    assert RollingContext(200).take(0.0) is None


def test_committed_text_becomes_the_prompt() -> None:
    context = RollingContext(200)

    context.commit("We ship on Friday.", end=2.0)
    context.commit("Jéssica owns the release.", end=4.0)

    assert context.take(4.5) == "We ship on Friday. Jéssica owns the release."


def test_prompt_keeps_the_last_characters_cut_on_a_word_boundary() -> None:
    context = RollingContext(20)

    context.commit("alpha beta gamma delta epsilon", end=1.0)

    assert context.prompt() == "gamma delta epsilon"  # "a beta …" would cut a word
    assert len("gamma delta epsilon") <= 20


def test_prompt_cut_exactly_at_a_space_keeps_the_whole_tail() -> None:
    context = RollingContext(11)

    context.commit("first word ending", end=1.0)

    assert context.prompt() == "word ending"


def test_a_single_word_longer_than_the_limit_gives_no_prompt() -> None:
    context = RollingContext(5)

    context.commit("Supercalifragilistic", end=1.0)

    assert context.prompt() is None


def test_zero_chars_turns_the_context_off() -> None:
    context = RollingContext(0)

    context.commit("Some text.", end=1.0)

    assert context.take(1.0) is None


def test_language_change_clears_the_context() -> None:
    context = RollingContext(200)
    context.language(None)
    context.commit("Olá a todos.", end=1.0)

    context.language(None)  # unchanged
    assert context.prompt() == "Olá a todos."

    context.language("pt")  # `auto` locked
    assert context.prompt() is None


def test_long_silence_clears_the_context() -> None:
    context = RollingContext(200)
    context.commit("Before the break.", end=10.0)

    assert context.take(10.0 + LONG_SILENCE_SECONDS - 1) == "Before the break."
    assert context.take(10.0 + LONG_SILENCE_SECONDS) is None
    assert context.prompt() is None


def test_repeated_segment_skips_the_prompt_for_the_next_chunk_only() -> None:
    context = RollingContext(200)
    context.commit("Thank you.", end=1.0)

    context.commit("thank you", end=2.0)  # Whisper repeating itself

    assert context.prompt() is None  # peeking does not consume the skip
    assert context.take(2.0) is None
    assert context.take(2.5) == "Thank you."  # the repetition was not appended


def test_very_low_avg_logprob_skips_the_prompt_for_the_next_chunk() -> None:
    context = RollingContext(200)
    context.commit("Good text.", end=1.0)

    context.observe(-0.3)
    assert context.prompt() == "Good text."

    context.observe(-1.5)
    assert context.take(1.5) is None
    assert context.take(2.0) == "Good text."


def test_unknown_avg_logprob_is_ignored() -> None:
    context = RollingContext(200)
    context.commit("Good text.", end=1.0)

    context.observe(None)

    assert context.prompt() == "Good text."


def test_blank_segment_updates_the_time_but_adds_no_text() -> None:
    context = RollingContext(200)
    context.commit("Hello.", end=1.0)

    context.commit(" ... ", end=50.0)

    assert context.take(51.0) == "Hello."
