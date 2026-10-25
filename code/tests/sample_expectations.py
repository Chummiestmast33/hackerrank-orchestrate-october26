"""Documented public-sample expectations after the evidence-driven P1 refactor."""

KNOWN_EVIDENCE_GAP = frozenset({"case_18", "case_20"})
GAP_RECORD_BY_CASE = {
    "case_18": "audit_record_6645",
    "case_20": "audit_record_5569",
}
EXPECTED_SAMPLE_CASES = 32
EXPECTED_STATUS_CORRECT = 32
EXPECTED_SEQUENCE_CORRECT = 30
EXPECTED_POSITIONAL_MATCHED = 187
EXPECTED_POSITIONAL_TOTAL = 193
EXPECTED_SET_TP = 191
EXPECTED_SET_FP = 0
EXPECTED_SET_FN = 2
