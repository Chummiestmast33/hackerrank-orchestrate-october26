"""Parser CLI: ``python code/src/loaders/cli.py parse-all``.

One pass over the evidence manifest, reusing the aggressive disk cache for files
whose sha256 and ``PARSER_VERSION`` are unchanged. Prints a family census and
exits 0 (clean), 1 (any PARSE_ERROR; with ``--strict`` also UNKNOWN_STATE) or 2
(manifest/usage error).
"""

import argparse
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = CODE_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from src.loaders.cache import ParseAllResult, build_census, parse_all  # noqa: E402
from src.loaders.csv_loader import load_evidence_manifest  # noqa: E402
from src.models import ParseStatus  # noqa: E402


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


def print_census(result: ParseAllResult, quiet: bool = False) -> None:
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
    problems = [
        (file_id, entry.report.errors)
        for file_id, entry in sorted(result.entries.items())
        if entry.report is not None and entry.report.errors
    ]
    for file_id, errors in problems:
        print(f"  {file_id}: {len(errors)} error(s)")
        for error in errors[:10]:
            print(f"    - {error}")


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    manifest_path = args.dataset / "evidence_files.csv"
    manifest, manifest_errors = load_evidence_manifest(manifest_path)
    if manifest_errors:
        for error in manifest_errors:
            print(error)
        return 2
    result = parse_all(
        manifest,
        dataset_dir=args.dataset,
        cache_path=args.cache,
        force=args.force,
    )
    print_census(result, quiet=args.quiet)
    return exit_code(result, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
