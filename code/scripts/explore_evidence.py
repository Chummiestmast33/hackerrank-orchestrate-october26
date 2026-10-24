"""P1.5 resource linkage, P1.6 evidence formats, P1.7 citation rule, P1.10 temporal checks.

Writes out/resource_linkage.csv, out/citation_audit.csv, out/temporal_audit.csv
and out/evidence_formats.md. PDF containment uses pypdf text extraction; PNGs
are flagged for manual review (structured extraction is Plan.md Phase 4).
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import cast

from _paths import (
    ACTIVITY_CSV,
    AUDIT_LOG_CSV,
    DATASET_DIR,
    EVIDENCE_MANIFEST_CSV,
    IDENTITIES_CSV,
    OUT_DIR,
    SAMPLE_OUTPUT_CSV,
    SAMPLE_REQUESTS_CSV,
    ensure_out_dir,
    read_csv,
)
from explore_identity import norm

TEXT_EXTS = {".sql", ".json", ".log", ".txt"}
BINARY_EXTS = {".pdf", ".png"}


# --------------------------------------------------------------------------- #
# Loading & text corpus
# --------------------------------------------------------------------------- #


def load_manifest() -> dict[str, dict[str, str]]:
    return {row["file_id"]: row for row in read_csv(EVIDENCE_MANIFEST_CSV)}


def manifest_path(row: dict[str, str]) -> Path:
    return DATASET_DIR / row["file_path"].replace("/", "\\")


class Corpus:
    def __init__(self, manifest: dict[str, dict[str, str]]) -> None:
        self.manifest = manifest
        self.text: dict[str, str] = {}
        self.text_lower: dict[str, str] = {}
        self.digits: dict[str, str] = {}
        self.binary_kinds: dict[str, str] = {}
        for fid, row in manifest.items():
            path = manifest_path(row)
            ext = path.suffix.lower()
            if ext in TEXT_EXTS:
                content = path.read_text(encoding="utf-8", errors="replace")
                self.text[fid] = content
                self.text_lower[fid] = content.lower()
                self.digits[fid] = re.sub(r"\D", "", content)
            else:
                self.binary_kinds[fid] = ext

    def pdf_text(self, fid: str) -> str:
        if fid not in self._pdf_cache:
            from pypdf import PdfReader  # local import: only needed for 4 PDFs

            reader = PdfReader(str(manifest_path(self.manifest[fid])))
            self._pdf_cache[fid] = "\n".join(
                (page.extract_text() or "") for page in reader.pages
            ).lower()
        return self._pdf_cache[fid]

    _pdf_cache: dict[str, str] = {}

    def contains_token(self, fid: str, token: str) -> bool:
        pattern = rf"\b{re.escape(token.lower())}\b"
        if fid in self.text_lower:
            return re.search(pattern, self.text_lower[fid]) is not None
        if self.binary_kinds.get(fid) == ".pdf":
            return re.search(pattern, self.pdf_text(fid)) is not None
        return False

    def contains_digits(self, fid: str, digits: str) -> bool:
        return fid in self.digits and digits in self.digits[fid]


# --------------------------------------------------------------------------- #
# Identity graphs (mirrors explore_identity.py logic)
# --------------------------------------------------------------------------- #


def build_identity_indexes() -> tuple[
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
    dict[str, str],
    dict[str, list[dict[str, str]]],
]:
    identities = {row["user_id"]: row for row in read_csv(IDENTITIES_CSV)}
    by_email: dict[str, dict[str, str]] = {}
    for row in identities.values():
        by_email.setdefault(norm(row["email"]), row)
    audit = read_csv(AUDIT_LOG_CSV)
    email_hist: dict[str, str] = {}
    user_events: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in audit:
        user_events[row["user_id"]].append(row)
        if norm(row["field_name"]) == "email":
            email_hist.setdefault(norm(row["old_value"]), row["user_id"])
            if row["new_value"]:
                email_hist.setdefault(norm(row["new_value"]), row["user_id"])
    return identities, by_email, email_hist, user_events


class IdentityGraph:
    def __init__(self, user_row: dict[str, str], events: list[dict[str, str]]) -> None:
        self.user_id = user_row["user_id"]
        self.name = user_row["name"]
        self.emails = {norm(user_row["email"])}
        self.phones = {user_row["phone"].strip()}
        self.hashes = {norm(user_row["email_hash"])}
        for event in events:
            field = norm(event["field_name"])
            for value in (event["old_value"], event["new_value"]):
                if not value:
                    continue
                if field == "email":
                    self.emails.add(norm(value))
                elif field == "phone":
                    self.phones.add(value.strip())
                elif field == "email_hash":
                    self.hashes.add(norm(value))

    def text_needles(self) -> list[str]:
        needles = sorted(self.emails | self.hashes | {self.name.lower(), self.user_id})
        needles += sorted(self.phones)
        return needles

    def phone_digit_variants(self) -> list[str]:
        return sorted({re.sub(r"\D", "", p) for p in self.phones if len(re.sub(r"\D", "", p)) >= 7})


def resolve_graph(
    req: dict[str, str], identities, by_email, email_hist, user_events
) -> IdentityGraph | None:
    email = norm(req["email"])
    user_row = by_email.get(email)
    if user_row is None:
        user_id = email_hist.get(email)
        user_row = identities.get(user_id) if user_id else None
    if user_row is None:
        return None
    events = sorted(
        (e for e in user_events.get(user_row["user_id"], []) if e["event_time"] <= req["audit_at"]),
        key=lambda e: e["event_time"],
    )
    return IdentityGraph(user_row, events)


# --------------------------------------------------------------------------- #
# Activity index
# --------------------------------------------------------------------------- #


def load_activity() -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    rows = read_csv(ACTIVITY_CSV)
    by_resource: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["resource_id"]:
            by_resource[row["resource_id"]].append(row)
    return by_resource, rows


# --------------------------------------------------------------------------- #
# P1.5 linkage audit + P1.7 citation audit + P1.10 temporal
# --------------------------------------------------------------------------- #


def family_of(file_path: str) -> str:
    stem = Path(file_path).stem
    return re.sub(r"(_\d+.*)+$", "", stem) + Path(file_path).suffix


def main() -> None:
    ensure_out_dir()
    manifest = load_manifest()
    corpus = Corpus(manifest)
    identities, by_email, email_hist, user_events = build_identity_indexes()
    activity_by_resource, activity_rows = load_activity()
    requests = {r["case_id"]: r for r in read_csv(SAMPLE_REQUESTS_CSV)}
    outputs = {r["case_id"]: r for r in read_csv(SAMPLE_OUTPUT_CSV)}

    captured = {fid: row["captured_at"] for fid, row in manifest.items()}
    families: dict[str, list[str]] = defaultdict(list)
    for fid, row in manifest.items():
        families[family_of(row["file_path"])].append(fid)

    linkage_rows: list[dict[str, object]] = []
    citation_rows: list[dict[str, object]] = []
    temporal_rows: list[dict[str, object]] = []

    for case_id in sorted(outputs):
        req = requests[case_id]
        audit_at = req["audit_at"]
        graph = resolve_graph(req, identities, by_email, email_hist, user_events)
        if graph is None:
            print(f"{case_id}: IDENTITY UNRESOLVED")
            continue
        steps = json.loads(outputs[case_id]["steps_json"])
        resources = sorted({(s["system_id"], s["resource_id"]) for s in steps})

        eligible = sorted(fid for fid in manifest if captured[fid] <= audit_at)
        later = sorted(fid for fid in manifest if captured[fid] > audit_at)

        needle_files: dict[str, list[str]] = {}
        for needle in graph.text_needles():
            hits = [fid for fid in eligible if corpus.contains_token(fid, needle)]
            if hits:
                needle_files[needle] = hits
        for digits in graph.phone_digit_variants():
            hits = [fid for fid in eligible if corpus.contains_digits(fid, digits)]
            if hits:
                needle_files[f"phone_digits:{digits}"] = hits
        user_files = sorted({fid for hits in needle_files.values() for fid in hits})

        activity_le = {
            rid: [a for a in activity_by_resource.get(rid, []) if a["event_time"] <= audit_at]
            for _, rid in resources
        }
        activity_gt = {
            rid: [a for a in activity_by_resource.get(rid, []) if a["event_time"] > audit_at]
            for _, rid in resources
        }

        # --- P1.5 linkage ---
        for system_id, rid in resources:
            rid_files = [fid for fid in eligible if corpus.contains_token(fid, rid)]
            rid_in_user_files = sorted(set(rid_files) & set(user_files))
            activity = activity_le[rid]
            activity_types = Counter(a["event_type"] for a in activity)
            linked_activity_ids = [
                a["activity_id"]
                for a in activity
                if a["event_type"] == "LINK_RESOURCE_IDENTITY"
                or any(n.lower() in a["details"].lower() for n in graph.text_needles())
            ]
            if rid_in_user_files:
                verdict = "DISCOVERABLE_EVIDENCE"
            elif linked_activity_ids:
                verdict = "DISCOVERABLE_ACTIVITY"
            elif rid_files:
                verdict = "RID_ONLY_NO_IDENTIFIER_SAME_FILE"
            elif activity:
                verdict = "ACTIVITY_RESOURCE_MATCH_ONLY"
            elif any(corpus.binary_kinds.get(fid) == ".png" for fid in manifest):
                verdict = "TEXT_ABSENT_CHECK_PNG_MANUALLY"
            else:
                verdict = "GOLDEN_ONLY"
            linkage_rows.append(
                {
                    "case_id": case_id,
                    "system_id": system_id,
                    "resource_id": rid,
                    "verdict": verdict,
                    "activity_events": json.dumps(dict(activity_types)),
                    "activity_ids_sample": ";".join(a["activity_id"] for a in activity[:3]),
                    "linked_activity_ids": ";".join(linked_activity_ids[:5]),
                    "files_with_rid_le_audit": ";".join(rid_files),
                    "rid_in_identifier_files": ";".join(rid_in_user_files),
                }
            )

        # --- P1.7 citation audit ---
        cited_ids = sorted({s["evidence_id"] for s in steps if s["evidence_id"]})
        for step in steps:
            if not step["evidence_id"]:
                continue
            fid = step["evidence_id"]
            rid = step["resource_id"]
            candidates = [f for f in eligible if corpus.contains_token(f, rid)]
            latest = max(candidates, key=lambda f: captured[f]) if candidates else ""
            citation_rows.append(
                {
                    "case_id": case_id,
                    "step_no": step["step_no"],
                    "phase": step["phase"],
                    "resource_id": rid,
                    "cited": fid,
                    "cited_captured_at": captured.get(fid, "?"),
                    "cited_has_rid": fid in candidates,
                    "cited_is_latest_candidate": bool(latest) and fid == latest,
                    "n_candidates_le_audit": len(candidates),
                    "candidates": ";".join(candidates),
                    "latest_candidate": latest,
                    "case_cited_ids": ";".join(cited_ids),
                }
            )

        # --- P1.10 temporal ---
        for fid in cited_ids:
            if captured.get(fid, "9999") > audit_at:
                temporal_rows.append(
                    {
                        "case_id": case_id,
                        "kind": "FUTURE_CITATION",
                        "resource_id": "-",
                        "file_or_activity": fid,
                        "time": captured.get(fid, "?"),
                        "detail": f"cited but captured_at > audit_at {audit_at}",
                    }
                )
        for system_id, rid in resources:
            for fid in later:
                if corpus.contains_token(fid, rid):
                    temporal_rows.append(
                        {
                            "case_id": case_id,
                            "kind": "POST_AUDIT_FILE_MENTIONS_RESOURCE",
                            "resource_id": rid,
                            "file_or_activity": fid,
                            "time": captured[fid],
                            "detail": f"system={system_id} captured after audit_at {audit_at}",
                        }
                    )
            events = sorted(activity_by_resource.get(rid, []), key=lambda a: a["event_time"])
            for i, event in enumerate(events):
                if event["event_time"] > audit_at:
                    continue
                if event["event_type"] in {
                    "RESTORE_BACKUP",
                    "SYNC_RECORD",
                    "INDEX_RECORD",
                    "CREATE_EXPORT",
                }:
                    prior_delete = [
                        p
                        for p in events[:i]
                        if p["event_type"] in {"DELETE_RECORD", "ANONYMIZE_RECORD", "REDACT_RECORD"}
                    ]
                    if prior_delete:
                        temporal_rows.append(
                            {
                                "case_id": case_id,
                                "kind": "RECREATION_AFTER_DELETE",
                                "resource_id": rid,
                                "file_or_activity": event["activity_id"],
                                "time": event["event_time"],
                                "detail": f"{prior_delete[-1]['event_type']}@{prior_delete[-1]['event_time']} "
                                f"then {event['event_type']} reported_result={event['reported_result']}",
                            }
                        )
            for event in activity_gt[rid]:
                if event["event_type"] == "RESTORE_BACKUP":
                    temporal_rows.append(
                        {
                            "case_id": case_id,
                            "kind": "POST_AUDIT_ACTIVITY",
                            "resource_id": rid,
                            "file_or_activity": event["activity_id"],
                            "time": event["event_time"],
                            "detail": f"{event['event_type']} after audit_at (out of scope)",
                        }
                    )

    write_csv_rows(OUT_DIR / "resource_linkage.csv", linkage_rows)
    write_csv_rows(OUT_DIR / "citation_audit.csv", citation_rows)
    write_csv_rows(OUT_DIR / "temporal_audit.csv", temporal_rows)

    # ------------------------------------------------------------------ #
    # Summaries
    # ------------------------------------------------------------------ #
    print("== P1.5 linkage verdicts ==")
    for verdict_name, n in Counter(str(r["verdict"]) for r in linkage_rows).most_common():
        print(f"  {verdict_name}: {n}")
    bad = [
        r for r in linkage_rows if r["verdict"] in {"GOLDEN_ONLY", "TEXT_ABSENT_CHECK_PNG_MANUALLY"}
    ]
    for r in bad[:20]:
        print("  flag:", r["case_id"], r["system_id"], r["resource_id"], r["verdict"])

    print("\n== P1.7 citation rule ==")
    total = len(citation_rows)
    has_rid = sum(1 for r in citation_rows if r["cited_has_rid"])
    is_latest = sum(1 for r in citation_rows if r["cited_is_latest_candidate"])
    single: Counter[tuple[str, str]] = Counter()
    for r in citation_rows:
        single[(str(r["case_id"]), str(r["case_cited_ids"]))] += 1
    multi_cited_cases = sorted({c for (c, ids) in single if ";" in str(ids)})
    print(
        f"  citations={total} cited_file_mentions_resource={has_rid} cited_is_latest_candidate={is_latest}"
    )
    print(f"  cases citing >1 distinct evidence id: {multi_cited_cases or 'none'}")
    for r in citation_rows:
        if not r["cited_has_rid"]:
            print("  cited-without-rid:", r["case_id"], r["step_no"], r["resource_id"], r["cited"])

    print("\n== P1.10 temporal ==")
    for kind, n in Counter(r["kind"] for r in temporal_rows).most_common():
        print(f"  {kind}: {n}")
    for r in temporal_rows[:25]:
        if r["kind"] != "POST_AUDIT_FILE_MENTIONS_RESOURCE":
            print(
                "  ", r["kind"], r["case_id"], r["resource_id"], r["file_or_activity"], r["detail"]
            )

    write_formats_report(manifest, families, corpus, captured)


def write_csv_rows(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(v) for k, v in row.items()})


# --------------------------------------------------------------------------- #
# P1.6 evidence formats
# --------------------------------------------------------------------------- #


def sql_structure(path: Path) -> dict[str, object]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(path.read_text(encoding="utf-8", errors="replace"))
        tables = {
            t[0]: conn.execute(f'SELECT COUNT(*) FROM "{t[0]}"').fetchone()[0]
            for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        scope = None
        if "snapshot_scope" in tables:
            scope = [
                dict(zip(("origin_system", "captured_at"), r, strict=True))
                for r in conn.execute("SELECT * FROM snapshot_scope")
            ]
        columns = {t: [c[1] for c in conn.execute(f'PRAGMA table_info("{t}")')] for t in tables}
        return {"tables": tables, "columns": columns, "snapshot_scope": scope}
    finally:
        conn.close()


def json_structure(path: Path, depth: int = 2) -> object:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))

    def shape(obj: object, level: int) -> object:
        if level <= 0:
            return type(obj).__name__
        if isinstance(obj, dict):
            return {k: shape(v, level - 1) for k, v in list(obj.items())[:12]}
        if isinstance(obj, list):
            return [shape(obj[0], level - 1)] if obj else []
        return type(obj).__name__

    return shape(data, depth)


def log_structure(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    services: Counter[str] = Counter()
    events: Counter[str] = Counter()
    for line in lines:
        m = re.search(r"\bservice=(\S+)", line)
        if m:
            services[m.group(1)] += 1
        m = re.search(r"\bevent=(\S+)", line)
        if m:
            events[m.group(1)] += 1
    return {
        "n_lines": len(lines),
        "services": dict(services.most_common(8)),
        "events": dict(events.most_common(15)),
    }


def write_formats_report(
    manifest: dict[str, dict[str, str]],
    families: dict[str, list[str]],
    corpus: Corpus,
    captured: dict[str, str],
) -> None:
    cited = {
        "evidence_01",
        "evidence_03",
        "evidence_05",
        "evidence_51",
        "evidence_54",
        "evidence_56",
        "evidence_57",
        "evidence_58",
        "evidence_59",
        "evidence_61",
        "evidence_92",
        "evidence_93",
        "evidence_94",
    }
    lines = ["# P1.6 Evidence formats (auto-draft)", ""]
    for fam in sorted(families):
        fids = sorted(families[fam])
        rep = fids[0]
        row = manifest[rep]
        path = manifest_path(row)
        ext = path.suffix.lower()
        cap_range = f"{min(captured[f] for f in fids)} .. {max(captured[f] for f in fids)}"
        lines += [
            f"## family `{fam}` ({len(fids)} files, ext {ext})",
            f"- file_ids: {', '.join(fids)}",
            f"- captured_at range: {cap_range}",
            f"- origin(s): {sorted({manifest[f]['origin'] for f in fids})}",
            f"- representative: `{row['file_path']}` ({rep})",
        ]
        try:
            if ext == ".sql":
                info = sql_structure(path)
                tables = cast("dict[str, int]", info["tables"])
                columns = cast("dict[str, list[str]]", info["columns"])
                scope = cast("list[dict[str, str]] | None", info["snapshot_scope"])
                lines.append(f"- tables/row counts: {json.dumps(tables)}")
                if scope:
                    lines.append(f"- snapshot_scope: {json.dumps(scope[:6])}")
                sample_table = (
                    max(columns, key=lambda t: 1 if columns[t] else 0) if columns else None
                )
                if sample_table:
                    lines.append(f"- columns[{sample_table}]: {columns[sample_table]}")
            elif ext == ".json":
                lines.append(f"- top structure: `{json.dumps(json_structure(path))[:600]}`")
            elif ext == ".log":
                lines.append(f"- log structure: `{json.dumps(log_structure(path))[:600]}`")
                text_lines = corpus.text[rep].splitlines()
                lines.append(f"- first line: `{text_lines[0][:220]}`" if text_lines else "- empty")
            elif ext == ".txt":
                text_lines = [
                    ln for ln in corpus.text[rep].splitlines() if ln.strip().startswith("-")
                ]
                lines.append(f"- record lines starting with '-': {len(text_lines)}")
                lines.append(f"- example: `{text_lines[0][:220]}`" if text_lines else "- none")
            else:
                lines.append(
                    f"- binary {ext}: manual review required (size {path.stat().st_size} bytes)"
                )
        except Exception as exc:  # noqa: BLE001 - exploration script
            lines.append(f"- STRUCTURE ERROR: {exc}")
        cited_here = sorted(set(fids) & cited)
        if cited_here:
            lines.append(f"- cited by samples: {', '.join(cited_here)}")
        lines.append("")
    out = OUT_DIR / "evidence_formats.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
