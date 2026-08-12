from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class GlossaryMatch:
    source: str
    target: str


class CourseGlossary:
    """Small editable glossary with per-sentence, longest-term matching."""

    def __init__(self, entries=()):
        prepared = []
        seen = set()
        for source, target in entries:
            source = source.strip()
            target = target.strip()
            key = source.casefold()
            if not source or not target or key in seen:
                continue
            seen.add(key)
            # Permit an English plural suffix while keeping strict word boundaries.
            suffix = "" if source[-1:].casefold() == "s" else r"(?:s|es)?"
            pattern = re.compile(
                rf"(?<!\w){re.escape(source)}{suffix}(?!\w)",
                re.IGNORECASE,
            )
            prepared.append((source, target, pattern))
        self._entries = sorted(prepared, key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def from_file(cls, path):
        return cls.from_files((path,))

    @classmethod
    def from_files(cls, paths):
        if isinstance(paths, (str, os.PathLike)):
            paths = (paths,)
        entries = []
        loaded = []
        for path in paths or ():
            if not path or not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, 1):
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) != 2 or not all(part.strip() for part in parts):
                        print(f"[Glossary] Ignoring malformed line {line_number}: {path}")
                        continue
                    entries.append(parts)
            loaded.append(path)
        glossary = cls(entries)
        if loaded:
            print(f"[Glossary] Loaded {len(glossary)} terms from {', '.join(loaded)}")
        return glossary

    def match(self, text, limit=12):
        matches = []
        occupied = []
        for _, target, pattern in self._entries:
            found = pattern.search(text)
            if not found:
                continue
            span = found.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            occupied.append(span)
            matches.append(GlossaryMatch(found.group(0), target))
            if len(matches) >= limit:
                break
        return matches

    def __len__(self):
        return len(self._entries)


class DoNotTranslateTerms:
    """Small profile-owned list of technical tokens to preserve verbatim.

    The matcher is deliberately local and bounded.  It never rewrites source
    text or calls a service; it merely gives the remote model a short explicit
    protection list for the current sentence.
    """

    def __init__(self, terms=()):
        prepared = []
        seen = set()
        for raw_term in terms:
            term = str(raw_term).strip()
            key = term.casefold()
            if not term or key in seen:
                continue
            seen.add(key)
            prepared.append((
                term,
                re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE),
            ))
        self._terms = sorted(prepared, key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def from_files(cls, paths):
        if isinstance(paths, (str, os.PathLike)):
            paths = (paths,)
        terms = []
        for path in paths or ():
            if not path or not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                terms.extend(
                    line.strip() for line in handle
                    if line.strip() and not line.lstrip().startswith("#")
                )
        return cls(terms)

    def match(self, text, limit=8):
        matches = []
        occupied = []
        for term, pattern in self._terms:
            found = pattern.search(text or "")
            if not found:
                continue
            start, end = found.span()
            if any(start < used_end and used_start < end for used_start, used_end in occupied):
                continue
            occupied.append((start, end))
            matches.append(term)
            if len(matches) >= limit:
                break
        return matches


class ASRCorrections:
    """Conservative, editable replacements applied only to finalized ASR."""

    def __init__(self, entries=()):
        prepared = []
        for source, target in entries:
            source = source.strip()
            target = target.strip()
            if source and target:
                prepared.append((
                    re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE),
                    target,
                ))
        self._entries = sorted(prepared, key=lambda item: len(item[0].pattern), reverse=True)

    @classmethod
    def from_file(cls, path):
        return cls.from_files((path,))

    @classmethod
    def from_files(cls, paths):
        if isinstance(paths, (str, os.PathLike)):
            paths = (paths,)
        entries = []
        for path in paths or ():
            if not path or not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        entries.append(parts)
        return cls(entries)

    def apply(self, text):
        corrected = text
        for pattern, target in self._entries:
            corrected = pattern.sub(target, corrected)
        return corrected
