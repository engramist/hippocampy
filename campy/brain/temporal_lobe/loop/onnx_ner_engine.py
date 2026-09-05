"""
ONNX NER engine (B387) — replaces spaCy's `en_core_web_md` NER component.

Model: onnx-community/distilbert-base-cased-finetuned-conll03-english-ONNX
  - Mechanical ONNX/int8 conversion (HF `onnx-community` org, via Optimum)
    of `elastic/distilbert-base-cased-finetuned-conll03-english`. The base
    model's own cardData declares `license: apache-2.0` (verified directly
    via `GET https://huggingface.co/api/models/elastic/distilbert-base-
    cased-finetuned-conll03-english` -- the `onnx-community` conversion
    repo itself carries no license tag at all, so the base model's card is
    the authority here, not the mirror). A pure format/quantization
    conversion carries no new copyrightable expression, so it inherits the
    base model's license -- the same judgment call already made for
    fastembed's embedding model in B355 (sentence-transformers/all-MiniLM-
    L6-v2 via its "ONNX conversion, qdrant/all-MiniLM-L6-v2-onnx").
  - Training-data provenance (CoNLL-2003 / Reuters RCV1) was investigated
    separately at Gate 0 -- see backlog/B387.md and the PR description for
    the full writeup. Summary: the Reuters/NIST agreement gates
    redistribution of the raw news-article text, not use of statistical
    models fine-tuned on it; `elastic` (the fine-tuner) made an explicit,
    unchanged-since-2022 Apache-2.0 grant on the weights, and the same
    provenance pattern (CoNLL-2003-trained, permissively licensed) is
    industry-standard practice -- e.g. `dslim/bert-base-NER` (MIT,
    ~2.1M downloads/month). Residual risk is the same class of "is a
    trained model a derivative work of its training corpus" ambiguity that
    applies to virtually every pretrained NLP model, not something specific
    to this one; flagged for counsel review given the active patent filing,
    not blocked on it.
  - int8 quantized weights: ~65.7 MB on disk (onnx/model_quantized.onnx).
  - 4 entity types: PER, ORG, LOC, MISC (CoNLL-2003 tag set) -- narrower
    than spaCy's 18-type OntoNotes scheme, mapped onto the same label
    strings step3_schema_org.py's _AGENT_SPACY_MAP already branches on
    (PERSON, ORG); GPE/MISC pass through unbranched, same as any spaCy
    label other than PERSON/ORG did before.

Distribution / offline runtime:
  - `download_model()` (network allowed) is called once at install time
    (campy/cli/install.py's install_ner_model(), mirroring the old spaCy
    model download and the existing prewarm_embeddings() step) and caches
    the two files via huggingface_hub's normal on-disk cache -- respects
    `HF_HOME` (falls back to ~/.cache/huggingface/hub) exactly like
    fastembed's embedding model does in campy/brain/hippocampus/graph/
    embeddings.py's _get_fe_model().
  - `get_engine()` (used at daemon runtime) always resolves with
    `local_files_only=True` -- zero egress at first inference,
    unconditionally (stricter than embeddings.py's HF_HUB_OFFLINE-gated
    `local_files_only=offline`; there is no local-dev reason for NER to
    ever reach the network at inference time, so this card didn't add an
    `[nlp].offline` config toggle to match -- `download_model()` at
    install/build time is the only network path). A cache miss raises a
    clear RuntimeError instead of silently reaching out to the network.

  Container build-time fetch (B385, zero-egress AWS Fargate target): set
  `HF_HOME` to a directory baked into the image (matching whatever
  fastembed's ONNX model pre-bake step already does there) and call
  `download_model()` once during the image build, *before* `ENV
  HF_HOME=...` is relied on at runtime -- huggingface_hub resolves the
  cache from `HF_HOME` automatically, no code change needed here. As of
  this writing `deploy/Dockerfile` (named in backlog/B385.md as already
  built) is not present in this repository -- see backlog/B387.md's PR
  description for that discrepancy. This module's contract (HF_HOME-
  driven cache, local_files_only=True at runtime, clear failure on a
  cache miss) is ready for whatever Dockerfile bakes it in; wiring an
  actual `RUN python -c "...download_model()"` build step is tracked as
  follow-up work, not blocking this card.
"""

from __future__ import annotations

import threading

import numpy as np

MODEL_REPO = "onnx-community/distilbert-base-cased-finetuned-conll03-english-ONNX"
MODEL_FILE = "onnx/model_quantized.onnx"
TOKENIZER_FILE = "tokenizer.json"

_ID2LABEL = {
    0: "O", 1: "B-PER", 2: "I-PER", 3: "B-ORG", 4: "I-ORG",
    5: "B-LOC", 6: "I-LOC", 7: "B-MISC", 8: "I-MISC",
}

