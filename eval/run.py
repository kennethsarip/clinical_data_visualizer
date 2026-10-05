"""Run the eval set live and save the results (CLAUDE.md §5, §14 Phase 5):

    uv run --env-file .env python -m eval.run eval/results/<name>.json [--only ID ...]

Needs the Compose Postgres (migrated), an OpenAI key and the ClinicalTrials.gov API. Responses go
through the cache like any request, so a rerun on a warm cache is faster; latency is comparable
only between runs with the same cache state.
"""

import argparse
import logging
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.cache import TrialCache
from app.config import load_settings
from app.ctgov import CtgovClient
from app.llm import LLMClient
from app.pipeline import Checker, Pipeline
from eval.questions import load_question_set
from eval.runner import RunMeta, RunResult, run_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="where to write the results JSON")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run just these question ids")
    args = parser.parse_args(argv)
    # Progress from the runner; only warnings from the app (cache hits would bury the progress).
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("eval").setLevel(logging.INFO)

    question_set = load_question_set()
    questions = [q for q in question_set.questions if not args.only or q.id in args.only]
    if args.only and len(questions) != len(set(args.only)):
        parser.error(f"unknown question ids: {sorted(set(args.only) - {q.id for q in questions})}")
    settings = load_settings()
    today = date.fromisoformat(question_set.written)  # relative years mean what they meant then
    meta = RunMeta(
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        git_commit=_git_commit(),
        model=settings.openai_model,
        reasoning_effort=settings.openai_reasoning_effort,
        fetch_cap=settings.fetch_cap,
        today=today,
        questions_written=question_set.written,
    )
    llm = LLMClient.from_settings(settings)
    url = settings.database_url.get_secret_value()
    with psycopg.connect(url, autocommit=True) as conn:
        cache = TrialCache(conn, CtgovClient.from_settings(settings), settings.cache_ttl_hours)

        def make_pipeline(checker: Checker) -> Pipeline:
            return Pipeline(llm, cache, checker=checker, today=lambda: today)

        run = run_all(questions, make_pipeline, meta)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(run.model_dump_json(indent=2) + "\n")
    sys.stdout.write(_report(run))
    return 0


def _git_commit() -> str:
    """The commit the run measured, marked dirty if uncommitted changes could affect it."""
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD"], check=False).returncode != 0
    return f"{sha}-dirty" if dirty else sha


def _report(run: RunResult) -> str:
    s = run.summary
    lines = [f"\n{s.passed}/{s.questions} passed ({run.meta.model}, {run.meta.git_commit})"]
    lines += [f"  {cls}: {p}/{n}" for cls, (p, n) in sorted(s.by_class.items())]
    lines += [f"  failure {mode}: {count}" for mode, count in sorted(s.failure_modes.items())]
    lines.append(f"  repaired {s.repaired}, prose fallbacks {s.prose_fallbacks}")
    lines.append(f"  latency median {s.latency_p50_s:.1f} s, max {s.latency_max_s:.1f} s")
    lines.append(f"  items fully cited {s.items_fully_cited}/{s.items}")
    lines.append(f"  excerpts passed {s.excerpts_passed}/{s.citations}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
