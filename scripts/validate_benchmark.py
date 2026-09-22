"""Validate the v0.2 corpus and its generated manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qa_agent_lm.benchmark.corpus import build_manifest, load_corpus

ROOT = Path(__file__).resolve().parents[1] / "benchmark" / "v0.2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    cases = load_corpus(ROOT)
    expected = json.dumps(build_manifest(cases), indent=2, sort_keys=True) + "\n"
    path = ROOT / "manifest.json"
    if args.write_manifest:
        path.write_text(expected, encoding="utf-8", newline="\n")
    elif not path.is_file() or path.read_text(encoding="utf-8") != expected:
        raise ValueError("benchmark manifest is stale")
    print(f"Benchmark validation passed: {len(cases)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
