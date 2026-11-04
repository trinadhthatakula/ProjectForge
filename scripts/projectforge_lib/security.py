from __future__ import annotations

import re
from typing import Any


_SECRET_ASSIGNMENT = re.compile(r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|private[_-]?key|authorization|credential)[\"']?\s*[:=]\s*(?:Bearer\s+)?[\"']?)([^\"'\s,;}]+)")
_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]{12,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\b")
_PROVIDER_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{16,}|AIza[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b")
_PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)


def redact_text(value: str) -> str:
    value = _PRIVATE_KEY_BLOCK.sub("[REDACTED PRIVATE KEY]", value)
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}[REDACTED]", value)
    value = _JWT.sub("[REDACTED TOKEN]", value)
    return _PROVIDER_TOKEN.sub("[REDACTED TOKEN]", value)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, dict):
        secret_key = re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|private[_-]?key|credential|authorization)")
        return {key: "[REDACTED]" if secret_key.search(str(key)) and item not in (None, "") else redact_sensitive(item) for key, item in value.items()}
    return value
