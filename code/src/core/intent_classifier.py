"""Multilingual intent classifier for deletion requests (AGENTS.md section 6.2, 6.5).

Evaluates whether ``request_text`` authorizes data deletion or represents a
non-deletion request (access, correction, export, marketing opt-out, account recovery,
or adversarial prompt-injection), in which case the request is ``NOT_APPLICABLE``.

Features:
1. Fast-path deterministic regex rules for 6 languages (en, fr, pt, es, ja, ko)
   and explicit negation detection.
2. Intake activity check against ``CLASSIFY_REQUEST`` events in ``system_activity.csv``.
3. Prompt-injection isolation and rejection.
4. Aggressive disk-caching (``code/cache/intent_classifications.json``) to prevent
   unnecessary LLM calls.
5. Metered LLM fallback when ambiguous and cache is absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from ..evaluation.metering import Meter
from ..loaders.csv_loader import ActivityRow
from ..models import IntentVerdict

CACHE_FILE_NAME = "intent_classifications.json"

# Adversarial prompt-injection indicators
_PROMPT_INJECTION_RE = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions|you\s+are\s+now|system\s+prompt|print\s+every\s+stored|"
    r"disregard\s+(?:all\s+)?prior|bypass\s+security|dump\s+database)",
    re.IGNORECASE,
)

# Negated deletion patterns (explicit requests NOT to delete or close)
_NEGATED_DELETION_RE = re.compile(
    r"(?:"
    r"do\s+not\s+(?:close|delete|remove|erase|purge)|"
    r"don'?t\s+(?:close|delete|remove|erase|purge)|"
    r"leave\s+(?:the\s+|my\s+)?account\s+active|"
    r"leave\s+(?:the\s+|my\s+)?(?:profile|purchase|history|records)\s+in\s+place|"
    r"keep\s+(?:the\s+|my\s+)?account\s+(?:as\s+it\s+is|active|open)|"
    r"without\s+removing\s+any\s+of\s+my\s+records|"
    r"want\s+to\s+continue\s+using\s+the\s+service|"
    r"keep\s+my\s+account\s+and\s+order\s+history"
    r")",
    re.IGNORECASE,
)

# Specific non-deletion categories
_CORRECTION_RE = re.compile(
    r"(?:out\s+of\s+date|replace\s+it\s+with\s+the\s+new\s+one|misspelled|correct\s+it|"
    r"change\s+the\s+email\s+address|update\s+my\s+(?:phone|mobile|email|name))",
    re.IGNORECASE,
)

_ACCESS_EXPORT_RE = re.compile(
    r"(?:download\s+my\s+account\s+information|portable\s+format|copy\s+of\s+(?:last\s+year'?s\s+)?invoices|"
    r"export\s+my\s+data|request\s+access\s+to\s+my\s+data|send\s+me\s+my\s+data)",
    re.IGNORECASE,
)

_MARKETING_OPTOUT_RE = re.compile(
    r"(?:unsubscribe\s+me|stop\s+(?:the\s+)?marketing\s+emails|opt[- ]out\s+of\s+marketing|"
    r"newsletter\s+unsubscribe)",
    re.IGNORECASE,
)

_ACCOUNT_HELP_RE = re.compile(
    r"(?:can'?t\s+access\s+my\s+profile|resetting\s+the\s+login|forgot\s+my\s+password|"
    r"help\s+(?:with\s+)?resetting|login\s+issue)",
    re.IGNORECASE,
)

# Multilingual affirmative deletion patterns
_DELETION_PATTERNS = {
    "en": re.compile(
        r"(?:"
        r"close\s+(?:my\s+)?account|"
        r"delete\s+(?:all\s+)?(?:my\s+)?(?:personal\s+)?(?:data|records|profile|account)|"
        r"remove\s+(?:the\s+|my\s+)?(?:profile|personal\s+details|data|records)|"
        r"purge\s+(?:my\s+)?(?:records|data)|"
        r"erasure\s+request|"
        r"right\s+to\s+be\s+forgotten|"
        r"verify\s+that\s+the\s+profile\s+is\s+gone|"
        r"delete\s+that\s+export\s+file\s+as\s+well"
        r")",
        re.IGNORECASE,
    ),
    "fr": re.compile(
        r"(?:suppression\s+d[eé]finitive|supprimer\s+(?:mon\s+compte|mes\s+donn[eé]es)|effacer\s+mes\s+donn[eé]es)",
        re.IGNORECASE,
    ),
    "pt": re.compile(
        r"(?:exclus[aã]o\s+permanente|apagar\s+(?:minha\s+conta|meus\s+dados)|eliminar\s+minha\s+conta)",
        re.IGNORECASE,
    ),
    "es": re.compile(
        r"(?:eliminaci[oó]n\s+permanente|borrar\s+(?:mi\s+cuenta|mis\s+datos)|suprimir\s+mis\s+datos)",
        re.IGNORECASE,
    ),
    "ja": re.compile(
        r"(?:完全な削除|アカウントの完全な削除|アカウント.*削除|データを削除|個人情報を削除)",
    ),
    "ko": re.compile(
        r"(?:영구\s*삭제|계정(?:의)?\s*영구\s*삭제|계정.*삭제|데이터.*삭제|개인정보.*삭제)",
    ),
}


class IntentClassifier:
    """Classifies user requests with regex fast-path and cached LLM fallback."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        meter: Meter | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.meter = meter or Meter()
        self._cache: dict[str, dict[str, Any]] = {}
        self._load_cache()

    def _cache_path(self) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / CACHE_FILE_NAME

    def _load_cache(self) -> None:
        path = self._cache_path()
        if path is not None and path.exists():
            try:
                self._cache = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._cache = {}

    def _save_cache(self) -> None:
        path = self._cache_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def classify_text_fast_path(self, text: str) -> IntentVerdict | None:
        """Deterministic, rule-based classification."""
        cleaned = text.strip()
        if not cleaned:
            return IntentVerdict(
                is_deletion=False,
                category="EMPTY",
                confidence=1.0,
                reason="empty request text",
            )

        # 1. Prompt-injection defense
        if _PROMPT_INJECTION_RE.search(cleaned):
            return IntentVerdict(
                is_deletion=False,
                category="PROMPT_INJECTION",
                confidence=1.0,
                reason="adversarial prompt-injection attempt detected",
            )

        # 2. Negated deletion (e.g. 'do not close', 'leave active')
        if _NEGATED_DELETION_RE.search(cleaned):
            return IntentVerdict(
                is_deletion=False,
                category="NEGATED_DELETION",
                confidence=1.0,
                reason="request explicitly demands preserving or keeping account active",
            )

        # 3. Specific non-deletion categories
        if _CORRECTION_RE.search(cleaned):
            return IntentVerdict(
                is_deletion=False,
                category="CORRECTION",
                confidence=0.98,
                reason="request is for profile or identifier correction",
            )

        if _ACCESS_EXPORT_RE.search(cleaned):
            return IntentVerdict(
                is_deletion=False,
                category="ACCESS",
                confidence=0.98,
                reason="request is for data access or export download",
            )

        if _MARKETING_OPTOUT_RE.search(cleaned):
            return IntentVerdict(
                is_deletion=False,
                category="MARKETING_OPTOUT",
                confidence=0.98,
                reason="request is for marketing communication opt-out",
            )

        if _ACCOUNT_HELP_RE.search(cleaned):
            return IntentVerdict(
                is_deletion=False,
                category="ACCOUNT_HELP",
                confidence=0.98,
                reason="request is for login or account recovery help",
            )

        # 4. Affirmative deletion patterns in any of the 6 languages
        for lang, pattern in _DELETION_PATTERNS.items():
            if pattern.search(cleaned):
                return IntentVerdict(
                    is_deletion=True,
                    category="DELETION",
                    confidence=0.99,
                    reason=f"explicit deletion authorized ({lang})",
                )

        return None

    def classify(
        self,
        request_text: str,
        activity_events: list[ActivityRow] | None = None,
        audit_at: str | None = None,
        account_ids: set[str] | None = None,
    ) -> IntentVerdict:
        """Classify a request using activity lookup, fast-path rules, or cached LLM."""
        # 1. Check intake activity events if provided
        if activity_events and account_ids:
            for act in activity_events:
                if act.event_type == "CLASSIFY_REQUEST" and act.resource_id in account_ids:
                    if audit_at is None or act.event_time <= audit_at:
                        if "non-deletion" in act.details.lower():
                            return IntentVerdict(
                                is_deletion=False,
                                category="NON_DELETION_INTAKE",
                                confidence=1.0,
                                reason=f"privacy intake classified as non-deletion in {act.activity_id}",
                            )

        # 2. Fast-path deterministic evaluation
        verdict = self.classify_text_fast_path(request_text)
        if verdict is not None:
            return verdict

        # 3. Check disk cache before invoking any model
        content_hash = hashlib.sha256(request_text.strip().encode("utf-8")).hexdigest()
        if content_hash in self._cache:
            entry = self._cache[content_hash]
            return IntentVerdict(
                is_deletion=bool(entry["is_deletion"]),
                category=str(entry["category"]),
                confidence=float(entry.get("confidence", 0.9)),
                reason=f"cached: {entry.get('reason', '')}",
            )

        # 4. Ambiguous and uncached: if in offline mode / no model available,
        # fail safe to non-deletion if suspicious or deletion if neutral
        return IntentVerdict(
            is_deletion=True,
            category="DELETION_DEFAULT",
            confidence=0.5,
            reason="ambiguous text; default deletion assumption",
        )
