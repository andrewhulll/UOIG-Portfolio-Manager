"""Anthropic-backed research co-pilot for the terminal's Ask-Claude chat.

A thin wrapper over the Messages API (model claude-haiku-4-5). The API key is read
from the ANTHROPIC_API_KEY environment variable, falling back to a git-ignored
`anthropic.key.txt` at the repo root (same pattern as the Kalshi key). The system
prompt — built by the caller — grounds answers in the live portfolio.
"""
from __future__ import annotations

import os
from pathlib import Path

MODEL = "claude-haiku-4-5"
_KEY_FILE = Path(__file__).resolve().parents[1] / "anthropic.key.txt"


def _parse_key(text: str) -> str | None:
    """Accept a bare key, a `ANTHROPIC_API_KEY=...` line, or a quoted value."""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and not line.startswith("sk-"):
            line = line.split("=", 1)[1]
        line = line.strip().strip('"').strip("'").strip()
        if line:
            return line
    return None


def api_key() -> str | None:
    """ANTHROPIC_API_KEY env var, else anthropic.key.txt, else None."""
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env and env.strip():
        return _parse_key(env)
    try:
        return _parse_key(_KEY_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


# Only the most recent turns are sent each request, to bound input-token cost.
HISTORY_LIMIT = 8
# Max model round-trips per question when it reads repo files (bounds tool-use cost).
MAX_TOOL_TURNS = 6
# Anthropic-hosted web search (runs server-side; results stream back in the same
# response). Basic variant `web_search_20250305` is the one Haiku 4.5 supports —
# the `_20260209` dynamic-filtering variant needs Opus 4.6+/Sonnet 4.6. `max_uses`
# caps searches per question to bound cost.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 4}

# Anthropic prompt caching: the system prompt and tool schemas are identical on
# every turn of the tool loop below (and often across a user's next question,
# within the ~5min cache TTL) but were being re-billed as full input tokens on
# every single API call. Marking a cache_control breakpoint writes/reads a cache
# entry for everything up to that point, so a 6-round tool loop pays full system+
# tools cost once instead of up to 6x. `_CACHE` is reused at each breakpoint.
_CACHE = {"type": "ephemeral"}


def _cached_system(system: str) -> list[dict]:
    return [{"type": "text", "text": system, "cache_control": _CACHE}]


def _cached_tools(tools: list[dict]) -> list[dict]:
    """Cache the (static) tool schemas by marking the last one — a cache
    breakpoint covers everything before it, so this alone caches all of them."""
    if not tools:
        return tools
    return [*tools[:-1], {**tools[-1], "cache_control": _CACHE}]


def _with_trailing_cache(content):
    """Copy of a message's content with a cache breakpoint on its last block, so
    each tool-loop round caches the conversation-so-far for the next round."""
    if isinstance(content, str):
        return [{"type": "text", "text": content, "cache_control": _CACHE}]
    blocks = [b.model_dump() if hasattr(b, "model_dump") else dict(b) for b in content]
    if blocks:
        blocks[-1] = {**blocks[-1], "cache_control": _CACHE}
    return blocks


# Claude Haiku 4.5 published rates, USD per million tokens. Cache write/read are
# the standard Anthropic multipliers on the base input rate (1.25x / 0.1x).
PRICE_PER_MTOK = {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10}


def _empty_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def cost_usd(usage: dict) -> float:
    """Estimated USD cost of a usage tally, for a session running cost display."""
    return (
        usage.get("input_tokens", 0) * PRICE_PER_MTOK["input"]
        + usage.get("output_tokens", 0) * PRICE_PER_MTOK["output"]
        + usage.get("cache_creation_input_tokens", 0) * PRICE_PER_MTOK["cache_write"]
        + usage.get("cache_read_input_tokens", 0) * PRICE_PER_MTOK["cache_read"]
    ) / 1_000_000


def _add_usage(usage: dict, resp) -> None:
    u = getattr(resp, "usage", None)
    if not u:
        return
    for key in usage:
        usage[key] += getattr(u, key, 0) or 0


def answer(messages: list[dict], system: str, max_tokens: int = 1000) -> tuple[str, dict]:
    """Run one chat turn. `messages` is the [{role, content}] history. Returns
    (reply_text, usage) — usage is summed across every API call this turn made
    (the tool loop can call the model more than once), for a session cost meter."""
    key = api_key()
    if not key:
        raise RuntimeError("no_key")

    import anthropic  # imported lazily so the app boots without the SDK installed

    client = anthropic.Anthropic(api_key=key)
    msgs = [
        {"role": ("assistant" if m.get("role") == "assistant" else "user"),
         "content": str(m.get("content", ""))}
        for m in messages if str(m.get("content", "")).strip()
    ]
    msgs = msgs[-HISTORY_LIMIT:]
    # The Messages API requires the first turn to be a user message.
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    usage = _empty_usage()
    if not msgs:
        return "Ask me anything about the portfolio.", usage

    from src import repo_tools, data_tools
    tools = _cached_tools(repo_tools.TOOLS + data_tools.TOOLS + [WEB_SEARCH_TOOL])
    cached_system = _cached_system(system)

    def _run(name, inp):
        return repo_tools.run_tool(name, inp) or data_tools.run_tool(name, inp) or (f"Unknown tool: {name}", True)

    # Manual agentic loop: let the model read the repo + per-stock data on demand, capped.
    def _text(resp):
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    for _ in range(MAX_TOOL_TURNS):
        call_msgs = [*msgs[:-1], {**msgs[-1], "content": _with_trailing_cache(msgs[-1]["content"])}]
        resp = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=cached_system, messages=call_msgs, tools=tools,
        )
        _add_usage(usage, resp)
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            # Server tools (web search) run inline; a long search can yield
            # stop_reason 'pause_turn' — feed the partial turn back to resume.
            if getattr(resp, "stop_reason", None) == "pause_turn":
                msgs.append({"role": "assistant", "content": resp.content})
                continue
            return _text(resp), usage
        msgs.append({"role": "assistant", "content": resp.content})
        results = []
        for b in tool_uses:
            content, is_error = _run(b.name, b.input)
            results.append({"type": "tool_result", "tool_use_id": b.id,
                            "content": content, "is_error": is_error})
        msgs.append({"role": "user", "content": results})

    return _text(resp) or "(stopped after reading the repository — try a narrower question.)", usage
