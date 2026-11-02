"""Deterministic PDF evidence extraction into :class:`ExtractedRecord` facts.

pypdf is the primary text source; pdfplumber is used as a fallback when the
primary pass yields no usable text. Families are detected from document header
text only (never from file names or ids). Nothing is inferred here — records
carry transcribed facts and diagnostics, and decoding happens in
``multimodal_rules``.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models import ExtractedRecord

PDF_FAMILY_HEADERS: tuple[tuple[str, str], ...] = (
    ("NORTHSTAR SHOP - CUSTOMER STATEMENT", "customer_statement"),
    ("DISPUTED ORDERS AND TAX RECORDS REGISTER", "retention_register"),
    ("COMPLIANCE JOURNAL - SIGNED RECORD EXTRACT", "compliance_journal"),
    ("DELIVERY ADDRESS CORRECTION REQUEST", "support_attachment"),
)

SPLIT_TIME = re.compile(r"(\d{1,2})\s*\n\s*(\d{2})(\s+UTC)")
LABEL_LINE = re.compile(r"^\s*(Record|Detail)\s*$")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\+\d[\d\s()-]{7,}\d")
USER_ID = re.compile(r"\buser_\d+\b")
RESOURCE_ID = re.compile(
    r"\b(?:account|support|search|data_flow|analytics|export|backup|audit_record|tombstone|legal_hold|object|marketing)_\w+\b"
)
ORDER_REF = re.compile(r"\bORD-\d+\b")
TICKET_REF = re.compile(r"\bCS-\d+\b")
STATEMENT_ID = re.compile(r"\bNST-\d{4}-\d{4}-\d{4}\b")
JOURNAL_REF = re.compile(r"\bCJX-\d{8}-\d{4}\b")
REGISTER_ROW = re.compile(
    r"(ORD-\d+)\s*\|\s*(user_\d+)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|"
    r"\s*([^|\n]+?)\s*\|\s*Retain until\s*([^|\n]+?)\s*\|\s*([A-Z]{2})\b"
)
UTC_TIMESTAMP = re.compile(r"\d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2} UTC")


@dataclass
class PdfExtraction:
    family: str
    records: list[ExtractedRecord] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    text_hash_source: str = ""


def _pypdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _pdfplumber_text(path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(str(path)) as document:
        return "\n".join((page.extract_text() or "") for page in document.pages)


def extract_text(path: Path) -> str:
    """pypdf first; pdfplumber fallback when the primary pass is empty."""
    primary = ""
    try:
        primary = _pypdf_text(path)
    except Exception:  # noqa: BLE001 - fallback is the explicit recovery path
        primary = ""
    if len(primary.strip()) >= 20:
        return primary
    try:
        fallback = _pdfplumber_text(path)
    except Exception:  # noqa: BLE001 - caller sees the empty primary text
        return primary
    return fallback if len(fallback.strip()) > len(primary.strip()) else primary


def normalize_text(raw: str) -> str:
    """Rejoin split times and drop PDF label artifacts while keeping line order."""
    text = SPLIT_TIME.sub(r"\1:\2\3", raw)
    lines = [
        line.strip() for line in text.splitlines() if not LABEL_LINE.match(line) and line.strip()
    ]
    cleaned = "\n".join(lines)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def detect_family(text: str) -> str:
    head = text[:800].upper()
    for signature, family in PDF_FAMILY_HEADERS:
        if signature in head:
            return family
    return "unknown"


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0) if match else None


def _customer_statement(text: str) -> tuple[dict[str, object], list[str]]:
    fields: dict[str, object] = {}
    name = re.search(r"Customer\s+([A-Z][^\n]+)", text)
    if name:
        fields["customer_name"] = name.group(1).strip()
    for key, pattern in (
        ("statement_id", STATEMENT_ID),
        ("user_id", USER_ID),
        ("email", EMAIL),
        ("order_ref", ORDER_REF),
    ):
        value = _first(pattern, text)
        if value is not None:
            fields[key] = value
    sku = re.search(r"SKU\s+([A-Z0-9-]+)", text)
    if sku:
        fields["item_sku"] = sku.group(1)
    total = re.search(r"total EUR ([\d.,]+)", text)
    if total:
        fields["total_eur"] = total.group(1)
    diagnostics = [] if "user_id" in fields else ["missing_field:user_id"]
    return fields, diagnostics


def _retention_register(text: str) -> tuple[list[dict[str, object]], list[str]]:
    month = re.search(r"Register month\s+([A-Za-z]+ \d{4})", text)
    rows: list[dict[str, object]] = []
    for order_ref, user_id, reason, date, amount, retain_until, owner in REGISTER_ROW.findall(text):
        record: dict[str, object] = {
            "order_ref": order_ref,
            "user_id": user_id,
            "reason": reason.strip(),
            "date": date.strip(),
            "amount": amount.strip(),
            "retain_until": retain_until.strip(),
            "owner": owner,
        }
        if month:
            record["register_month"] = month.group(1)
        rows.append(record)
    return rows, ([] if rows else ["missing_register_rows"])


def _compliance_journal(text: str) -> tuple[dict[str, object], list[str]]:
    fields: dict[str, object] = {}
    for key, pattern in (
        ("journal_reference", JOURNAL_REF),
        ("event_reference", re.compile(r"\baudit_record_\d+\b")),
        ("subject_reference", USER_ID),
        ("recorded_at", re.compile(r"recorded\s+(" + UTC_TIMESTAMP.pattern + r")")),
        ("retain_until", re.compile(r"retain until\s+(" + UTC_TIMESTAMP.pattern + r")")),
        ("journal_partition", re.compile(r"Journal partition\s+([\w-]+)")),
        ("integrity_seal", re.compile(r"integrity seal\s+(\w+)")),
        ("actor", re.compile(r"actor\s+([A-Za-z][^\n]+)")),
        ("event_name", re.compile(r"\nevent\s+([A-Z][^\n]+)")),
    ):
        match = pattern.search(text)
        if match:
            fields[key] = match.group(1) if match.groups() else match.group(0)
    diagnostics = [
        f"missing_field:{name}"
        for name in ("event_reference", "subject_reference")
        if name not in fields
    ]
    return fields, diagnostics


def _support_attachment(text: str) -> tuple[dict[str, object], list[str]]:
    fields: dict[str, object] = {}
    support_id = re.search(r"\bsupport_\d+\b", text)
    if support_id:
        fields["support_id"] = support_id.group(0)
    ticket = _first(TICKET_REF, text)
    if ticket:
        fields["ticket_ref"] = ticket
    email = _first(EMAIL, text)
    if email:
        fields["requester_email"] = email
        name = re.search(r"\n([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)+)\n" + re.escape(email), text)
        if name:
            fields["requester_name"] = name.group(1)
    phone = PHONE.search(text)
    if phone:
        fields["requester_phone"] = re.sub(r"\s+", " ", phone.group(0)).strip()
    order = _first(ORDER_REF, text)
    if order:
        fields["order_ref"] = order
    for key, pattern in (
        ("submitted_at", re.compile(r"submitted\s+(" + UTC_TIMESTAMP.pattern + r")")),
        ("file_name", re.compile(r"file\s+([\w.-]+\.(?:pdf|png|jpg))")),
        ("region", re.compile(r"region\s+([\w-]+)")),
        ("uploader", re.compile(r"uploader\s+(\w+)")),
        ("checksum_prefix", re.compile(r"checksum prefix\s+(\w+)")),
    ):
        match = pattern.search(text)
        if match:
            fields[key] = match.group(1)
    diagnostics = [] if "support_id" in fields else ["missing_field:support_id"]
    return fields, diagnostics


def extract_pdf_records(file_id: str, path: Path) -> PdfExtraction:
    raw = extract_text(path)
    text = normalize_text(raw)
    family = detect_family(text)
    if family == "unknown":
        return PdfExtraction(family="unknown", diagnostics=["unknown_document_family"])
    if family == "customer_statement":
        fields, diagnostics = _customer_statement(text)
        records = [fields]
    elif family == "retention_register":
        records, diagnostics = _retention_register(text)
    elif family == "compliance_journal":
        fields, diagnostics = _compliance_journal(text)
        records = [fields]
    else:
        fields, diagnostics = _support_attachment(text)
        records = [fields]
    extracted = [
        ExtractedRecord(
            file_id=file_id,
            family=family,
            record_index=index,
            fields=tuple(record.items()),
            source="pdf_text",
        )
        for index, record in enumerate(records)
    ]
    return PdfExtraction(family=family, records=extracted, diagnostics=diagnostics)
