"""Explicit, course-scoped terminology profiles.

Profiles are selected only from the session topic entered by the user.  They
never guess from live speech, so a correction valid in one subject cannot leak
into an unrelated class.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CourseProfile:
    name: str
    glossary_path: str
    corrections_path: str


_ROOT = Path(__file__).resolve().parent / "course_profiles"
_PROFILES = (
    (
        (
            "comp90054",
            "planning for autonomy",
            "blind search",
            "breadth-first",
            "depth-first",
            "uniform-cost",
            "uniform cost search",
        ),
        CourseProfile(
            name="COMP90054 Planning for Autonomy",
            glossary_path=str(_ROOT / "comp90054" / "glossary.tsv"),
            corrections_path=str(_ROOT / "comp90054" / "corrections.tsv"),
        ),
    ),
)


def resolve_course_profile(topic):
    """Resolve an optional profile from an explicitly entered session topic."""
    normalized = " ".join(str(topic or "").casefold().split())
    if not normalized:
        return None
    for markers, profile in _PROFILES:
        if any(marker in normalized for marker in markers):
            return profile
    return None


def glossary_paths(base_path, topic):
    profile = resolve_course_profile(topic)
    return tuple(
        path for path in (
            base_path,
            profile.glossary_path if profile else None,
        ) if path
    )


def correction_paths(base_path, topic):
    profile = resolve_course_profile(topic)
    return tuple(
        path for path in (
            base_path,
            profile.corrections_path if profile else None,
        ) if path
    )
