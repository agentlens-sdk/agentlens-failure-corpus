"""Secret scrubbing applied to everything that leaves this process (traces, spans, exports)."""
import re

SECRET_RE = re.compile(r"(sk-ant-[A-Za-z0-9_-]+|ghp_[A-Za-z0-9]+|gho_[A-Za-z0-9]+|hf_[A-Za-z0-9]+)")


def redact(s):
    """Replace known credential shapes with [REDACTED]. Non-strings pass through untouched."""
    return SECRET_RE.sub("[REDACTED]", s) if isinstance(s, str) else s


def redact_deep(obj, _depth=0):
    """redact() applied through nested dicts/lists, as tool inputs and content blocks arrive."""
    if _depth > 12:
        return obj
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_deep(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_deep(v, _depth + 1) for v in obj]
    return obj
