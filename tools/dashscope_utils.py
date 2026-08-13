"""Shared DashScope endpoint helpers."""

from __future__ import annotations

import os


DEFAULT_DASHSCOPE_API_BASE = "https://dashscope.aliyuncs.com/api/v1"


def dashscope_api_base() -> str:
    """Return the DashScope native API base, honoring workspace endpoints."""
    base = (
        os.environ.get("DASHSCOPE_API_BASE")
        or os.environ.get("DASHSCOPE_BASE_URL")
        or os.environ.get("DASHSCOPE_API_HOST")
        or DEFAULT_DASHSCOPE_API_BASE
    ).strip()
    if not base:
        return DEFAULT_DASHSCOPE_API_BASE
    if not base.startswith(("http://", "https://")):
        base = "https://" + base

    base = base.rstrip("/")
    if base.endswith("/compatible-mode/v1"):
        base = base[: -len("/compatible-mode/v1")] + "/api/v1"
    elif base.endswith("/api"):
        base += "/v1"
    elif not base.endswith("/api/v1") and ".aliyuncs.com" in base:
        base += "/api/v1"
    return base


def dashscope_url(path: str) -> str:
    return dashscope_api_base().rstrip("/") + "/" + path.lstrip("/")
