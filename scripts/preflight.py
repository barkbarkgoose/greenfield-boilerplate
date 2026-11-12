#!/usr/bin/env python3
"""Preflight checks: local tooling, keychain, and project-specific services.

Run from the project root:  ./scripts/preflight.sh  [--skip-remote]

Generic checks live here and are shared across projects. Project-specific
checks live in an optional sibling module, ``scripts/preflight_project.py``,
which may define:

    REQUIRED_SETTINGS: list[str]   # keys that must resolve (env, then keychain)
    BASE_URL_SETTINGS: list[str]   # subset that must be a bare scheme://host[:port]
    def add_arguments(parser): ... # optional extra CLI flags
    def run(pf, args): ...         # extra checks; skipped with --skip-remote

``pf`` is this module, so hooks can call ``pf.section``, ``pf.ok``, ``pf.warn``,
``pf.fail``, ``pf.setting`` and ``pf.http_json``. Secret values are never printed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
sys.path.insert(0, str(BACKEND_DIR))

from keychain import KeychainNotInitializedError, get as keychain_get  # noqa: E402
from keychain.core import is_key_file_secure  # noqa: E402

GREEN, YELLOW, RED, BOLD, RESET = "\033[92m", "\033[93m", "\033[91m", "\033[1m", "\033[0m"
failures = 0


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET} {msg}")


def fail(msg: str) -> None:
    global failures
    failures += 1
    print(f"  {RED}✗{RESET} {msg}")


def setting(key: str) -> str | None:
    """Resolve a setting the same way Django settings do: environment, then keychain."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        return keychain_get(key)
    except KeychainNotInitializedError:
        return None


def http_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict | None = None,
    timeout: float = 30,
) -> tuple[int, dict | list | str]:
    """GET (or POST when ``body`` is given) and return ``(status, parsed JSON or text)``.

    Raises ``urllib.error.URLError`` / ``TimeoutError`` when the host is unreachable.
    """
    all_headers = {"Accept": "application/json", "User-Agent": "preflight", **(headers or {})}
    data = None
    if body is not None:
        all_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=all_headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw, status = resp.read().decode(), resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode(errors="replace"), exc.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw[:200]


def _load_project_hook():
    path = Path(__file__).with_name("preflight_project.py")
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("preflight_project", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_tools() -> None:
    section("Local tooling")
    for tool in ("uv", "node", "pnpm"):
        path = shutil.which(tool)
        if not path:
            fail(f"{tool} not found on PATH")
            continue
        # A shim can exist on PATH yet point at a missing install (e.g. a stale
        # Volta image), so run it rather than trusting `which`.
        proc = subprocess.run([path, "--version"], capture_output=True, text=True)
        if proc.returncode != 0:
            first_err = next((ln for ln in proc.stderr.splitlines() if "Error" in ln), "").strip()
            fail(f"{tool} is on PATH but broken ({path}): {first_err or f'exit {proc.returncode}'}")
            continue
        ok(f"{tool} {proc.stdout.strip()}")

    # The default database is a local PostgreSQL over the socket (dev.sh creates it).
    if not shutil.which("pg_isready"):
        fail("PostgreSQL not found on PATH — `brew install postgresql@16`")
    elif subprocess.run(["pg_isready", "-q"]).returncode != 0:
        fail("PostgreSQL is not accepting connections — `brew services start postgresql@16`")
    else:
        ok("PostgreSQL accepting connections")

    pinned = _pinned_pnpm()
    if pinned and shutil.which("pnpm"):
        proc = subprocess.run(["pnpm", "--version"], capture_output=True, text=True, cwd=FRONTEND_DIR)
        if proc.returncode == 0 and proc.stdout.strip() != pinned:
            warn(f"pnpm {proc.stdout.strip()} differs from packageManager pin pnpm@{pinned}")

    if (FRONTEND_DIR / "node_modules").is_dir():
        ok("frontend/node_modules present")
    else:
        warn("frontend/node_modules missing — run `pnpm install` in frontend/")


def _pinned_pnpm() -> str | None:
    try:
        manager = json.loads((FRONTEND_DIR / "package.json").read_text()).get("packageManager", "")
    except (OSError, json.JSONDecodeError):
        return None
    name, _, ver = manager.partition("@")
    return ver.split("+")[0] if name == "pnpm" and ver else None


def check_keychain(required: list[str], base_urls: list[str]) -> None:
    section("Keychain / config")
    try:
        keychain_get("__preflight_probe__")
        ok("keychain initialized")
        if is_key_file_secure():
            ok("keychain.key permissions are owner-only")
        else:
            fail("backend/keychain.key is readable by others — chmod 600 it")
    except KeychainNotInitializedError:
        fail("keychain not initialized — `cd backend && uv run python -m keychain init --from-example`")

    for key in required:
        value = setting(key)
        if not value:
            fail(f"{key} not set")
        elif key in base_urls:
            check_base_url(key, value)
        elif key.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")):
            ok(f"{key} set ({len(value)} chars)")
        else:
            ok(f"{key} = {value}")


def check_base_url(key: str, value: str) -> None:
    """A base URL must be scheme://host[:port] with no path, query or trailing slash.

    Callers append endpoint paths to it, so a stored path (e.g. `/api/v1/leads`)
    turns every request into a confusing 404.
    """
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        fail(f"{key} = {value!r} is not an http(s) URL")
    elif parts.path not in ("", "/") or parts.query or parts.fragment:
        fail(f"{key} = {value} must be the bare host; drop {parts.path or '?' + parts.query!r}")
    elif value.endswith("/"):
        fail(f"{key} = {value} has a trailing slash; remove it")
    else:
        ok(f"{key} = {value}")


def main() -> int:
    hook = _load_project_hook()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-remote", action="store_true", help="only check the local setup")
    if hook and hasattr(hook, "add_arguments"):
        hook.add_arguments(parser)
    args = parser.parse_args()

    check_tools()
    check_keychain(
        list(getattr(hook, "REQUIRED_SETTINGS", [])),
        list(getattr(hook, "BASE_URL_SETTINGS", [])),
    )
    if hook and hasattr(hook, "run") and not args.skip_remote:
        if failures:
            warn("skipping project checks until the failures above are fixed")
        else:
            hook.run(sys.modules[__name__], args)

    print()
    if failures:
        print(f"{RED}{BOLD}{failures} check(s) failed{RESET}")
        return 1
    print(f"{GREEN}{BOLD}All preflight checks passed{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
