"""tests/cli/test_recall_unwrap.py — B440.

A raw `tools/call` JSON-RPC response nests the actual tool output as a
JSON-encoded string at result.content[0].text (the MCP envelope), not
as a flat dict directly under "result". Every command in recall.py
(recall/bundle/timeline/diff/decide/dispatch/context/handoff) does
`result.get("result", ...)` expecting a flat dict -- without
_unwrap_tool_result, every one of those commands silently got an
empty/placeholder result against a real daemon. Confirmed by hand
against a live daemon while testing B440's SessionEnd hook: both
`campy decide` and `campy dispatch` printed "?"/"N/A" placeholders for
every field before this fix.

This bug predates B440 and B382 (the `decide` command, and this
response shape, are older than either) -- not introduced by either.
"""

from __future__ import annotations

import json

from campy.cli.recall import _unwrap_tool_result


def test_unwraps_real_mcp_tool_call_envelope():
    """The exact shape a real daemon returns for a successful
    `tools/call`, confirmed by hand against the live daemon."""
    inner = {"tier": "frontier", "recommended_model": "claude-opus-5"}
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": json.dumps(inner)}]},
    }

    unwrapped = _unwrap_tool_result(response)

    assert unwrapped["result"] == inner


def test_leaves_error_response_untouched():
    response = {"jsonrpc": "2.0", "id": 1, "error": {"message": "boom"}}
    assert _unwrap_tool_result(response) == response


def test_leaves_local_connection_error_untouched():
    """The locally-fabricated error dict _send() returns on a
    ConnectionError has no "result" key at all -- must pass through
    unchanged, not raise."""
    response = {"error": {"message": "Daemon not running. Start with: campy start"}}
    assert _unwrap_tool_result(response) == response


def test_leaves_already_flat_result_untouched():
    """If some future/different response shape already has a flat
    dict under "result" (no "content" wrapper), don't break it."""
    response = {"jsonrpc": "2.0", "id": 1, "result": {"tier": "economy"}}
    assert _unwrap_tool_result(response) == response


def test_leaves_non_json_text_content_untouched():
    """A tool that returns plain text (not a JSON-encoded dict) must
    not raise -- the response passes through with its original
    (unparseable) content intact."""
    response = {
        "jsonrpc": "2.0", "id": 1,
        "result": {"content": [{"type": "text", "text": "plain text answer"}]},
    }
    original = json.loads(json.dumps(response))  # deep copy

    unwrapped = _unwrap_tool_result(response)

    assert unwrapped == original


def test_leaves_empty_response_untouched():
    assert _unwrap_tool_result({}) == {}


def test_leaves_non_text_content_type_untouched():
    response = {
        "jsonrpc": "2.0", "id": 1,
        "result": {"content": [{"type": "image", "data": "base64..."}]},
    }
    original = json.loads(json.dumps(response))
    assert _unwrap_tool_result(response) == original
