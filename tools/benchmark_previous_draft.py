#!/usr/bin/env python3
"""Compare Gemini full-prefix rewrites with previous-draft continuity.

The source transcript is read locally.  Neither source sentences nor API keys
are written to the repository; the JSON report defaults to the ignored logs/
directory.
"""

from argparse import ArgumentParser
from difflib import SequenceMatcher
import json
from pathlib import Path
import statistics
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config  # noqa: E402
from translator import Translator  # noqa: E402


def load_pairs(path):
    pairs = []
    pending_english = None
    for raw_line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if line.startswith("英语:"):
            pending_english = line.removeprefix("英语:").strip()
        elif line.startswith("中文 (简体):") and pending_english:
            chinese = line.removeprefix("中文 (简体):").strip()
            word_count = len(pending_english.split())
            if 12 <= word_count <= 42 and chinese:
                pairs.append((pending_english, chinese))
            pending_english = None
    return pairs


def evenly_spaced(values, count):
    if len(values) <= count:
        return list(values)
    return [
        values[round(index * (len(values) - 1) / (count - 1))]
        for index in range(count)
    ]


def retained_old_ratio(previous, current):
    if not previous:
        return 0.0
    matcher = SequenceMatcher(None, previous, current, autojunk=False)
    preserved = sum(block.size for block in matcher.get_matching_blocks())
    return preserved / len(previous)


def similarity(left, right):
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def percentile(values, ratio):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[round((len(ordered) - 1) * ratio)]


def timed_translate(translator, source, **kwargs):
    started = time.perf_counter()
    result = translator.translate(
        source,
        use_context=False,
        remember_context=False,
        deadline=time.monotonic() + 5.0,
        **kwargs,
    )
    return result, (time.perf_counter() - started) * 1000


def run(args):
    config = Config()
    if not config.gemini_api_key:
        raise SystemExit("Gemini Key is not configured in macOS Keychain")
    pairs = evenly_spaced(load_pairs(args.input), args.count)
    if len(pairs) < args.count:
        raise SystemExit(f"Only {len(pairs)} suitable sentence pairs found")

    translator = Translator(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=config.gemini_api_key,
        model="gemini-3.5-flash-lite",
        target_lang=config.target_lang,
        domain_prompt=config.translation_domain,
        glossary_path=config.glossary_path,
        deadline_seconds=5.0,
    )
    try:
        translator.warmup(timeout=3.0)
    except Exception:
        pass

    rows = []
    prior_sources = []
    for index, (source, reference) in enumerate(pairs, 1):
        words = source.split()
        prefix_word_count = min(
            len(words) - 1,
            max(5, round(len(words) * 0.45)),
        )
        prefix_source = " ".join(words[:prefix_word_count])
        context_text = "\n".join(prior_sources[-4:]) or None
        prefix, prefix_ms = timed_translate(
            translator,
            prefix_source,
            context_text=context_text,
        )

        # Alternate order to reduce bias from transient network changes.
        if index % 2:
            baseline, baseline_ms = timed_translate(
                translator, source, context_text=context_text
            )
            treatment, treatment_ms = timed_translate(
                translator,
                source,
                context_text=context_text,
                previous_preview=prefix,
            )
        else:
            treatment, treatment_ms = timed_translate(
                translator,
                source,
                context_text=context_text,
                previous_preview=prefix,
            )
            baseline, baseline_ms = timed_translate(
                translator, source, context_text=context_text
            )

        row = {
            "index": index,
            "words": len(words),
            "prefix_words": prefix_word_count,
            "prefix_ms": round(prefix_ms, 1),
            "baseline_ms": round(baseline_ms, 1),
            "previous_draft_ms": round(treatment_ms, 1),
            "baseline_retention": round(
                retained_old_ratio(prefix, baseline), 4
            ),
            "previous_draft_retention": round(
                retained_old_ratio(prefix, treatment), 4
            ),
            "baseline_reference_similarity": round(
                similarity(reference, baseline), 4
            ),
            "previous_draft_reference_similarity": round(
                similarity(reference, treatment), 4
            ),
            # Samples are useful for local review; logs/ is gitignored.
            "source": source,
            "reference": reference,
            "prefix_translation": prefix,
            "baseline": baseline,
            "previous_draft": treatment,
        }
        rows.append(row)
        prior_sources.append(source)
        print(
            f"[{index:02d}/{len(pairs)}] "
            f"baseline={baseline_ms:.0f}ms previous={treatment_ms:.0f}ms "
            f"retention={row['baseline_retention']:.0%}→"
            f"{row['previous_draft_retention']:.0%}",
            flush=True,
        )

    baseline_latency = [row["baseline_ms"] for row in rows]
    treatment_latency = [row["previous_draft_ms"] for row in rows]
    baseline_retention = [row["baseline_retention"] for row in rows]
    treatment_retention = [row["previous_draft_retention"] for row in rows]
    baseline_quality = [row["baseline_reference_similarity"] for row in rows]
    treatment_quality = [
        row["previous_draft_reference_similarity"] for row in rows
    ]
    summary = {
        "sentences": len(rows),
        "baseline_latency_mean_ms": round(statistics.mean(baseline_latency), 1),
        "previous_draft_latency_mean_ms": round(
            statistics.mean(treatment_latency), 1
        ),
        "baseline_latency_p50_ms": round(percentile(baseline_latency, 0.5), 1),
        "previous_draft_latency_p50_ms": round(
            percentile(treatment_latency, 0.5), 1
        ),
        "baseline_retention_mean": round(statistics.mean(baseline_retention), 4),
        "previous_draft_retention_mean": round(
            statistics.mean(treatment_retention), 4
        ),
        "baseline_reference_similarity_mean": round(
            statistics.mean(baseline_quality), 4
        ),
        "previous_draft_reference_similarity_mean": round(
            statistics.mean(treatment_quality), 4
        ),
    }
    summary["recommended"] = bool(
        summary["previous_draft_retention_mean"]
        >= summary["baseline_retention_mean"] + 0.05
        and summary["previous_draft_latency_p50_ms"]
        <= summary["baseline_latency_p50_ms"] + 150
        and summary["previous_draft_reference_similarity_mean"]
        >= summary["baseline_reference_similarity_mean"] - 0.03
    )
    report = {"summary": summary, "rows": rows}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"Report: {output}", flush=True)


def main():
    parser = ArgumentParser()
    parser.add_argument(
        "--input",
        default="/Users/ywbw/Desktop/文本-9E916F5EE5BF-1.txt",
    )
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "logs/previous_draft_ab.json"),
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
