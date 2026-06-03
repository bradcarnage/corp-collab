"""Corp-Collab: nicknames module.

Role-flavored name pools, title progression, and manager renaming rights.
"""

from __future__ import annotations

import random
from typing import Optional

# ---------------------------------------------------------------------------
# Name pools keyed by role
# ---------------------------------------------------------------------------
NAME_POOLS: dict[str, list[str]] = {
    "researcher": [
        "Curie", "Volta", "Darwin", "Kepler", "Mendel", "Goodall",
        "Hawking", "Sagan", "Tesla", "Faraday", "Bohr", "Planck",
        "Fermi", "Pauling", "Hopper", "Babbage",
    ],
    "engineer": [
        "Lovelace", "Turing", "Knuth", "Torvalds", "Wozniak", "Carmack",
        "Hopper", "Dijkstra", "Ritchie", "Thompson", "Stallman",
        "Berners_Lee", "Gosling", "Kernighan", "VonNeumann", "Shannon",
    ],
    "reviewer": [
        "Jenkins", "Crawford", "Sterling", "Monroe", "Bishop", "Fletcher",
        "Marlowe", "Barrett", "Sinclair", "Whitfield", "Ashworth",
        "Pemberton", "Blackwood", "Prescott", "Langley", "Whitmore",
    ],
    "analyst": [
        "Nash", "Bayes", "Gauss", "Euler", "Fourier", "Markov",
        "Bernoulli", "Laplace", "Poisson", "Fisher", "Wald", "Tukey",
        "Benford", "Shannon", "Kolmogorov", "Pearson",
    ],
    "manager": [
        "Brandon", "Patel", "Chen", "Rodriguez", "Davis", "Margaret",
        "Thompson", "Nakamura", "Singh", "Mueller", "Petrov", "Santos",
        "Kim", "OBrien", "Yamamoto", "Garcia",
    ],
}

# ---------------------------------------------------------------------------
# Title progression
# ---------------------------------------------------------------------------
TITLE_LEVELS: dict[str, str] = {
    "intern": "Intern",
    "senior": "Senior",
    "lead": "Lead",
    "director": "Director",
}

# Role-specific display names used at the "role" level
ROLE_DISPLAY: dict[str, str] = {
    "researcher": "Researcher",
    "engineer": "Engineer",
    "reviewer": "Reviewer",
    "analyst": "Analyst",
    "manager": "Manager",
}

# ---------------------------------------------------------------------------
# Blocklist for custom manager titles
# ---------------------------------------------------------------------------
BLOCKLIST: set[str] = {
    "ass", "asshole", "bastard", "bitch", "bullshit", "crap", "cunt",
    "damn", "dick", "douche", "dumbass", "fuck", "fucker", "fucking",
    "hell", "idiot", "jerk", "moron", "nazi", "nigger", "piss",
    "prick", "racist", "rape", "retard", "sexist", "shit", "slut",
    "stupid", "twat", "whore",
}

# Maximum length for a custom title
MAX_TITLE_LENGTH = 40


class NicknameGenerator:
    """Generates role-flavoured nicknames with title progression.

    Usage::

        gen = NicknameGenerator()
        nick = gen.generate("engineer")           # e.g. "Turing"
        title = gen.get_title("engineer", "senior")  # "Senior"
        full  = gen.full_name(title, nick)         # "Senior Turing"
    """

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Name generation
    # ------------------------------------------------------------------

    def generate(self, role: str, exclude: Optional[set[str]] = None) -> str:
        """Return a nickname from *role*'s pool not in *exclude*.

        If every base name is taken, append increasing numeric suffixes
        (e.g. ``Curie-2``, ``Curie-3``) until a fresh name is found.
        """
        role = role.lower()
        pool = NAME_POOLS.get(role)
        if pool is None:
            raise ValueError(f"Unknown role {role!r}. Choose from {sorted(NAME_POOLS)}")

        exclude = exclude or set()

        available = [n for n in pool if n not in exclude]
        if available:
            return self._rng.choice(available)

        # Pool exhausted – generate suffixed variants
        suffix = 2
        while True:
            candidates = [f"{n}-{suffix}" for n in pool if f"{n}-{suffix}" not in exclude]
            if candidates:
                return self._rng.choice(candidates)
            suffix += 1  # pragma: no cover – safety valve

    # ------------------------------------------------------------------
    # Title helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_title(role: str, level: str) -> str:
        """Return the title prefix for a given *role* at *level*.

        Levels: ``intern``, ``role``, ``senior``, ``lead``, ``director``.
        """
        level = level.lower()
        if level == "role":
            role = role.lower()
            display = ROLE_DISPLAY.get(role)
            if display is None:
                raise ValueError(f"Unknown role {role!r}")
            return display
        title = TITLE_LEVELS.get(level)
        if title is None:
            raise ValueError(
                f"Unknown level {level!r}. Choose from: intern, role, senior, lead, director"
            )
        return title

    @staticmethod
    def full_name(title: str, nickname: str) -> str:
        """Format ``'{title} {nickname}'``."""
        return f"{title} {nickname}"

    # ------------------------------------------------------------------
    # Manager renaming rights
    # ------------------------------------------------------------------

    @staticmethod
    def validate_custom_title(
        title: str,
        taken_titles: Optional[set[str]] = None,
    ) -> tuple[bool, str]:
        """Validate a custom seniority title for a manager.

        Returns ``(True, 'ok')`` on success or ``(False, reason)`` on
        failure.  Checks:

        * Non-empty and within length limit
        * No blocked words (case-insensitive token check)
        * Unique among *taken_titles*
        """
        taken_titles = taken_titles or set()

        # Basic sanity
        stripped = title.strip()
        if not stripped:
            return False, "Title cannot be empty"
        if len(stripped) > MAX_TITLE_LENGTH:
            return False, f"Title exceeds {MAX_TITLE_LENGTH} characters"

        # Blocklist check – tokenise on whitespace and compare lowercase
        words = stripped.lower().split()
        for word in words:
            if word in BLOCKLIST:
                return False, f"Title contains blocked word: {word!r}"

        # Uniqueness
        if stripped in taken_titles:
            return False, "Title is already in use by another manager"

        return True, "ok"
