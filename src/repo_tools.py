"""Read-only repository tools for the Ask-Claude co-pilot.

Exposes list_files / read_file / search_repo to the model so it can answer
questions about how the terminal is built. Access is deliberately narrow:

  * only an allowlist of code/document extensions and filenames is readable,
  * any path under a sensitive directory (data/, node_modules, .git, .venv,
    dist, build, .claude, …) is denied,
  * credential-like names and general-purpose secret text files are denied,
  * every path is resolved and confined to the repo root (no traversal),
  * file reads and listings are size/count-capped to bound token cost.

The model cannot write anything — these tools only read.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ALLOWED_EXT = {
    ".md", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".html", ".css", ".toml", ".cfg", ".ini", ".sh",
}
ALLOWED_FILENAMES = {"requirements.txt"}
DENY_DIRS = {"node_modules", "__pycache__", ".git", ".venv", "venv", "dist",
             "build", ".claude", "data", "scratchpad", ".streamlit"}
DENY_NAME = re.compile(
    r"(^workos\.|^supabase\.|\.key($|\.)|\.pem$|\.env|secret|credential|"
    r"password|passwd|token|api[._-]?key|\.db$|\.sqlite)",
    re.I,
)
MAX_BYTES = 60_000
MAX_LIST = 400
MAX_HITS = 40


def _safe(rel: Path) -> bool:
    """True if a repo-relative path is allowed to be read."""
    if any(part in DENY_DIRS or part.startswith(".") and part not in (".gitignore",)
           for part in rel.parts[:-1]):
        return False
    if DENY_NAME.search(rel.name):
        return False
    return rel.name.lower() in ALLOWED_FILENAMES or rel.suffix.lower() in ALLOWED_EXT


def _resolve(path: str) -> Path | None:
    try:
        p = (REPO / path).resolve()
        rel = p.relative_to(REPO)
    except (ValueError, OSError):
        return None
    return p if _safe(rel) else None


def _walk(base: Path):
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in DENY_DIRS and not d.startswith(".")]
        for f in files:
            rel = Path(root, f).relative_to(REPO)
            # Resolve every candidate through the same confinement check used by
            # read_file. This also prevents an allowed-looking symlink from
            # exposing a secret or a file outside the repository.
            if _resolve(str(rel)) is not None:
                yield str(rel).replace("\\", "/")


def list_files(subdir: str = "") -> str:
    base = (REPO / (subdir or "")).resolve()
    if base != REPO and REPO not in base.parents:
        return "(invalid directory)"
    out = sorted(set(_walk(base)))[:MAX_LIST]
    return "\n".join(out) if out else "(no readable files here)"


def read_file(path: str) -> tuple[str, bool]:
    p = _resolve(path)
    if not p or not p.is_file():
        return (f"Not readable: {path} (missing, or excluded for safety).", True)
    try:
        data = p.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return (f"Could not read {path}: {exc}", True)
    if len(data) > MAX_BYTES:
        data = data[:MAX_BYTES] + f"\n…[truncated at {MAX_BYTES} chars]"
    return (data, False)


def search_repo(query: str, max_results: int = MAX_HITS) -> str:
    try:
        rx = re.compile(query, re.I)
    except re.error:
        rx = re.compile(re.escape(query), re.I)
    hits = []
    for rel in _walk(REPO):
        p = _resolve(rel)
        if p is None:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                if len(hits) >= min(max_results, MAX_HITS):
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "(no matches)"


# ---------- Anthropic tool definitions + dispatch ----------
TOOLS = [
    {"name": "list_files",
     "description": "List readable files in the project repository, optionally under a "
                    "subdirectory (e.g. 'src', 'web/src', 'api'). Returns relative paths. "
                    "Use this first to discover what exists.",
     "input_schema": {"type": "object", "properties": {
         "subdir": {"type": "string", "description": "Subdirectory to list; omit for repo root."}}}},
    {"name": "read_file",
     "description": "Read a UTF-8 text/code/doc file by its repo-relative path "
                    "(e.g. 'README.md', 'src/analytics/pnl.py', 'web/src/App.jsx'). "
                    "Returns the file contents.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Repo-relative file path."}},
         "required": ["path"]}},
    {"name": "search_repo",
     "description": "Search the repository for a string or regex across readable files. "
                    "Returns matching 'path:line: snippet' results.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "max_results": {"type": "integer", "description": "Cap on matches (default 40)."}},
         "required": ["query"]}},
]


def run_tool(name: str, inp: dict):
    """Execute a repo tool. Returns (content, is_error), or None if not handled here."""
    try:
        if name == "read_file":
            return read_file(str((inp or {}).get("path", "")))
        if name == "list_files":
            return (list_files(str((inp or {}).get("subdir", "") or "")), False)
        if name == "search_repo":
            return (search_repo(str((inp or {}).get("query", "")),
                                int((inp or {}).get("max_results") or MAX_HITS)), False)
    except Exception as exc:  # noqa: BLE001 — never let a tool error crash the turn
        return (f"Tool error: {exc}", True)
    return None
