"""Display-time masking of personal data (NFR-06).

All data in this project is synthetic, but traces, scenario views and reports are served with
person-like fields masked to demonstrate the practice. Stored data is left intact so the
evaluator can use it (context/architecture.md §6).
"""

from typing import Any

PII_KEYS = frozenset({"recipient_name", "new_address", "phone", "email", "address"})


def mask_text(value: str) -> str:
    """'Ananya Rao' -> 'A***** R**'"""
    return " ".join(part[0] + "*" * (len(part) - 1) for part in value.split() if part)


def redact_pii(value: Any) -> Any:
    """Returns a copy of `value` with PII_KEYS values masked, at any nesting depth."""
    if isinstance(value, dict):
        return {
            key: mask_text(item) if key in PII_KEYS and isinstance(item, str) else redact_pii(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_pii(item) for item in value]
    return value
