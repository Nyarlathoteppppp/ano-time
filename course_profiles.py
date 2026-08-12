"""Explicit, file-backed lecture profiles.

A profile is selected in the control center and captured once per Launch.  It
does not infer a course from live speech or from free-form lecture-topic text:
that would allow an unrelated keyword to activate the wrong ASR correction.
"""

from dataclasses import dataclass
import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parent / "course_profiles"


@dataclass(frozen=True, slots=True)
class CourseProfile:
    """Portable metadata plus optional terminology assets for one subject."""

    id: str
    name: str
    domain: str
    glossary_path: str | None = None
    corrections_path: str | None = None
    do_not_translate_path: str | None = None

    @property
    def label(self):
        return self.name


def _asset(profile_id, filename):
    path = _ROOT / profile_id / filename
    return str(path) if path.is_file() else None


def _profile(profile_id, metadata):
    name = " ".join(str(metadata.get("name", "")).split())
    domain = " ".join(str(metadata.get("domain", "")).split())
    if (
        not profile_id
        or not name
        or not domain
        or any(character.isspace() for character in profile_id)
        or any(character in profile_id for character in "/\\")
    ):
        return None
    return CourseProfile(
        id=profile_id,
        name=name,
        domain=domain,
        glossary_path=_asset(profile_id, "glossary.tsv"),
        corrections_path=_asset(profile_id, "corrections.tsv"),
        do_not_translate_path=_asset(profile_id, "do_not_translate.txt"),
    )


def _load_profiles(root=_ROOT):
    """Discover editable profile folders without importing user course material."""
    profiles = []
    for metadata_path in sorted(root.glob("*/profile.json")):
        try:
            with metadata_path.open(encoding="utf-8") as handle:
                metadata = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        profile = _profile(metadata_path.parent.name, metadata)
        if profile:
            profiles.append(profile)
    return tuple(profiles)


# Names live in editable profile.json files and intentionally omit university
# course codes, making them usable as examples in every installation.
_PROFILES = _load_profiles()
_BY_ID = {profile.id: profile for profile in _PROFILES}


def available_course_profiles():
    """Return profiles in stable UI order; callers must not mutate them."""
    return _PROFILES


def resolve_course_profile(profile_id):
    """Resolve only an explicit persisted profile id; blank means no profile."""
    return _BY_ID.get(str(profile_id or "").strip())


def selected_course_profile(settings):
    return resolve_course_profile(getattr(settings, "course_profile_id", ""))


def profile_domain(default_domain, profile_id):
    """A selected profile replaces only the generic default discipline prompt."""
    profile = resolve_course_profile(profile_id)
    return profile.domain if profile else str(default_domain or "")


def glossary_paths(base_path, profile_id=""):
    profile = resolve_course_profile(profile_id)
    return tuple(
        path for path in (
            base_path,
            profile.glossary_path if profile else None,
        ) if path
    )


def correction_paths(base_path, profile_id=""):
    profile = resolve_course_profile(profile_id)
    return tuple(
        path for path in (
            base_path,
            profile.corrections_path if profile else None,
        ) if path
    )


def do_not_translate_paths(profile_id=""):
    """Return only explicit profile protection terms.

    They intentionally do not share the legacy global glossary path: a course
    profile is opt-in and should never make an unrelated installation preserve
    someone's private subject vocabulary.
    """
    profile = resolve_course_profile(profile_id)
    return (profile.do_not_translate_path,) if profile and profile.do_not_translate_path else ()
