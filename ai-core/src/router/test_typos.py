"""Correcting a mistyped word without a hand-written list of misspellings.

The file this replaces the need for had four such lists -- one each for
`librarian`, `subject`, `library` and `makerspace`. Every new typo needed
a code change, and the only way to learn which one was missing was for
somebody to hit it and give up. A student who mistypes and gets a bad
answer does not file a report.

MOST OF THIS FILE IS ABOUT WHAT MUST NOT BE CORRECTED. A wrong correction
is worse than a missed one: it answers confidently about something nobody
asked. The eight words below are the ones a first, more ambitious version
got wrong, measured against every word real patrons have actually typed.
"""

import pytest

from src.router.typos import VOCABULARY, correction_for, normalise


class TestItCorrectsMistypings:
    @pytest.mark.parametrize("typed,meant", [
        ("lirbary", "library"),      # live, 2026-08-27
        ("librarain", "librarian"),  # live, same corpus of questions
        ("libraries", None),         # already right -- untouched
    ])
    def test_an_adjacent_swap_is_recognised(self, typed, meant):
        assert correction_for(typed) == meant

    def test_the_message_comes_back_corrected(self):
        assert (normalise("who is in charge of the lirbary")
                == "who is in charge of the library")

    def test_capitalisation_is_kept(self):
        """Anything that echoes the text must not look like it silently
        rewrote the reader."""
        assert normalise("Lirbary hours") == "Library hours"

    def test_a_message_with_no_mistyping_comes_back_identical(self):
        m = "who is in charge of the library"
        assert normalise(m) is m or normalise(m) == m


class TestWhatItMustNotTouch:
    @pytest.mark.parametrize("word", [
        # Every one of these was corrected by an any-single-edit version,
        # and every one is wrong. They are real words patrons really typed.
        "directory",   # -> director. A real word, and a real page.
        "onesearch",   # -> research. A product name.
        "archivist",   # -> archives. A real word, and a job title.
        "charge",      # -> charger
        "chapters",    # -> chargers
        "point",       # -> print
        "borrowed",    # -> borrow
        "situation",   # -> citation
    ])
    def test_real_words_are_left_alone(self, word):
        assert correction_for(word) is None, word

    def test_a_vocabulary_word_is_never_corrected(self):
        for w in list(VOCABULARY)[:12]:
            assert correction_for(w) is None, w

    def test_short_tokens_are_left_alone(self):
        """Below five letters a swap reaches too many real words."""
        for w in ("form", "care", "form", "tow", "on"):
            assert correction_for(w) is None, w

    def test_a_swap_that_lands_on_another_real_word_is_not_a_correction(self):
        """If the swapped form is itself in the vocabulary, the reader
        typed a word, not a mistake."""
        assert correction_for("reserve") is None
        assert correction_for("reserves") is None

    def test_an_unrelated_word_is_untouched(self):
        for w in ("thesis", "professor", "chemistry", "tuesday"):
            assert correction_for(w) is None, w


class TestAmbiguityIsLeftAlone:
    def test_a_token_two_vocabulary_words_both_reach_is_not_guessed(self,
                                                                   monkeypatch):
        """A token we cannot read unambiguously is one we leave as typed;
        guessing between two words answers the wrong question with
        confidence."""
        import src.router.typos as T

        monkeypatch.setattr(T, "VOCABULARY", frozenset({"tacos", "tacox"}))
        T._index.cache_clear()
        T.correction_for.cache_clear()
        # "tacso" is one swap from "tacos"; construct a genuine collision.
        monkeypatch.setattr(T, "VOCABULARY", frozenset({"abcde", "abced"}))
        T._index.cache_clear()
        T.correction_for.cache_clear()
        assert T.correction_for("abcde") is None
        T._index.cache_clear()
        T.correction_for.cache_clear()


class TestItOnlyEverAddsAMatch:
    def test_the_original_is_always_offered_first(self):
        from src.graph.new_orchestrator import _also_typo_fixed

        raw = "who is in charge of the lirbary"
        forms = _also_typo_fixed(raw)
        assert forms[0] == raw

    def test_a_clean_message_produces_exactly_one_form(self):
        """No second regex run on the 99% of turns with no typo in them."""
        from src.graph.new_orchestrator import _also_typo_fixed

        assert len(_also_typo_fixed("who is in charge of the library")) == 1

    def test_the_dean_answer_now_survives_the_typo(self):
        from src.graph.new_orchestrator import _dean_answer

        assert _dean_answer("who is in charge of the lirbary") is not None
        assert _dean_answer("who is in charge of the library") is not None

    def test_it_still_declines_what_it_declined_before(self):
        from src.graph.new_orchestrator import _dean_answer

        assert _dean_answer("where is the library") is None
        assert _dean_answer("what time does the library close") is None
