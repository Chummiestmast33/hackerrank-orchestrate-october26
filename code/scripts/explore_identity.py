"""P1.4 identity tracing per sample case.

Resolves each sample request email to user_id via user_identities.csv, and via
user_audit_log.csv (field_name=email old/new values) when the current snapshot
does not match. Builds the identity graph (current + historical identifiers
with event_time <= audit_at), verifies the email_hash SHA-256 relation, and
writes out/identity_resolution.csv.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence

from _paths import (
    AUDIT_LOG_CSV,
    IDENTITIES_CSV,
    OUT_DIR,
    SAMPLE_REQUESTS_CSV,
    ensure_out_dir,
    read_csv,
)


def norm(value: str) -> str:
    return value.strip().lower()


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    identities = {row["user_id"]: row for row in read_csv(IDENTITIES_CSV)}
    by_email: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in identities.values():
        by_email[norm(row["email"])].append(row)
    audit = read_csv(AUDIT_LOG_CSV)

    email_history: dict[str, list[dict[str, str]]] = defaultdict(list)
    user_events: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in audit:
        user_events[row["user_id"]].append(row)
        if norm(row.get("field_name", "")) == "email":
            email_history[norm(row["old_value"])].append(row)
            if row["new_value"]:
                email_history[norm(row["new_value"])].append(row)

    requests = read_csv(SAMPLE_REQUESTS_CSV)
    ensure_out_dir()
    results: list[dict[str, object]] = []
    for req in sorted(requests, key=lambda r: r["case_id"]):
        case_id = req["case_id"]
        email = norm(req["email"])
        audit_at = req["audit_at"]
        method = ""
        user_row: dict[str, str] | None = None
        if email in by_email and len(by_email[email]) == 1:
            user_row = by_email[email][0]
            method = "current_identity_email"
        elif email in email_history:
            match = email_history[email][0]
            user_row = identities.get(match["user_id"])
            method = "audit_log_email_history"
        if user_row is None:
            results.append({"case_id": case_id, "email": email, "status": "UNRESOLVED"})
            continue
        user_id = user_row["user_id"]
        events = sorted(
            (e for e in user_events.get(user_id, []) if e["event_time"] <= audit_at),
            key=lambda e: e["event_time"],
        )
        hist_set = {
            norm(e["old_value"])
            for e in events
            if norm(e["field_name"]) == "email" and e["old_value"]
        } | {
            norm(e["new_value"])
            for e in events
            if norm(e["field_name"]) == "email" and e["new_value"]
        }
        hist_emails = sorted(hist_set)
        snapshot_after_audit = user_row["updated_at"] > audit_at
        hash_of_current = sha256_hex(norm(user_row["email"])) == norm(user_row["email_hash"])
        hash_of_any_hist = {e: sha256_hex(e) == norm(user_row["email_hash"]) for e in hist_emails}
        field_changes = Counter_fields(events)
        results.append(
            {
                "case_id": case_id,
                "email": email,
                "user_id": user_id,
                "method": method,
                "name": user_row["name"],
                "current_email": user_row["email"],
                "phone": user_row["phone"],
                "email_hash": user_row["email_hash"][:12] + "...",
                "snapshot_updated_at": user_row["updated_at"],
                "snapshot_updated_after_audit_at": snapshot_after_audit,
                "historical_emails_le_audit_at": ";".join(
                    sorted(hist_set - {norm(user_row["email"])})
                )
                or "-",
                "needed_history": method != "current_identity_email",
                "sha256_lower_email_matches_hash": hash_of_current,
                "sha256_historical_match": json.dumps(hash_of_any_hist)
                if hash_of_any_hist
                else "-",
                "field_change_counts": json.dumps(field_changes),
            }
        )

    out_path = OUT_DIR / "identity_resolution.csv"
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    for res in results:
        print(json.dumps(res, default=str))
    methods = Counter_fields([r for r in results if "method" in r], key="method")
    print(f"\nresolution methods: {methods}")
    flagged = [r["case_id"] for r in results if r.get("snapshot_updated_after_audit_at")]
    print(f"snapshot updated_at AFTER audit_at: {flagged or 'none'}")
    hist = [r["case_id"] for r in results if r.get("needed_history")]
    print(f"cases needing audit-log email history: {hist or 'none'}")
    hash_ok = all(r.get("sha256_lower_email_matches_hash", False) for r in results if "method" in r)
    print(f"sha256(lower(current email)) == email_hash for all samples: {hash_ok}")


def Counter_fields(rows: Sequence[Mapping[str, object]], key: str = "field_name") -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get(key, "?"))] += 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    main()
