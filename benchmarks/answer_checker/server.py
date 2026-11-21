"""ND-18b: the answer checker server (out of process, its own environment).

An open-weights 2B decision model gives P(the proposed answer is correct, according to the context). campy's
``[answer] checker`` stage (campy/brain/thalamus/answer_checker.py) calls it over HTTP; campy itself imports no torch.

The wording, loader and scoring are ND-17's (scratch nd17_check.py) unchanged: one yes/no ("noul") question, the
package's temperature, the head loaded weights-only, no truncation (an input over the package's max_length is
reported as "skipped", which the stage escalates). Every path is passed as an argument; nothing is downloaded
(hub offline).

Endpoints (JSON over POST unless noted):
  /check   {"context", "question", "answer"} -> {"status": "ok", "p_correct", "tokens", "latency_s", "load_s"}
                                              or {"status": "skipped", "error"}
  /release {} -> {"status": "released"}: frees the weights (the next /check reloads them), so a larger answer
           model can run with nothing else resident (ND-18 amendment).
  /health  (GET) -> {"status": "ok", "loaded": bool, "device", "dtype"}

usage: python -I server.py --vendor DIR --vendor-module NAME --package DIR --base DIR --base-rev SHA
                           [--host 127.0.0.1] [--port 8765] [--smoke]
"""
from __future__ import annotations

import argparse
import gc
import importlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

WORDING = "{q}\nProposed answer: {a}\nIs the proposed answer correct, according to the context?"


class Checker:
    def __init__(self, args):
        sys.path.insert(0, str(Path(args.vendor)))
        import torch
        from peft import PeftModel
        self.torch, self.PeftModel = torch, PeftModel
        mod = args.vendor_module
        self.DecisionModel = importlib.import_module(f"{mod}.model").DecisionModel
        api = importlib.import_module(f"{mod}.api")
        self.compile_request, self.format_response = api.compile_request, api.format_response
        self.softmax = importlib.import_module(f"{mod}.metrics").softmax
        self.pkg, self.base = Path(args.package), Path(args.base)
        self.cfg = json.loads((self.pkg / "model.json").read_text())
        if self.cfg["revision"] != args.base_rev:
            raise SystemExit(f"package expects base revision {self.cfg['revision']}, got {args.base_rev}")
        self.temp = json.loads((self.pkg / "temperature.json").read_text())["temperature"]
        self.dev = "mps" if torch.backends.mps.is_available() else "cpu"
        self.dtype = os.environ.setdefault("JEV_TORCH_DTYPE", "bfloat16")  # the released dtype
        self.model = None
        self.lock = threading.Lock()  # one request at a time: one model, one device

    def _load(self) -> float:
        if self.model is not None:
            return 0.0
        t0 = time.perf_counter()
        torch, cfg = self.torch, self.cfg
        m = self.DecisionModel(str(self.base), None, device=self.dev, lora_rank=0, max_length=cfg["max_length"])
        m.backbone = self.PeftModel.from_pretrained(m.backbone, self.pkg / "adapter")
        m.lora_rank = cfg["lora_rank"]
        m.head.load_state_dict(torch.load(self.pkg / "head.pt", map_location=self.dev, weights_only=True))
        m._validate_loaded_parameters()
        self.model = m.eval()
        return round(time.perf_counter() - t0, 2)

    def release(self) -> None:
        with self.lock:
            self.model = None
            gc.collect()
            if self.dev == "mps":
                self.torch.mps.empty_cache()

    def score(self, state, questions):
        records = self.compile_request(state, questions)
        with self.torch.inference_mode():
            logits = self.model(records)
        probs = [self.softmax(row.float().cpu().tolist(), temperature=self.temp) for row in logits]
        return self.format_response(records, probs), self.model.last_input_tokens

    def check(self, context: str, question: str, answer: str) -> dict:
        with self.lock:
            load_s = self._load()
            q = {"check": {"type": "noul", "instructions": WORDING.format(q=question, a=answer)}}
            t = time.perf_counter()
            try:
                res, ntok = self.score(context, q)
            except ValueError as e:  # over max_length: no silent truncation (as ND-17)
                return {"status": "skipped", "error": str(e)[:200], "load_s": load_s}
            return {"status": "ok", "p_correct": res["answers"]["check"]["noul"], "tokens": ntok,
                    "latency_s": round(time.perf_counter() - t, 2), "load_s": load_s}


def make_handler(checker: Checker):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                return self._reply(200, {"status": "ok", "loaded": checker.model is not None,
                                         "device": checker.dev, "dtype": checker.dtype})
            self._reply(404, {"status": "error", "error": "not found"})

        def do_POST(self):  # noqa: N802
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/check":
                    return self._reply(200, checker.check(body["context"], body["question"], body["answer"]))
                if self.path == "/release":
                    checker.release()
                    return self._reply(200, {"status": "released"})
                self._reply(404, {"status": "error", "error": "not found"})
            except Exception as e:  # the stage treats any non-ok/skipped reply as unavailable (fail-open)
                self._reply(500, {"status": "error", "error": repr(e)[:300]})

        def log_message(self, fmt, *args):  # quiet: one line per request on stderr is enough
            sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vendor", required=True, help="pinned checkout of the decision model's code")
    ap.add_argument("--vendor-module", required=True, help="the importable package name inside --vendor")
    ap.add_argument("--package", required=True, help="the released checkpoint package (model.json, adapter, head.pt)")
    ap.add_argument("--base", required=True, help="local copy of the base model the package was trained on")
    ap.add_argument("--base-rev", required=True, help="base revision the package must name in model.json")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--smoke", action="store_true", help="score the vendor's example request and exit")
    args = ap.parse_args()
    checker = Checker(args)
    if args.smoke:
        req = json.loads((Path(args.vendor) / "configs/example-request.json").read_text())
        with checker.lock:
            print(f"loaded on {checker.dev} dtype {checker.dtype} in {checker._load()}s", flush=True)
            res, ntok = checker.score(req["state"], req["questions"])
        print(json.dumps({"tokens": ntok, "result": res}, indent=1)[:2000])
        return
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(checker))
    print(f"answer checker on {args.host}:{args.port} (device {checker.dev}, lazy load)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
