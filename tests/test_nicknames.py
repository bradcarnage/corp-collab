"""Tests for corp_collab.nicknames module."""

from __future__ import annotations

import pytest

from corp_collab.nicknames import (
    BLOCKLIST,
    MAX_TITLE_LENGTH,
    NAME_POOLS,
    NicknameGenerator,
)


@pytest.fixture
def gen() -> NicknameGenerator:
    return NicknameGenerator(seed=42)


# ── Name generation ──────────────────────────────────────────────────

class TestGenerate:
    @pytest.mark.parametrize("role", list(NAME_POOLS))
    def test_generate_per_role(self, gen: NicknameGenerator, role: str) -> None:
        nick = gen.generate(role)
        assert nick in NAME_POOLS[role]

    def test_unknown_role_raises(self, gen: NicknameGenerator) -> None:
        with pytest.raises(ValueError, match="Unknown role"):
            gen.generate("janitor")

    def test_exclude_respected(self, gen: NicknameGenerator) -> None:
        exclude = {"Curie", "Volta", "Darwin"}
        nick = gen.generate("researcher", exclude=exclude)
        assert nick not in exclude
        assert nick in NAME_POOLS["researcher"]

    def test_no_duplicates_across_multiple_generates(self) -> None:
        gen = NicknameGenerator(seed=0)
        seen: set[str] = set()
        pool_size = len(NAME_POOLS["engineer"])
        for _ in range(pool_size):
            nick = gen.generate("engineer", exclude=seen)
            assert nick not in seen
            seen.add(nick)
        # All base names consumed
        assert seen == set(NAME_POOLS["engineer"])

    def test_pool_exhaustion_adds_suffix(self) -> None:
        gen = NicknameGenerator(seed=7)
        all_names = set(NAME_POOLS["reviewer"])
        nick = gen.generate("reviewer", exclude=all_names)
        # Should be like "Jenkins-2" etc.
        assert "-" in nick
        base, suffix = nick.rsplit("-", 1)
        assert base in NAME_POOLS["reviewer"]
        assert suffix.isdigit()

    def test_pool_exhaustion_suffix_increments(self) -> None:
        gen = NicknameGenerator(seed=1)
        pool = NAME_POOLS["analyst"]
        all_base = set(pool)
        all_suffix2 = {f"{n}-2" for n in pool}
        exclude = all_base | all_suffix2
        nick = gen.generate("analyst", exclude=exclude)
        assert nick.endswith("-3")

    def test_case_insensitive_role(self, gen: NicknameGenerator) -> None:
        nick = gen.generate("MANAGER")
        assert nick in NAME_POOLS["manager"]


# ── Title progression ────────────────────────────────────────────────

class TestTitleProgression:
    def test_intern_level(self) -> None:
        assert NicknameGenerator.get_title("researcher", "intern") == "Intern"

    def test_role_level_per_role(self) -> None:
        assert NicknameGenerator.get_title("researcher", "role") == "Researcher"
        assert NicknameGenerator.get_title("engineer", "role") == "Engineer"
        assert NicknameGenerator.get_title("manager", "role") == "Manager"

    def test_senior_level(self) -> None:
        assert NicknameGenerator.get_title("analyst", "senior") == "Senior"

    def test_lead_level(self) -> None:
        assert NicknameGenerator.get_title("reviewer", "lead") == "Lead"

    def test_director_level(self) -> None:
        assert NicknameGenerator.get_title("engineer", "director") == "Director"

    def test_unknown_level_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown level"):
            NicknameGenerator.get_title("engineer", "ceo")

    def test_unknown_role_at_role_level_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown role"):
            NicknameGenerator.get_title("janitor", "role")

    def test_level_case_insensitive(self) -> None:
        assert NicknameGenerator.get_title("engineer", "SENIOR") == "Senior"


# ── Full name formatting ─────────────────────────────────────────────

class TestFullName:
    def test_basic(self) -> None:
        assert NicknameGenerator.full_name("Intern", "Curie") == "Intern Curie"

    def test_senior(self) -> None:
        assert NicknameGenerator.full_name("Senior", "Lovelace") == "Senior Lovelace"

    def test_custom_manager_title(self) -> None:
        assert (
            NicknameGenerator.full_name("Deadline Dragon", "Brandon")
            == "Deadline Dragon Brandon"
        )


# ── Custom title validation ──────────────────────────────────────────

class TestValidateCustomTitle:
    def test_valid_title(self) -> None:
        ok, reason = NicknameGenerator.validate_custom_title("Deadline Dragon")
        assert ok is True
        assert reason == "ok"

    def test_empty_title(self) -> None:
        ok, reason = NicknameGenerator.validate_custom_title("   ")
        assert ok is False
        assert "empty" in reason.lower()

    def test_too_long(self) -> None:
        ok, reason = NicknameGenerator.validate_custom_title("A" * (MAX_TITLE_LENGTH + 1))
        assert ok is False
        assert "exceeds" in reason.lower()

    def test_blocklist_single_word(self) -> None:
        # Pick the first word from the blocklist for a deterministic test
        blocked = sorted(BLOCKLIST)[0]
        ok, reason = NicknameGenerator.validate_custom_title(blocked)
        assert ok is False
        assert "blocked" in reason.lower()

    def test_blocklist_in_phrase(self) -> None:
        ok, reason = NicknameGenerator.validate_custom_title("Chief Shit Disturber")
        assert ok is False
        assert "blocked" in reason.lower()

    def test_blocklist_case_insensitive(self) -> None:
        ok, reason = NicknameGenerator.validate_custom_title("FUCK")
        assert ok is False

    def test_uniqueness_taken(self) -> None:
        taken = {"Deadline Dragon", "Supreme Overlord"}
        ok, reason = NicknameGenerator.validate_custom_title("Deadline Dragon", taken)
        assert ok is False
        assert "already in use" in reason.lower()

    def test_uniqueness_ok(self) -> None:
        taken = {"Deadline Dragon"}
        ok, reason = NicknameGenerator.validate_custom_title("Coffee Wrangler", taken)
        assert ok is True

    def test_none_taken_titles(self) -> None:
        ok, reason = NicknameGenerator.validate_custom_title("Nice Title", None)
        assert ok is True
