"""ND-18b: the answer checker stage (off by default; ``[answer] checker``).

After the answer (and H2), the prompt, question and answer go to an out-of-process checker server
(``benchmarks/answer_checker/server.py``), which returns P(the answer is correct according to the context).
A fixed rule decides (P3): below ``checker_threshold``, or an input over the checker's limit ("skipped"), the
same messages are re-answered by ``escalation_model``. The checker unreachable keeps the first answer and records
the error (fail-open).

Memory (ND-18 amendment): while the escalation model answers, neither the first answer model nor the checker may be
resident. Before an escalation the checker frees its weights and the first model is unloaded; after it the
escalation model is unloaded. Unloading is done through Ollama's native API, so it applies when
``[llm] provider = "ollama"``; with any other provider nothing is loaded locally and the swap is skipped.
If the swap cannot be completed, the first answer is kept (the escalation is not run with two models resident).

Stdlib only: campy imports no torch (tests/test_no_torch_dependency.py).
"""
from __future__ import annotations

import copy
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

_logger = logging.getLogger(__name__)

UNLOAD_WAIT_SECONDS = 60.0


class CheckerUnavailable(RuntimeError):
    """The checker server could not be reached or replied with something unusable."""


def checker_enabled(config: dict) -> bool:
    return bool((config.get("answer") or {}).get("checker", False))


def _answer_cfg(config: dict) -> dict:
    return config.get("answer") or {}


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


