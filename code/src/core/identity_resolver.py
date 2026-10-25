"""Identity resolver for resolving case-insensitive identity closures (AGENTS.md section 6.2, 6.5).

Resolves current and historical identifiers (user_id, names, emails, phones, email_hashes)
as of audit_at using user_identities.csv and user_audit_log.csv.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from ..loaders.csv_loader import AuditLogRow, IdentityRow
from ..models import IdentityGraph


class IdentityResolver:
    """Resolves identity graphs from identities and audit history."""

    def __init__(
        self,
        identities: Iterable[IdentityRow],
        audit_log: Iterable[AuditLogRow],
    ) -> None:
        self.identities = list(identities)
        self.audit_log = list(audit_log)

        # Pre-index identities
        self._ident_by_user_id: dict[str, IdentityRow] = {
            i.user_id: i for i in self.identities
        }
        self._user_by_email: dict[str, str] = {
            i.email.strip().lower(): i.user_id for i in self.identities if i.email
        }

        # Index audit log by user_id
        self._audit_by_user_id: dict[str, list[AuditLogRow]] = {}
        for a in self.audit_log:
            self._audit_by_user_id.setdefault(a.user_id, []).append(a)

    def resolve(self, request_email: str, audit_at: str) -> IdentityGraph:
        """Resolve full identity graph for request_email as of audit_at."""
        norm_email = request_email.strip().lower()
        user_id = self._user_by_email.get(norm_email)

        # If not found directly in current identities, look through audit log
        if not user_id:
            for a in self.audit_log:
                if a.event_time <= audit_at and a.field_name == "email":
                    if norm_email in (a.old_value.strip().lower(), a.new_value.strip().lower()):
                        user_id = a.user_id
                        break

        if not user_id:
            # Fallback if email never appeared in identities or audit log
            user_id = f"unknown_{hashlib.sha256(norm_email.encode('utf-8')).hexdigest()[:8]}"
            ident = None
        else:
            ident = self._ident_by_user_id.get(user_id)

        emails: set[str] = {norm_email}
        phones: set[str] = set()
        names: set[str] = set()
        hashes: set[str] = set()

        if ident is not None:
            if ident.email:
                emails.add(ident.email.strip().lower())
            if ident.phone:
                phones.add(ident.phone.strip())
            if ident.name:
                names.add(ident.name.strip())
            if ident.email_hash:
                hashes.add(ident.email_hash.strip().lower())

        # Collect historical mutations <= audit_at
        if user_id in self._audit_by_user_id:
            for a in self._audit_by_user_id[user_id]:
                if a.event_time <= audit_at:
                    if a.field_name == "email":
                        if a.old_value:
                            emails.add(a.old_value.strip().lower())
                        if a.new_value:
                            emails.add(a.new_value.strip().lower())
                    elif a.field_name == "phone":
                        if a.old_value:
                            phones.add(a.old_value.strip())
                        if a.new_value:
                            phones.add(a.new_value.strip())
                    elif a.field_name == "email_hash":
                        if a.old_value:
                            hashes.add(a.old_value.strip().lower())
                        if a.new_value:
                            hashes.add(a.new_value.strip().lower())

        # Expand phone formats: add digits-only representations and local variants
        digits_phones = set()
        for p in phones:
            digits = re.sub(r"\D", "", p)
            if len(digits) >= 7:
                digits_phones.add(digits)
                if digits.startswith("1") and len(digits) in (8, 11):
                    digits_phones.add(digits[1:])
        phones.update(digits_phones)

        # For every email, derive SHA-256 hash
        for e in list(emails):
            hashes.add(hashlib.sha256(e.encode("utf-8")).hexdigest())

        canonical_email = ident.email.strip().lower() if ident and ident.email else norm_email

        return IdentityGraph(
            user_id=user_id,
            canonical_email=canonical_email,
            all_emails=frozenset(emails),
            all_phones=frozenset(phones),
            all_names=frozenset(names),
            all_email_hashes=frozenset(hashes),
            audit_at=audit_at,
        )