# CoNLL tag -> the label vocabulary the rest of the Loop already expects
# (step3_schema_org._AGENT_SPACY_MAP branches on PERSON/ORG specifically;
# GPE/MISC are carried through unbranched, matching how any non-PERSON/ORG
# spaCy label behaved before).
_LABEL_MAP = {"PER": "PERSON", "ORG": "ORG", "LOC": "GPE", "MISC": "MISC"}


def download_model() -> tuple[str, str]:
    """Fetch (and cache) the ONNX model + tokenizer files. Network allowed --
    call this only from the install/prewarm path, never from the daemon's
    hot path."""
    from huggingface_hub import hf_hub_download
    model_path = hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE)
    tokenizer_path = hf_hub_download(repo_id=MODEL_REPO, filename=TOKENIZER_FILE)
    return model_path, tokenizer_path


def _resolve_local(local_files_only: bool) -> tuple[str, str]:
    from huggingface_hub import hf_hub_download
    try:
        model_path = hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE,
                                      local_files_only=local_files_only)
        tokenizer_path = hf_hub_download(repo_id=MODEL_REPO, filename=TOKENIZER_FILE,
                                          local_files_only=local_files_only)
    except Exception as exc:  # huggingface_hub raises its own not-found errors
        raise RuntimeError(
            "ONNX NER model not found in the local cache. Run the install "
            "step (`campy install` / VenvManager.install_ner_model()) once "
            "with network access before starting the daemon, or -- in a "
            "container build -- pre-bake it into the image cache (set "
            "HF_HOME to a directory baked into the image and call "
            "onnx_ner_engine.download_model() during the build, the same "
            "way fastembed's embedding model is pre-baked)."
        ) from exc
    return model_path, tokenizer_path


class OnnxNerEngine:
    """Loads the ONNX session + tokenizer once; `predict()` is the hot path."""

    def __init__(self, local_files_only: bool = True):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path, tokenizer_path = _resolve_local(local_files_only)

        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            model_path, sess_options=so, providers=["CPUExecutionProvider"],
        )
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=512)

    def predict(self, text: str) -> list[dict]:
        """Run NER and return [{"text","label","start","end"}, ...] --
        the same shape step1_ner.py has always produced from doc.ents."""
        if not text.strip():
            return []

        enc = self._tokenizer.encode(text)
        input_ids = np.asarray([enc.ids], dtype=np.int64)
        attention_mask = np.asarray([enc.attention_mask], dtype=np.int64)
        outputs = self._session.run(None, {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        })
        logits = outputs[0][0]              # (seq_len, num_labels)
        preds = logits.argmax(axis=-1)
        offsets = enc.offsets
        word_ids = enc.word_ids

        # Reduce subword-token predictions to one label per whitespace word
        # (first-subtoken label, extended to the last subtoken's end offset).
        # Needed because WordPiece shatters out-of-vocabulary compound tech
        # terms ("PostgreSQL", "KuzuDB") into many pieces, and this model
        # (fine-tuned on 2003 Reuters news) predicts an inconsistent B-TYPE
        # for *each* piece rather than B-TYPE then I-TYPE continuations --
        # merging by word_id first, then by adjacency+matching-type second,
        # is what actually recovers "PostgreSQL" as one span (see B387 Gate
        # 0 spike notes for the naive per-subtoken merge that broke this).
        words: dict[int, dict] = {}
        for pred_id, (start, end), wid in zip(preds, offsets, word_ids):
            if wid is None or start == end:
                continue
            label = _ID2LABEL[int(pred_id)]
            if wid not in words:
                words[wid] = {"label": label, "start": start, "end": end}
            else:
                words[wid]["end"] = end

        ordered = [words[w] for w in sorted(words)]

        spans = []
        cur = None
        for w in ordered:
            if w["label"] == "O":
                if cur:
                    spans.append(cur)
                    cur = None
                continue
            etype = w["label"].split("-", 1)[1]
            if cur is not None and cur["type"] == etype:
                cur["end"] = w["end"]
            else:
                if cur:
                    spans.append(cur)
                cur = {"type": etype, "start": w["start"], "end": w["end"]}
        if cur:
            spans.append(cur)

        return [
            {
                "text": text[s["start"]:s["end"]],
                "label": _LABEL_MAP.get(s["type"], s["type"]),
                "start": s["start"],
                "end": s["end"],
            }
            for s in spans
        ]


_engine: OnnxNerEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> OnnxNerEngine:
    """Module-level singleton, lazily constructed on first use (mirrors the
    old spaCy `get_nlp()` cache in step1_ner.py). Always resolves the model
    from the local cache only -- zero egress at inference time."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = OnnxNerEngine(local_files_only=True)
    return _engine
