"""Helpers for running Remotion without downloading a browser."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


_ENV_VARS = (
    "REMOTION_BROWSER_EXECUTABLE",
    "CHROME_EXECUTABLE",
    "PUPPETEER_EXECUTABLE_PATH",
)


def find_browser_executable() -> str | None:
    """Return a local Chrome/Chromium executable path for Remotion if found."""

    for env_var in _ENV_VARS:
        value = os.environ.get(env_var)
        if value and Path(value).exists():
            return str(Path(value))

    names = (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    )
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved

    if sys.platform == "darwin":
        candidates = (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path.home() / "Applications/Chromium.app/Contents/MacOS/Chromium",
        )
    elif sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("PROGRAMFILES")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
        candidates = tuple(
            Path(base) / suffix
            for base in (program_files, program_files_x86, local_app_data)
            if base
            for suffix in (
                "Google/Chrome/Application/chrome.exe",
                "Chromium/Application/chrome.exe",
            )
        )
    else:
        candidates = ()

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def remotion_browser_cli_args() -> list[str]:
    """CLI flags that make Remotion use an installed browser when possible."""

    executable = find_browser_executable()
    return [f"--browser-executable={executable}"] if executable else []


def _positive_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def remotion_render_cli_args(
    *,
    concurrency: object = None,
    default_concurrency: int | None = None,
) -> list[str]:
    """CLI flags for stable local Remotion renders."""

    args = remotion_browser_cli_args()
    resolved_concurrency = (
        _positive_int(concurrency)
        or _positive_int(os.environ.get("OPENMONTAGE_REMOTION_CONCURRENCY"))
        or _positive_int(default_concurrency)
    )
    if resolved_concurrency:
        args.append(f"--concurrency={resolved_concurrency}")
    return args
