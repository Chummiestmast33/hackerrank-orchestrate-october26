"""Parser CLI: ``python code/src/loaders/cli.py parse-all``.

One pass over the evidence manifest, reusing the aggressive disk cache for files
whose sha256 and ``PARSER_VERSION`` are unchanged. Offline by default: PNGs are
decoded only from the committed transcription store. ``--extract-images`` allows
metered vision model calls for images missing from the store (requires
credentials). Exits 0 (clean), 1 (any PARSE_ERROR; with ``--strict`` also
UNKNOWN_STATE) or 2 (manifest/usage error).
"""

import argparse
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = CODE_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from src import config as app_config  # noqa: E402
from src.evaluation.metering import Meter  # noqa: E402
from src.loaders.cache import (  # noqa: E402
    ParseAllResult,
    build_census,
    load_evidence_index,
    parse_all,
)
from src.loaders.csv_loader import (  # noqa: E402
    load_activity,
    load_audit_log,
    load_evidence_manifest,
    load_identities,
)
from src.loaders.transcription_validator import build_known_identifiers  # noqa: E402
from src.loaders.vlm_extractor import (  # noqa: E402
    UnsupportedVisionProvider,
    VisionConfig,
)
from src.models import ParseStatus  # noqa: E402

DEFAULT_STORE = CODE_DIR / "data" / "multimodal_transcriptions.json"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py parse-all",
        description="Parse all evidence files into the aggressive local cache.",
    )
    parser.add_argument("command", nargs="?", default="parse-all", choices=["parse-all"])
    parser.add_argument("--dataset", type=Path, default=REPO_ROOT / "dataset")
    parser.add_argument(
        "--cache",
        type=Path,
        default=CODE_DIR / "cache" / "parsed_evidence.json",
        help="cache artifact path (gitignored, reused forever while content is unchanged)",
    )
    parser.add_argument(
        "--transcription-store",
        type=Path,
        default=DEFAULT_STORE,
        help="vision transcription store (committed; offline runs only read it)",
    )
    parser.add_argument(
        "--extract-images",
        action="store_true",
        help="allow metered vision model calls for PNGs missing from the store",
    )
    parser.add_argument(
        "--force", action="store_true", help="ignore the cache and reparse everything"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any file reports UNKNOWN_STATE in addition to PARSE_ERROR",
    )
    parser.add_argument("--quiet", action="store_true", help="only print totals and errors")
    return parser


def exit_code(result: ParseAllResult, strict: bool) -> int:
    statuses = {
        entry.report.status for entry in result.entries.values() if entry.report is not None
    }
    if ParseStatus.PARSE_ERROR in statuses:
        return 1
    if strict and ParseStatus.UNKNOWN_STATE in statuses:
        return 1
    return 0


def _family_rows(census: dict[str, dict]) -> dict[str, dict]:
    families: dict[str, dict] = {}
    for entry in census.values():
        family = families.setdefault(
            entry["family"],
            {"files": 0, "observations": 0, "statuses": {}, "states": {}},
        )
        family["files"] += 1
        family["observations"] += entry["observations"]
        status = entry["status"]
        family["statuses"][status] = family["statuses"].get(status, 0) + 1
        for state, count in entry["states"].items():
            family["states"][state] = family["states"].get(state, 0) + count
    return families


def _multimodal_counts(result: ParseAllResult) -> dict[str, int]:
    counts = {"pdf_ok": 0, "pdf_other": 0, "png_ok": 0, "png_unsupported": 0, "png_other": 0}
    for entry in result.entries.values():
        report = entry.report
        if report is None:
            continue
        if report.family.startswith("pdf:"):
            key = "pdf_ok" if report.status is ParseStatus.OK else "pdf_other"
        elif report.family.startswith("png:"):
            if report.status is ParseStatus.OK:
                key = "png_ok"
            elif report.status is ParseStatus.UNSUPPORTED_FORMAT:
                key = "png_unsupported"
            else:
                key = "png_other"
        else:
            continue
        counts[key] += 1
    return counts


def print_census(result: ParseAllResult, quiet: bool = False, model_calls: int = 0) -> None:
    census = build_census(result.entries)
    if not quiet:
        families = _family_rows(census)
        widths = (6, 8)
        header = f"{'family':32} {'files':>{widths[0]}} {'obs':>{widths[1]}}  statuses / states"
        print("== parse census ==")
        print(header)
        for family in sorted(families):
            row = families[family]
            statuses = ", ".join(f"{k}:{v}" for k, v in sorted(row["statuses"].items()))
            states = ", ".join(f"{k}:{v}" for k, v in sorted(row["states"].items()))
            print(
                f"{family:32} {row['files']:>{widths[0]}} {row['observations']:>{widths[1]}}  "
                f"{statuses}" + (f" | {states}" if states else "")
            )
        print()
    stats = result.stats
    print(
        f"totals: files={stats.files} observations={stats.observations} "
        f"cache_hits={stats.hits} cache_misses={stats.misses} "
        f"unsupported={stats.unsupported} errors={stats.errors}"
    )
    counts = _multimodal_counts(result)
    summary = " ".join(f"{key}={value}" for key, value in counts.items())
    print(f"multimodal: {summary} model_calls_this_run={model_calls}")
    problems = [
        (file_id, entry.report.errors)
        for file_id, entry in sorted(result.entries.items())
        if entry.report is not None and entry.report.errors
    ]
    for file_id, errors in problems:
        print(f"  {file_id}: {len(errors)} error(s)")
        for error in errors[:10]:
            print(f"    - {error}")


def _usage_line_count() -> int:
    path = app_config.USAGE_LOG_PATH
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _load_known_identifiers(dataset_dir: Path, cache_path: Path) -> set[str]:
    identities, _ = load_identities(dataset_dir / "user_identities.csv")
    audit_log, _ = load_audit_log(dataset_dir / "user_audit_log.csv")
    observations = []
    if cache_path.exists():
        index, _ = load_evidence_index(cache_path)
        observations = [
            observation
            for observation_list, _report in index.values()
            for observation in observation_list
        ]
    return build_known_identifiers(identities, audit_log, observations)


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    manifest_path = args.dataset / "evidence_files.csv"
    manifest, manifest_errors = load_evidence_manifest(manifest_path)
    if manifest_errors:
        for error in manifest_errors:
            print(error)
        return 2
    meter: Meter | None = None
    vision_config: VisionConfig | None = None
    try:
        vision_config = VisionConfig.from_env()
    except UnsupportedVisionProvider as exc:
        if args.extract_images:
            print(f"error: {exc}")
            return 2
    if args.extract_images:
        if vision_config is None or not vision_config.available():
            print(
                "error: --extract-images requires DASHSCOPE_API_KEY (qwen) "
                "or OPENAI_API_KEY (openai) in the environment"
            )
            return 2
        meter = Meter(run_id="phase4-extraction")
    activity_rows, _ = load_activity(args.dataset / "system_activity.csv")
    known_identifiers = _load_known_identifiers(args.dataset, args.cache)
    usage_before = _usage_line_count()
    result = parse_all(
        manifest,
        dataset_dir=args.dataset,
        cache_path=args.cache,
        force=args.force,
        allow_model_calls=args.extract_images,
        vision_config=vision_config,
        meter=meter,
        transcription_store_path=args.transcription_store,
        activity=activity_rows,
        known_identifiers=known_identifiers,
    )
    usage_after = _usage_line_count()
    print_census(result, quiet=args.quiet, model_calls=usage_after - usage_before)
    return exit_code(result, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
