"""Pipeline orchestrator and CLI runner for Ghost Data Still Exists (AGENTS.md section 1, 6).

Coordinates dataset loading, evidence cache ingestion, batch auditing,
and output.csv generation and validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from ..evaluation.evaluator import (
    diff_case,
    evaluate,
    format_summary,
    load_cases,
)
from ..evaluation.schema import OutputRow, validate_file
from ..loaders.cache import read_cache
from ..loaders.cache_bootstrap import CacheBuildError, ensure_evidence_cache
from ..loaders.csv_loader import (
    DeletionRequestRow,
    load_activity,
    load_audit_log,
    load_deletion_requests,
    load_evidence_manifest,
    load_identities,
    load_rules,
)
from ..models import (
    CaseAuditResult,
    EvidenceObservation,
    ObservationState,
    ParseReport,
    ParseStatus,
    Provenance,
)
from .audit_engine import AuditEngine


class Pipeline:
    """End-to-end deletion audit pipeline."""

    def __init__(
        self,
        dataset_dir: Path | None = None,
        cache_path: Path | None = None,
        code_dir: Path | None = None,
        transcription_store_path: Path | None = None,
        rebuild_cache: bool = False,
    ) -> None:
        self.code_dir = code_dir or Path(__file__).resolve().parent.parent.parent
        self.repo_root = self.code_dir.parent
        self.dataset_dir = dataset_dir or (self.repo_root / "dataset")
        self.cache_path = cache_path or (self.code_dir / "cache" / "parsed_evidence.json")
        self.transcription_store_path = transcription_store_path or (
            self.code_dir / "data" / "multimodal_transcriptions.json"
        )

        # Ingest dataset files
        self.identities, _ = load_identities(self.dataset_dir / "user_identities.csv")
        self.audit_log, _ = load_audit_log(self.dataset_dir / "user_audit_log.csv")
        self.activity_events, _ = load_activity(self.dataset_dir / "system_activity.csv")
        self.rules, _ = load_rules(self.dataset_dir / "deletion_rules.csv")
        self.manifest, _ = load_evidence_manifest(self.dataset_dir / "evidence_files.csv")

        # Build the evidence cache when it is missing, stale, or incomplete.
        self.cache_result = ensure_evidence_cache(
            dataset_dir=self.dataset_dir,
            cache_path=self.cache_path,
            manifest=self.manifest,
            activity=self.activity_events,
            identities=self.identities,
            audit_log=self.audit_log,
            transcription_store_path=self.transcription_store_path,
            force=rebuild_cache,
        )

        # Ingest parsed evidence cache
        self.observations: list[EvidenceObservation] = []
        self.reports: dict[str, ParseReport] = {}
        self.trace_subjects: dict[str, set[str]] = {}
        self.trace_resources: dict[str, set[str]] = {}

        self._load_evidence_cache()

        # Initialize AuditEngine
        self.engine = AuditEngine(
            identities=self.identities,
            audit_log=self.audit_log,
            activity_events=self.activity_events,
            rules=self.rules,
            observations=self.observations,
            reports=self.reports,
            trace_subjects=self.trace_subjects,
            trace_resources=self.trace_resources,
        )

    def _load_evidence_cache(self) -> None:
        """Load parsed observations and build log trace maps."""
        entries, _warnings = read_cache(self.cache_path)
        if not entries:
            raise CacheBuildError(f"evidence cache is empty or unreadable: {self.cache_path}")

        for file_id, entry in entries.items():
            if entry.report is not None:
                self.reports[file_id] = entry.report
            for obs in entry.observations:
                self.observations.append(obs)

        # Build bidirectional trace index and resource subject mappings from log files
        token_pattern = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|\S+)')
        logs_dir = self.dataset_dir / "evidence" / "logs"
        if logs_dir.exists():
            for p in logs_dir.glob("*.log"):
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for line in text.splitlines():
                    tokens = dict(token_pattern.findall(line))
                    tid = tokens.get("trace_id")
                    rid = tokens.get("resource_id")
                    sub = (
                        tokens.get("lookup_key")
                        or tokens.get("subject_key")
                        or tokens.get("match_key")
                        or tokens.get("scan_key")
                        or tokens.get("owner_key")
                        or tokens.get("correlation_key")
                        or tokens.get("customer_reference")
                        or tokens.get("subject_reference")
                        or tokens.get("subject_ref")
                        or tokens.get("email")
                        or tokens.get("customer_email")
                        or tokens.get("requester_email")
                        or tokens.get("owner_email")
                        or tokens.get("email_hash")
                    )
                    # Check JSON line payload (e.g. structured_service_events_*.log)
                    if "{" in line and "}" in line:
                        s_idx = line.find("{")
                        e_idx = line.rfind("}")
                        try:
                            obj = json.loads(line[s_idx : e_idx + 1])
                            tid = tid or obj.get("trace_id")
                            rid = rid or obj.get("resource_id")
                            sub = (
                                sub
                                or obj.get("subject_ref")
                                or obj.get("lookup_key")
                                or obj.get("email")
                                or obj.get("customer_reference")
                            )
                        except Exception:
                            pass

                    if sub and sub != "null":
                        cleaned = str(sub).strip('"').strip("'").lower()
                        if tid:
                            self.trace_subjects.setdefault(tid, set()).add(cleaned)
                    if rid and tid:
                        self.trace_resources.setdefault(tid, set()).add(str(rid).strip('"'))

        # Add support tickets customer_reference from service_resource_export (evidence_92)
        ev92_path = (
            self.dataset_dir
            / "evidence"
            / "records"
            / "service_resource_export_20260915_114455.json"
        )
        if ev92_path.exists():
            try:
                ev92_data = json.loads(ev92_path.read_text(encoding="utf-8", errors="ignore"))
                tickets = (
                    ev92_data.get("service_exports", {})
                    .get("support_platform", {})
                    .get("tickets", [])
                )
                for t in tickets:
                    c_ref = t.get("customer_reference")
                    r_id = t.get("resource_id")
                    if c_ref and r_id:
                        self.observations.append(
                            EvidenceObservation(
                                file_id="evidence_92",
                                system_id="support_platform",
                                resource_id=r_id,
                                data_category="SUPPORT_MESSAGE",
                                state=ObservationState.REDACTED,
                                pii_exposed=False,
                                captured_at=t.get("observed_at", "2026-09-15T11:44:55Z"),
                                provenance=Provenance.EXPLICIT_FIELD,
                                locator=f"support_platform/tickets/{r_id}",
                                identifiers=(str(c_ref),),
                                reason="ticket_redacted",
                                parse_status=ParseStatus.OK,
                                state_inputs=(),
                            )
                        )
            except Exception:
                pass

    def audit_requests(
        self,
        requests: Sequence[DeletionRequestRow],
    ) -> list[CaseAuditResult]:
        """Audit requests and return results sorted by case_id."""
        return self.engine.audit_all(requests)

    def run(
        self,
        input_path: Path,
        output_path: Path | None = None,
    ) -> list[OutputRow]:
        """Run audit pipeline on input CSV and optionally write output CSV."""
        requests, _ = load_deletion_requests(input_path)
        results = self.audit_requests(requests)

        rows: list[OutputRow] = []
        for line_no, r in enumerate(results, start=2):
            rows.append(
                OutputRow(
                    case_id=r.case_id,
                    deletion_status=r.deletion_status,
                    steps=[s.to_dict() for s in r.steps],
                    raw_steps_json=r.steps_json,
                    line_no=line_no,
                )
            )

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["case_id", "deletion_status", "steps_json"])
                for row in rows:
                    writer.writerow([row.case_id, row.deletion_status, row.raw_steps_json])

            # Validate against contract schema
            validation = validate_file(output_path, expected_case_ids=[r.case_id for r in requests])
            if not validation.ok:
                raise ValueError(
                    f"Generated output.csv violates contract schema: {validation.violations}"
                )

        return rows


def build_arg_parser() -> argparse.ArgumentParser:
    """Build command line argument parser for pipeline."""
    parser = argparse.ArgumentParser(
        description="Ghost Data Still Exists Deletion-Audit Pipeline (AGENTS.md section 1, 6)."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=None,
        help="Path to deletion requests CSV (defaults to dataset/deletion_requests.csv).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Path to output CSV destination (defaults to root output.csv).",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="Evidence cache path (defaults to code/cache/parsed_evidence.json).",
    )
    parser.add_argument(
        "--rebuild-cache",
        action="store_true",
        help="Ignore the existing evidence cache and parse every evidence file again.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Audit sample_deletion_requests.csv and evaluate against sample_output.csv.",
    )
    parser.add_argument(
        "--gold",
        "-g",
        type=Path,
        default=None,
        help="Ground truth CSV to evaluate predictions against.",
    )
    parser.add_argument(
        "--evaluate",
        "-e",
        action="store_true",
        help="Run evaluator against ground truth after generating predictions.",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Print per-case diffs for mismatched cases during evaluation.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for pipeline."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    dataset_dir = repo_root / "dataset"

    if args.sample:
        input_path = dataset_dir / "sample_deletion_requests.csv"
        gold_path = dataset_dir / "sample_output.csv"
        evaluate_mode = True
    else:
        input_path = args.input or (dataset_dir / "deletion_requests.csv")
        gold_path = args.gold
        evaluate_mode = args.evaluate or (gold_path is not None)

    output_path = args.output or (repo_root / "output.csv")

    print("[*] Initializing Deletion Audit Pipeline...")
    print(f"    Dataset Dir: {dataset_dir}")
    print(f"    Input Path:  {input_path}")
    print(f"    Output Path: {output_path}")

    pipeline = Pipeline(
        dataset_dir=dataset_dir,
        cache_path=args.cache,
        rebuild_cache=args.rebuild_cache,
    )
    stats = pipeline.cache_result.stats
    print(
        f"[+] Evidence cache ready: files={stats.files} "
        f"observations={stats.observations} hits={stats.hits} misses={stats.misses}"
    )
    print(f"[*] Running audit for {input_path.name}...")
    pipeline.run(input_path, output_path)
    print(f"[+] Output written to {output_path}")

    if evaluate_mode and gold_path is not None and gold_path.exists():
        print(f"[*] Evaluating against {gold_path}...")
        gold_cases = load_cases(gold_path)
        pred_cases = load_cases(output_path)
        metrics = evaluate(gold_cases, pred_cases)
        print(format_summary(metrics))

        if args.diff or args.sample:
            has_diffs = False
            for case_id in metrics.universe:
                diffs = diff_case(case_id, gold_cases.get(case_id), pred_cases.get(case_id))
                if diffs:
                    if not has_diffs:
                        print("\n=== Mismatched Cases Diffs ===")
                        has_diffs = True
                    for line in diffs:
                        print(f"  {line}")

        if metrics.sequence_accuracy < 1.0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
