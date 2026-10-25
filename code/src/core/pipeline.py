"""Pipeline orchestrator and CLI runner for Ghost Data Still Exists (AGENTS.md section 1, 6).

Coordinates dataset loading, evidence cache ingestion, Hybrid AI Audit Agent
execution (qwen3.7-max + qwen3-vl-plus + deterministic tool guardrails),
and output.csv generation and validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from ..evaluation.evaluator import (
    diff_case,
    evaluate,
    format_summary,
    load_cases,
)
from ..evaluation.metering import Meter
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
from ..models import CaseAuditResult, EvidenceObservation, ParseReport
from .agent import AuditOrchestratorAgent
from .audit_engine import AuditEngine


class Pipeline:
    """End-to-end deletion audit pipeline powered by AuditOrchestratorAgent."""

    def __init__(
        self,
        dataset_dir: Path | None = None,
        cache_path: Path | None = None,
        code_dir: Path | None = None,
        transcription_store_path: Path | None = None,
        rebuild_cache: bool = False,
        meter: Meter | None = None,
        enable_live_llm: bool = False,
    ) -> None:
        self.code_dir = code_dir or Path(__file__).resolve().parent.parent.parent
        self.repo_root = self.code_dir.parent
        self.dataset_dir = dataset_dir or (self.repo_root / "dataset")
        self.cache_path = cache_path or (self.code_dir / "cache" / "parsed_evidence.json")
        self.transcription_store_path = transcription_store_path or (
            self.code_dir / "data" / "multimodal_transcriptions.json"
        )
        self.meter = meter or Meter(run_id="__full_518_audit__")
        self.enable_live_llm = enable_live_llm

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
        self.trace_captured_at: dict[str, str] = {}

        self._load_evidence_cache()

        # Initialize AuditEngine and Hybrid AI AuditOrchestratorAgent
        self.engine = AuditEngine(
            identities=self.identities,
            audit_log=self.audit_log,
            activity_events=self.activity_events,
            rules=self.rules,
            observations=self.observations,
            reports=self.reports,
            trace_subjects=self.trace_subjects,
            trace_resources=self.trace_resources,
            trace_captured_at=self.trace_captured_at,
        )
        self.agent = AuditOrchestratorAgent(
            engine=self.engine,
            dataset_dir=self.dataset_dir,
            manifest=self.manifest,
            cache_dir=self.cache_path.parent,
            meter=self.meter,
        )

    def _load_evidence_cache(self) -> None:
        """Load parsed observations and build temporal log trace maps."""
        entries, _warnings = read_cache(self.cache_path)
        if not entries:
            raise CacheBuildError(f"evidence cache is empty or unreadable: {self.cache_path}")

        for file_id, entry in entries.items():
            if entry.report is not None:
                self.reports[file_id] = entry.report
            for obs in entry.observations:
                self.observations.append(obs)

        captured_by_filename = {
            Path(row.file_path).name: row.captured_at for row in self.manifest
        }

        # Build bidirectional trace index and resource subject mappings from log files
        token_pattern = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|\S+)')
        logs_dir = self.dataset_dir / "evidence" / "logs"
        if logs_dir.exists():
            for p in logs_dir.glob("*.log"):
                file_captured_at = captured_by_filename.get(p.name, "")
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

                    if tid and file_captured_at:
                        prev = self.trace_captured_at.get(tid)
                        if prev is None or file_captured_at < prev:
                            self.trace_captured_at[tid] = file_captured_at
                    if sub and sub != "null":
                        cleaned = str(sub).strip('"').strip("'").lower()
                        if tid:
                            self.trace_subjects.setdefault(tid, set()).add(cleaned)
                    if rid and tid:
                        self.trace_resources.setdefault(tid, set()).add(str(rid).strip('"'))

    def audit_requests(
        self,
        requests: Sequence[DeletionRequestRow],
        *,
        enable_live_llm: bool | None = None,
    ) -> list[CaseAuditResult]:
        """Audit requests via AuditOrchestratorAgent and return results sorted by case_id."""
        live = self.enable_live_llm if enable_live_llm is None else enable_live_llm
        return self.agent.audit_all(requests, enable_live_llm=live)

    def run(
        self,
        input_path: Path,
        output_path: Path | None = None,
        *,
        enable_live_llm: bool | None = None,
    ) -> list[OutputRow]:
        """Run audit pipeline on input CSV and optionally write output CSV."""
        requests, _ = load_deletion_requests(input_path)
        results = self.audit_requests(requests, enable_live_llm=enable_live_llm)

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

            # Mirror full 518-case output to dataset/output.csv when writing root output.csv
            if (
                output_path.resolve() == (self.repo_root / "output.csv").resolve()
                and len(rows) == 518
                and (self.dataset_dir / "deletion_requests.csv").exists()
            ):
                dataset_output = self.dataset_dir / "output.csv"
                shutil.copyfile(output_path, dataset_output)

        return rows


def build_arg_parser() -> argparse.ArgumentParser:
    """Build command line argument parser for pipeline."""
    parser = argparse.ArgumentParser(
        description="Ghost Data Still Exists Deletion-Audit Agent (AGENTS.md section 1, 6)."
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
        "--agent-llm",
        action="store_true",
        help="Force live Qwen LLM/VLM agent calls during audit orchestration.",
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

    print("[*] Initializing Hybrid AI Deletion-Audit Agent...")
    print(f"    Dataset Dir: {dataset_dir}")
    print(f"    Input Path:  {input_path}")
    print(f"    Output Path: {output_path}")

    pipeline = Pipeline(
        dataset_dir=dataset_dir,
        cache_path=args.cache,
        rebuild_cache=args.rebuild_cache,
        enable_live_llm=args.agent_llm,
    )
    stats = pipeline.cache_result.stats
    print(
        f"[+] Evidence cache ready: files={stats.files} "
        f"observations={stats.observations} hits={stats.hits} misses={stats.misses}"
    )
    print(f"[*] Running audit for {input_path.name}...")
    pipeline.run(input_path, output_path, enable_live_llm=args.agent_llm)
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
