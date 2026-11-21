"""ND-18b: the `[answer] checker` stage in run_ask (off by default).

Flag off: byte-identical (same messages, same answer, checker never contacted). On: P >= threshold accepts;
P < threshold escalates (the same messages re-answered by the escalation model, after the checker is released and
the first model unloaded; the escalation model unloaded after); an over-length input ("skipped") escalates; the
checker unreachable keeps the first answer and records the error. Capture writes the final answer only.
A stub HTTP server stands in for the checker; no torch, no model.
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from campy.brain.thalamus import answer_checker as ac
from campy.brain.thalamus import bundle_compiler


class StubChecker:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                outer.calls.append((self.path, body))
                out = outer.reply if self.path == "/check" else {"status": "released"}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _bundle():
    sec = bundle_compiler.BundleSection(section_type="conversation", content=[{"text": "[Ann, 2023-05-01] hi"}],
                                        token_estimate=10, source_node_ids=["m"])
    return bundle_compiler.ContextBundle(query="q", sections=[sec], total_token_estimate=10, token_budget=32000,
                                         truncated=False, sources=[], compilation_ms=0.0)


def _llm(answer, usage):
    llm = MagicMock()
    llm.achat = AsyncMock(return_value=answer)
    llm.last_usage = usage
    return llm


def _cfg(url=None, on=True, esc="big"):
    cfg = {"llm": {"provider": "ollama", "model": "small"}}
    if url is not None or not on:
        cfg["answer"] = {"checker": on, "checker_url": url or "http://127.0.0.1:9", "checker_threshold": 0.5,
                         "escalation_model": esc, "escalation_max_tokens": 8192, "checker_timeout_seconds": 5}
    return cfg


async def _run(cfg, first, esc_llm=None, unloads=None):
    from campy.brain.thalamus.ask import run_ask
    meta: dict = {}
    cap = AsyncMock()
    unloads = [] if unloads is None else unloads
    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=_bundle()), \
            patch("campy.brain.thalamus.ask._get_llm", return_value=first), \
            patch("campy.brain.thalamus.ask._capture_turn", cap), \
            patch.object(ac, "_escalation_client", return_value=esc_llm) as mk, \
            patch.object(ac, "unload_model", side_effect=lambda c, m, **k: unloads.append(m)):
        out = await run_ask("When did Ann say hi?", "s", MagicMock(), cfg, meta=meta, capture=True)
    return out, meta, cap, mk, unloads


@pytest.mark.asyncio
async def test_flag_off_is_byte_identical():
    stub = StubChecker({"status": "ok", "p_correct": 0.1})
    try:
        a1 = _llm("first", {"prompt_tokens": 5})
        out_absent, meta_absent, cap_a, mk_a, _ = await _run(_cfg(), a1)
        a2 = _llm("first", {"prompt_tokens": 5})
        out_off, meta_off, cap_o, mk_o, _ = await _run(_cfg(stub.url, on=False), a2)
    finally:
        stub.close()
    assert out_absent == out_off == "first"
    assert a1.achat.call_args == a2.achat.call_args
    assert meta_absent == meta_off and "checker_p" not in meta_off
    assert stub.calls == [] and not mk_a.called and not mk_o.called
    assert cap_a.call_args[0][:2] == cap_o.call_args[0][:2] == ("When did Ann say hi?", "first")


@pytest.mark.asyncio
async def test_accept_keeps_the_first_answer():
    stub = StubChecker({"status": "ok", "p_correct": 0.8, "load_s": 0.0})
    try:
        first = _llm("first", {"prompt_tokens": 5})
        out, meta, cap, mk, unloads = await _run(_cfg(stub.url), first)
    finally:
        stub.close()
    assert out == "first" and meta["escalated"] is False and meta["checker_p"] == 0.8
    assert meta["answer_unchecked"] == "first" and meta["answer_usage"] == {"prompt_tokens": 5}
    assert [p for p, _ in stub.calls] == ["/check"] and not mk.called and unloads == []
    sent = stub.calls[0][1]
    assert sent["question"] == "When did Ann say hi?" and sent["answer"] == "first"
    assert sent["context"] == first.achat.call_args[0][0][1]["content"]  # the prompt the model read
    assert cap.call_args[0][1] == "first"


@pytest.mark.asyncio
async def test_escalate_reanswers_the_same_messages_with_the_swap():
    stub = StubChecker({"status": "ok", "p_correct": 0.2, "load_s": 0.0})
    try:
        first, big = _llm("first", {"prompt_tokens": 5}), _llm("second", {"prompt_tokens": 6})
        out, meta, cap, mk, unloads = await _run(_cfg(stub.url), first, big)
    finally:
        stub.close()
    assert out == "second" and meta["escalated"] is True and meta["checker_p"] == 0.2
    assert meta["answer_unchecked"] == "first" and meta["answer_escalated"] == "second"
    assert meta["answer_usage"] == {"prompt_tokens": 5} and meta["escalation_usage"] == {"prompt_tokens": 6}
    assert big.achat.call_args[0][0] == first.achat.call_args[0][0]
    assert big.achat.call_args[1] == {"max_tokens": 8192}
    assert mk.call_args[0][1:] == ("big", 8192)
    assert [p for p, _ in stub.calls] == ["/check", "/release"]
    assert unloads == ["small", "big"]  # first model out before, escalation model out after
    assert set(meta["swap_s"]) >= {"release_checker_s", "unload_first_s", "escalation_answer_s", "unload_escalation_s"}
    assert cap.call_args[0][1] == "second"  # capture writes the final answer only


@pytest.mark.asyncio
async def test_skipped_escalates():
    stub = StubChecker({"status": "skipped", "error": "input over max_length"})
    try:
        out, meta, *_ = await _run(_cfg(stub.url), _llm("first", None), _llm("second", None))
    finally:
        stub.close()
    assert out == "second" and meta["escalated"] is True
    assert meta["checker_status"] == "skipped" and meta["checker_p"] is None


@pytest.mark.asyncio
async def test_checker_down_keeps_the_answer():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{s.getsockname()[1]}"
    s.close()  # nothing listens here
    out, meta, cap, mk, unloads = await _run(_cfg(url), _llm("first", None), _llm("second", None))
    assert out == "first" and meta["escalated"] is False
    assert meta["checker_status"] == "error" and meta["checker_error"]
    assert not mk.called and unloads == [] and cap.call_args[0][1] == "first"


@pytest.mark.asyncio
async def test_failed_swap_keeps_the_answer_and_never_runs_two_models():
    stub = StubChecker({"status": "ok", "p_correct": 0.2})
    big = _llm("second", None)

    def fail(c, m, **k):
        raise RuntimeError("still resident")
    try:
        from campy.brain.thalamus.ask import run_ask
        meta: dict = {}
        with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=_bundle()), \
                patch("campy.brain.thalamus.ask._get_llm", return_value=_llm("first", None)), \
                patch.object(ac, "_escalation_client", return_value=big), \
                patch.object(ac, "unload_model", side_effect=fail):
            out = await run_ask("q", "s", MagicMock(), _cfg(stub.url), meta=meta, capture=False)
    finally:
        stub.close()
    assert out == "first" and not big.achat.called and meta["escalation_error"].startswith("swap:")


def test_stage_module_imports_no_torch():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(ac))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
             for a in getattr(n, "names", [])} | {n.module.split(".")[0] for n in ast.walk(tree)
                                                    if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"torch", "transformers", "peft"}