def check_answer(url: str, context: str, question: str, answer: str, timeout: float) -> dict:
    """Ask the checker. Returns {"status": "ok", "p_correct": float, ...} or {"status": "skipped", ...}.

    Raises CheckerUnavailable when the server is unreachable or its reply is not one of those two shapes.
    """
    try:
        out = _post_json(url.rstrip("/") + "/check",
                         {"context": context, "question": question, "answer": answer}, timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:  # URLError, timeout, refused, bad JSON
        raise CheckerUnavailable(repr(exc)[:300]) from exc
    status = out.get("status")
    if status == "ok" and isinstance(out.get("p_correct"), (int, float)):
        return out
    if status == "skipped":
        return out
    raise CheckerUnavailable(f"unexpected checker reply: {json.dumps(out)[:300]}")


def release_checker(url: str, timeout: float) -> None:
    """Ask the checker to free its weights (it reloads on the next /check)."""
    try:
        out = _post_json(url.rstrip("/") + "/release", {}, timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CheckerUnavailable(repr(exc)[:300]) from exc
    if out.get("status") != "released":
        raise CheckerUnavailable(f"unexpected release reply: {json.dumps(out)[:300]}")


def _ollama_host(config: dict) -> str:
    base = (config.get("llm") or {}).get("base_url", "http://localhost:11434/v1").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _loaded_models(host: str, timeout: float) -> list[str]:
    with urllib.request.urlopen(host + "/api/ps", timeout=timeout) as resp:
        return [m.get("name") or m.get("model") for m in json.loads(resp.read().decode()).get("models", [])]


def _tagged(name: str) -> str:
    """Ollama lists models with a tag; an untagged name means ":latest"."""
    name = (name or "").strip()
    return name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"


def unload_model(config: dict, model: str, timeout: float = 30.0, wait: float = UNLOAD_WAIT_SECONDS) -> None:
    """Unload ``model`` from the local Ollama server and wait until /api/ps no longer lists it."""
    host = _ollama_host(config)
    try:
        _post_json(host + "/api/generate", {"model": model, "keep_alive": 0}, timeout)
        deadline = time.monotonic() + wait
        want = _tagged(model)
        while want in {_tagged(m) for m in _loaded_models(host, timeout) if m}:
            if time.monotonic() > deadline:
                raise RuntimeError(f"{model} still resident after {wait:.0f}s")
            time.sleep(0.25)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"unload {model}: {exc!r}"[:300]) from exc


def _escalation_client(config: dict, model: str, max_tokens: int):
    from campy.brain.llm.provider import create_llm_client
    cfg = copy.deepcopy(config)
    cfg.setdefault("llm", {})
    cfg["llm"]["model"] = model
    cfg["llm"]["max_tokens"] = max_tokens
    return create_llm_client(cfg)


async def apply_checker(answer: str, messages: list[dict], prompt: str, query: str, config: dict,
                        meta: Optional[dict] = None) -> str:
    """Run the checker on ``answer`` and escalate when the rule says so. Returns the final answer."""
    import asyncio

    acfg = _answer_cfg(config)
    url = acfg.get("checker_url", "http://127.0.0.1:8765")
    threshold = float(acfg.get("checker_threshold", 0.5))
    timeout = float(acfg.get("checker_timeout_seconds", 120))
    esc_model = (acfg.get("escalation_model") or "").strip()
    esc_cap = int(acfg.get("escalation_max_tokens", 8192))
    rec: dict = {"answer_unchecked": answer, "checker_p": None, "checker_status": None, "checker_error": None,
                 "escalated": False, "answer_escalated": None, "escalation_usage": None, "escalation_error": None, "swap_s": None}

    def _done(final: str) -> str:
        if meta is not None:
            meta.update(rec)
        return final

    try:
        res = await asyncio.to_thread(check_answer, url, prompt, query, answer, timeout)
    except CheckerUnavailable as exc:
        _logger.warning("ND-18b: answer checker unavailable, keeping the first answer: %s", exc)
        rec["checker_status"], rec["checker_error"] = "error", str(exc)
        return _done(answer)

    rec["checker_status"] = res["status"]
    rec["checker_load_s"] = res.get("load_s")
    if res["status"] == "ok":
        rec["checker_p"] = float(res["p_correct"])
        if rec["checker_p"] >= threshold:
            return _done(answer)
    else:
        rec["checker_error"] = res.get("error")
    if not esc_model:
        return _done(answer)
    rec["escalated"] = True  # the rule decided; answer_escalated holds what the escalation model said

    llm_cfg = config.get("llm") or {}
    local = llm_cfg.get("provider", "ollama").lower() == "ollama"
    first_model = (llm_cfg.get("model") or "").strip()
    swap: dict = {}
    t = time.perf_counter()
    try:
        await asyncio.to_thread(release_checker, url, timeout)
        swap["release_checker_s"] = round(time.perf_counter() - t, 2)
        if local:
            if not first_model:
                raise RuntimeError("[llm] model is not set, so the first answer model cannot be unloaded")
            t = time.perf_counter()
            await asyncio.to_thread(unload_model, config, first_model)
            swap["unload_first_s"] = round(time.perf_counter() - t, 2)
    except (CheckerUnavailable, RuntimeError) as exc:
        _logger.warning("ND-18b: swap before escalation failed, keeping the first answer: %s", exc)
        rec["escalation_error"], rec["swap_s"] = f"swap: {exc}"[:300], swap
        return _done(answer)

    final = answer
    esc = _escalation_client(config, esc_model, esc_cap)
    t = time.perf_counter()
    try:
        if esc is None:
            raise RuntimeError("escalation client unavailable")
        out = await esc.achat(messages, max_tokens=esc_cap)
        rec["escalation_usage"] = dict(getattr(esc, "last_usage", None) or {}) or None
        rec["answer_escalated"] = out
        if out and out.strip():
            final = out
        else:
            rec["escalation_error"] = "empty escalation answer"
    except Exception as exc:  # the first answer stands
        rec["escalation_error"] = repr(exc)[:300]
    swap["escalation_answer_s"] = round(time.perf_counter() - t, 2)
    if local:
        t = time.perf_counter()
        try:
            await asyncio.to_thread(unload_model, config, esc_model)
        except RuntimeError as exc:
            swap["unload_escalation_error"] = str(exc)[:300]
        swap["unload_escalation_s"] = round(time.perf_counter() - t, 2)
    rec["swap_s"] = swap
    return _done(final)
