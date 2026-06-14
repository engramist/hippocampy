# Campy Ask — Augmented Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `campy ask` — a thalamic compression pipeline that augments a query with graph-native memory, compresses the bundle, makes an LLM inference call, and exposes the result as both a CLI command and an MCP tool.

**Architecture:** Compression lives in `campy/brain/thalamus/compression/` as a pluggable registry of four compressors. The `ask.py` orchestrator chains `compile_bundle → classify → compress → LLMClient.chat → notify_turn`. Two thin wrappers expose the core: a Typer CLI command (`campy ask`) and an MCP tool (`ask`).

**Tech Stack:** Python 3.11+, KuzuDB 0.11.3 (existing), sentence-transformers (existing), `j2toon` (new, pure Python), `py-tree-sitter-languages` (new, pre-compiled wheels), OpenAI-SDK-compatible `LLMClient` (existing at `mcp_engine/llm/provider.py`).

**Graph note:** Campy's bundles are subgraphs — heterogeneous node types (Concept, Decision, Lesson, Plan) connected by named edges (REQUIRES, ENABLES, CONTRADICTS). Generic compressors eliminate syntax overhead; `GraphBundleCompressor` eliminates *semantic irrelevance* using graph signals. Phase A scores nodes by `cosine_similarity(query_emb, node_emb) × pathway_strength` — combining query relevance with Campy's graph-maintained consolidation weight. Phase B adds adjacency-based Personalized PageRank once `_stage_graph_structure` in `bundle_compiler.py` returns relationship data. Do not replace `GraphBundleCompressor` with TOON/ONTO — they solve different problems.

**Spec:** `docs/superpowers/specs/2026-06-13-campy-ask-augmented-inference-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `campy/brain/thalamus/compression/__init__.py` | `Compressor` ABC, `PluggableCompressorRegistry`, `ContentRouter`, default registry builder |
| Create | `campy/brain/thalamus/compression/fallback.py` | `NoOpCompressor` — passthrough |
| Create | `campy/brain/thalamus/compression/structured_data.py` | `StructuredDataCompressor` — TOON via j2toon |
| Create | `campy/brain/thalamus/compression/llm_prose.py` | `LLMCompressor` — prose via LLMClient |
| Create | `campy/brain/thalamus/compression/ast_mapper.py` | `ASTCodeCompressor` — signatures via tree-sitter |
| Create | `campy/brain/thalamus/compression/graph_bundle.py` | `GraphBundleCompressor` — graph-native node scoring + compact notation |
| Create | `campy/brain/thalamus/ask.py` | Orchestrator: augment → classify → compress → send → capture |
| Create | `campy/cli/ask.py` | Typer CLI command for `campy ask` |
| Modify | `campy/brain/thalamus/tool_schemas.py` | Add `ask` tool schema to `TOOLS` list |
| Modify | `campy/brain/thalamus/tools/__init__.py` | Add `ask` handler + register in `TOOL_HANDLERS` |
| Modify | `campy/cli/main.py` | Import and mount `ask` CLI sub-app |
| Modify | `pyproject.toml` | Add `j2toon`, `py-tree-sitter-languages` dependencies |
| Modify | `campy/brain/brainstem/config.py` | Add `[compression]` defaults |
| Create | `tests/test_compression_structured.py` | StructuredDataCompressor unit tests |
| Create | `tests/test_compression_llm.py` | LLMCompressor unit tests |
| Create | `tests/test_compression_ast.py` | ASTCodeCompressor unit tests |
| Create | `tests/test_compression_graph.py` | GraphBundleCompressor unit tests |
| Create | `tests/test_ask_orchestrator.py` | ask.py integration test |
| Create | `tests/test_compression_regression.py` | Regression guard across all compressors |

---

## Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add j2toon and py-tree-sitter-languages to pyproject.toml**

Open `pyproject.toml`. In the `[project]` `dependencies` list, add after `"typer>=0.9.0"`:

```toml
    "j2toon>=0.1.0",
    "py-tree-sitter-languages>=1.10.0",
```

- [ ] **Step 2: Install the new dependencies**

```bash
cd /Users/djshelton/Desktop/GitProjects/hippocampy
pip install -e ".[dev]"
```

Expected: installs cleanly. Verify: `python -c "import j2toon; print('j2toon ok')"` and `python -c "from tree_sitter_languages import get_parser; print('tree-sitter ok')"`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add j2toon and py-tree-sitter-languages dependencies for compression"
```

---

## Task 2: Compressor ABC, Registry, ContentRouter, NoOp

**Files:**
- Create: `campy/brain/thalamus/compression/__init__.py`
- Create: `campy/brain/thalamus/compression/fallback.py`

- [ ] **Step 1: Create `compression/__init__.py`**

```python
"""
campy/brain/thalamus/compression/__init__.py

Pluggable compression infrastructure for Campy's thalamic emit path.

WHY GRAPH-NATIVE MATTERS:
Campy bundles are subgraphs, not JSON arrays. GraphBundleCompressor prunes
semantically irrelevant nodes using graph signals (pathway_strength × query
similarity). TOON/ONTO handles flat structured data. LLMCompressor handles
prose. ASTCodeCompressor handles code. ContentRouter dispatches by section_type.
Do NOT replace GraphBundleCompressor with a generic JSON compressor — they
solve different problems (semantic pruning vs syntax elimination).
"""

from __future__ import annotations
import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection


class Compressor(abc.ABC):
    """Abstract base for all compression strategies."""

    @abc.abstractmethod
    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        """
        Compress a bundle section. Always returns a BundleSection (never None).
        The returned section may have the same content (NoOp) or a reduced version.
        """


class PluggableCompressorRegistry:
    """Holds registered compressors and returns them by name."""

    def __init__(self) -> None:
        self._compressors: dict[str, Compressor] = {}

    def register(self, name: str, compressor: Compressor) -> None:
        self._compressors[name] = compressor

    def get(self, name: str) -> Compressor:
        """Return named compressor, or NoOpCompressor if not found."""
        from campy.brain.thalamus.compression.fallback import NoOpCompressor
        return self._compressors.get(name, NoOpCompressor())


class ContentRouter:
    """
    Routes BundleSections to the correct compressor by section_type.

    section_type → compressor name:
      "graph"      → "graph_bundle"   (graph-native pruning — do not substitute)
      "semantic"   → "graph_bundle"   (semantic nodes carry graph signals)
      "tabular"    → "structured_data"
      "exact_fact" → "structured_data"
      "summary"    → "llm_prose"      (only fires when prose is present)
      "code"       → "ast_code"       (Phase B: fires when code extracts present)
    """

    _ROUTE: dict[str, str] = {
        "graph":      "graph_bundle",
        "semantic":   "graph_bundle",
        "tabular":    "structured_data",
        "exact_fact": "structured_data",
        "summary":    "llm_prose",
        "code":       "ast_code",
    }

    def __init__(self, registry: PluggableCompressorRegistry) -> None:
        self._registry = registry

    def compress_section(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        name = self._ROUTE.get(section.section_type, "noop")
        compressor = self._registry.get(name)
        return compressor.compress(section, query, config)


def build_default_registry(config: dict) -> tuple[PluggableCompressorRegistry, ContentRouter]:
    """
    Construct the default registry with all four compressors registered.
    Returns (registry, router).
    """
    from campy.brain.thalamus.compression.fallback import NoOpCompressor
    from campy.brain.thalamus.compression.structured_data import StructuredDataCompressor
    from campy.brain.thalamus.compression.llm_prose import LLMCompressor
    from campy.brain.thalamus.compression.graph_bundle import GraphBundleCompressor

    registry = PluggableCompressorRegistry()
    registry.register("noop", NoOpCompressor())
    registry.register("structured_data", StructuredDataCompressor(config))
    registry.register("llm_prose", LLMCompressor(config))
    registry.register("graph_bundle", GraphBundleCompressor(config))

    ast_enabled = config.get("compression", {}).get("ast_compression", True)
    if ast_enabled:
        try:
            from campy.brain.thalamus.compression.ast_mapper import ASTCodeCompressor
            registry.register("ast_code", ASTCodeCompressor())
        except ImportError:
            registry.register("ast_code", NoOpCompressor())
    else:
        registry.register("ast_code", NoOpCompressor())

    router = ContentRouter(registry)
    return registry, router
```

- [ ] **Step 2: Create `compression/fallback.py`**

```python
"""campy/brain/thalamus/compression/fallback.py — NoOp passthrough compressor."""

from __future__ import annotations
from typing import TYPE_CHECKING
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection


class NoOpCompressor(Compressor):
    """Returns the section unchanged. Used as fallback and opt-out."""

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        return section
```

- [ ] **Step 3: Commit**

```bash
git add campy/brain/thalamus/compression/
git commit -m "feat: add Compressor ABC, PluggableCompressorRegistry, ContentRouter, NoOpCompressor"
```

---

## Task 3: StructuredDataCompressor

**Files:**
- Create: `campy/brain/thalamus/compression/structured_data.py`
- Create: `tests/test_compression_structured.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compression_structured.py
import json
import pytest
from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression.structured_data import StructuredDataCompressor


def _section(content: list[dict]) -> BundleSection:
    return BundleSection(
        section_type="exact_fact",
        content=content,
        token_estimate=len(json.dumps(content)),
        source_node_ids=[],
    )


def test_toon_reduces_tokens():
    content = [
        {"key": "auth_provider", "value": "JWT", "node_type": "GlobalConstraint"},
        {"key": "session_timeout", "value": "3600", "node_type": "GlobalPreference"},
        {"key": "db_host", "value": "localhost", "node_type": "GlobalConstraint"},
    ]
    section = _section(content)
    original_tokens = section.token_estimate

    compressor = StructuredDataCompressor({})
    result = compressor.compress(section, "auth config", {})

    assert result.token_estimate < original_tokens
    assert result.section_type == "exact_fact"
    assert result.content  # not empty


def test_toon_output_contains_field_names_once():
    content = [
        {"key": "x", "value": "1", "node_type": "GlobalConstraint"},
        {"key": "y", "value": "2", "node_type": "GlobalConstraint"},
    ]
    section = _section(content)
    compressor = StructuredDataCompressor({})
    result = compressor.compress(section, "", {})
    # TOON format: field names in header, not repeated per row
    text = result.content[0]["toon"] if result.content else ""
    assert text.count("key") <= 1  # appears in header only, not per row


def test_empty_content_returns_section_unchanged():
    section = _section([])
    compressor = StructuredDataCompressor({})
    result = compressor.compress(section, "", {})
    assert result.content == []
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/test_compression_structured.py -v
```

Expected: `ModuleNotFoundError: No module named 'campy.brain.thalamus.compression.structured_data'`

- [ ] **Step 3: Implement `structured_data.py`**

```python
"""
campy/brain/thalamus/compression/structured_data.py

StructuredDataCompressor — converts flat structured data to TOON format.

Use for: "exact_fact" and "tabular" section types (GlobalConstraints,
GlobalPreferences, Dataset rows). These are flat uniform arrays where
TOON's schema-once, data-many approach gives 30-60% token reduction.

Do NOT use for "semantic" or "graph" sections — those carry graph topology
signals (pathway_strength, node type, relationships) that require
GraphBundleCompressor to prune intelligently before serialization.
"""

from __future__ import annotations
import json
from typing import TYPE_CHECKING
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection


class StructuredDataCompressor(Compressor):
    """Converts list[dict] content to TOON format via j2toon."""

    def __init__(self, config: dict) -> None:
        fmt = config.get("compression", {}).get("structured_format", "toon")
        self._format = fmt

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        from campy.brain.thalamus.bundle_compiler import BundleSection as BS

        if not section.content:
            return section

        try:
            toon_text = self._to_toon(section.content)
            compressed_content = [{"toon": toon_text}]
            token_estimate = len(toon_text) // 4  # ~4 chars per token
            return BS(
                section_type=section.section_type,
                content=compressed_content,
                token_estimate=token_estimate,
                source_node_ids=section.source_node_ids,
            )
        except Exception:
            return section  # fail-safe: return original

    def _to_toon(self, records: list[dict]) -> str:
        if not records:
            return ""
        try:
            from j2toon import json2toon
            return json2toon(records)
        except (ImportError, Exception):
            return self._fallback_toon(records)

    def _fallback_toon(self, records: list[dict]) -> str:
        """Pure-Python TOON fallback if j2toon unavailable."""
        if not records:
            return ""
        keys = list(records[0].keys())
        header = f"{{{','.join(keys)}}}:"
        rows = [",".join(str(r.get(k, "")) for k in keys) for r in records]
        return header + "\n" + "\n".join(rows)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_compression_structured.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add campy/brain/thalamus/compression/structured_data.py tests/test_compression_structured.py
git commit -m "feat: add StructuredDataCompressor with TOON serialization"
```

---

## Task 4: LLMCompressor

**Files:**
- Create: `campy/brain/thalamus/compression/llm_prose.py`
- Create: `tests/test_compression_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compression_llm.py
import pytest
from unittest.mock import MagicMock
from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression.llm_prose import LLMCompressor


def _prose_section(text: str) -> BundleSection:
    return BundleSection(
        section_type="summary",
        content=[{"text": text}],
        token_estimate=len(text) // 4,
        source_node_ids=[],
    )


def _make_compressor(response: str) -> tuple[LLMCompressor, MagicMock]:
    mock_llm = MagicMock()
    mock_llm.chat.return_value = response
    compressor = LLMCompressor({}, llm_override=mock_llm)
    return compressor, mock_llm


def test_prose_section_is_compressed():
    long_prose = "We decided that all authentication calls should use JWT tokens. " * 20
    section = _prose_section(long_prose)
    compressed_text = "JWT tokens for auth."
    compressor, mock_llm = _make_compressor(compressed_text)

    result = compressor.compress(section, "auth decision", {})

    mock_llm.chat.assert_called_once()
    assert result.content[0]["text"] == compressed_text
    assert result.token_estimate < section.token_estimate


def test_empty_section_skips_llm_call():
    section = BundleSection(
        section_type="summary", content=[], token_estimate=0, source_node_ids=[]
    )
    compressor, mock_llm = _make_compressor("")
    result = compressor.compress(section, "", {})
    mock_llm.chat.assert_not_called()
    assert result.content == []


def test_compression_prompt_preserves_entities():
    compressor, mock_llm = _make_compressor("JWT auth decision.")
    section = _prose_section("we use JWT tokens")
    compressor.compress(section, "auth", {})
    call_args = mock_llm.chat.call_args[0][0]  # messages list
    user_content = next(m["content"] for m in call_args if m["role"] == "user")
    assert "entity names" in user_content.lower() or "verbatim" in user_content.lower()
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/test_compression_llm.py -v
```

Expected: `ModuleNotFoundError: No module named 'campy.brain.thalamus.compression.llm_prose'`

- [ ] **Step 3: Implement `llm_prose.py`**

```python
"""
campy/brain/thalamus/compression/llm_prose.py

LLMCompressor — compresses prose sections using Campy's existing LLMClient.

Fires only when the section contains prose (summary, semantic text). Uses
the configured compression_model (defaults to the main LLM to avoid loading
a second model). Set compression_model = "claude-3-5-haiku" or an Ollama
model in [compression] to run compression cheaply.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection

_COMPRESSION_PROMPT = (
    "Compress the following text. Rules:\n"
    "1. Preserve every entity name, decision, file path, number, and negation verbatim.\n"
    "2. Eliminate filler phrases, connective tissue, and redundant transitions.\n"
    "3. Do not alter semantic intent. Do not invent new facts.\n"
    "4. Return only the compressed text, no preamble.\n\n"
    "Text:\n{text}"
)


class LLMCompressor(Compressor):
    """Compresses prose via LLMClient. Skips if content is empty."""

    def __init__(self, config: dict, llm_override=None) -> None:
        self._config = config
        self._llm_override = llm_override  # injected in tests

    def _get_llm(self):
        if self._llm_override is not None:
            return self._llm_override
        from mcp_engine.llm.provider import create_llm_client
        compression_model = self._config.get("compression", {}).get("compression_model", "")
        cfg = dict(self._config)
        if compression_model:
            cfg = dict(cfg)
            cfg.setdefault("llm", {})
            cfg["llm"] = dict(cfg.get("llm", {}))
            cfg["llm"]["model"] = compression_model
        return create_llm_client(cfg)

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        from campy.brain.thalamus.bundle_compiler import BundleSection as BS

        if not section.content:
            return section

        prose = " ".join(
            item.get("text", "") for item in section.content if isinstance(item, dict)
        ).strip()
        if not prose:
            return section

        try:
            llm = self._get_llm()
            if llm is None:
                return section
            messages = [
                {"role": "user", "content": _COMPRESSION_PROMPT.format(text=prose)}
            ]
            compressed = llm.chat(messages)
            token_estimate = len(compressed) // 4
            return BS(
                section_type=section.section_type,
                content=[{"text": compressed}],
                token_estimate=token_estimate,
                source_node_ids=section.source_node_ids,
            )
        except Exception:
            return section  # fail-safe
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_compression_llm.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add campy/brain/thalamus/compression/llm_prose.py tests/test_compression_llm.py
git commit -m "feat: add LLMCompressor for prose sections"
```

---

## Task 5: ASTCodeCompressor

**Files:**
- Create: `campy/brain/thalamus/compression/ast_mapper.py`
- Create: `tests/test_compression_ast.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compression_ast.py
import pytest
from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression.ast_mapper import ASTCodeCompressor

_PYTHON_SOURCE = '''
class UserManager:
    """Manages user authentication."""
    def __init__(self, db):
        self.db = db
        self._cache = {}
        self._session_store = {}

    def authenticate(self, username, password):
        # Expensive validation
        user = self.db.query("SELECT * FROM users WHERE username=?", username)
        if user and verify_hash(password, user.hash):
            return UserSession(user.id)
        return None

    def logout(self, session_id):
        if session_id in self._session_store:
            del self._session_store[session_id]
'''


def _code_section(source: str) -> BundleSection:
    return BundleSection(
        section_type="code",
        content=[{"source": source, "language": "python"}],
        token_estimate=len(source) // 4,
        source_node_ids=[],
    )


def test_ast_folds_function_bodies():
    section = _code_section(_PYTHON_SOURCE)
    compressor = ASTCodeCompressor()
    result = compressor.compress(section, "", {})
    text = result.content[0]["source"]
    assert "def authenticate" in text
    assert "verify_hash" not in text  # body stripped
    assert "def logout" in text
    assert "del self._session_store" not in text  # body stripped


def test_ast_preserves_class_and_signatures():
    section = _code_section(_PYTHON_SOURCE)
    compressor = ASTCodeCompressor()
    result = compressor.compress(section, "", {})
    text = result.content[0]["source"]
    assert "class UserManager" in text
    assert "def authenticate(self, username, password)" in text


def test_ast_reduces_token_count():
    section = _code_section(_PYTHON_SOURCE)
    compressor = ASTCodeCompressor()
    result = compressor.compress(section, "", {})
    assert result.token_estimate < section.token_estimate


def test_empty_section_returns_unchanged():
    section = BundleSection(
        section_type="code", content=[], token_estimate=0, source_node_ids=[]
    )
    compressor = ASTCodeCompressor()
    result = compressor.compress(section, "", {})
    assert result.content == []
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/test_compression_ast.py -v
```

Expected: `ModuleNotFoundError: No module named 'campy.brain.thalamus.compression.ast_mapper'`

- [ ] **Step 3: Implement `ast_mapper.py`**

```python
"""
campy/brain/thalamus/compression/ast_mapper.py

ASTCodeCompressor — folds code to signatures using tree-sitter.

Fires on "code" section_type only (Phase B: when bundle_compiler emits
code extracts from ingested documents). Strips function/method bodies,
retains class hierarchy and method signatures. ~75-90% token reduction.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection


def _fold_python(source: str) -> str:
    """Fold Python source to class/method signatures using tree-sitter."""
    try:
        from tree_sitter_languages import get_parser
    except ImportError:
        return source

    parser = get_parser("python")
    tree = parser.parse(bytes(source, "utf8"))
    lines = []
    _walk(tree.root_node, source, lines, indent=0)
    return "\n".join(lines)


def _walk(node, source: str, out: list[str], indent: int) -> None:
    prefix = "    " * indent
    if node.type == "class_definition":
        name_node = node.child_by_field_name("name")
        name = name_node.text.decode("utf8") if name_node else "?"
        body = node.child_by_field_name("body")
        # Find docstring (first expression_statement with string)
        docstring = ""
        if body:
            for child in body.children:
                if child.type == "expression_statement":
                    for sub in child.children:
                        if sub.type == "string":
                            docstring = sub.text.decode("utf8")
                            break
                    break
        out.append(f"{prefix}class {name}:")
        if docstring:
            out.append(f"{prefix}    {docstring}")
        if body:
            for child in body.children:
                _walk(child, source, out, indent + 1)

    elif node.type == "function_definition":
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        name = name_node.text.decode("utf8") if name_node else "?"
        params = params_node.text.decode("utf8") if params_node else "()"
        out.append(f"{prefix}def {name}{params}:...")

    elif node.type in ("module", "block"):
        for child in node.children:
            _walk(child, source, out, indent)


_LANGUAGE_MAP = {
    "python": _fold_python,
    "py": _fold_python,
}


class ASTCodeCompressor(Compressor):
    """Folds code sections to signatures. Falls back to NoOp if tree-sitter unavailable."""

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        from campy.brain.thalamus.bundle_compiler import BundleSection as BS

        if not section.content:
            return section

        compressed_items = []
        for item in section.content:
            if not isinstance(item, dict):
                compressed_items.append(item)
                continue
            source = item.get("source", "")
            language = item.get("language", "python").lower()
            folder = _LANGUAGE_MAP.get(language)
            if folder and source:
                try:
                    folded = folder(source)
                    compressed_items.append({"source": folded, "language": language})
                except Exception:
                    compressed_items.append(item)
            else:
                compressed_items.append(item)

        total_text = " ".join(
            i.get("source", "") for i in compressed_items if isinstance(i, dict)
        )
        return BS(
            section_type=section.section_type,
            content=compressed_items,
            token_estimate=len(total_text) // 4,
            source_node_ids=section.source_node_ids,
        )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_compression_ast.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add campy/brain/thalamus/compression/ast_mapper.py tests/test_compression_ast.py
git commit -m "feat: add ASTCodeCompressor with tree-sitter signature folding"
```

---

## Task 6: GraphBundleCompressor

**Files:**
- Create: `campy/brain/thalamus/compression/graph_bundle.py`
- Create: `tests/test_compression_graph.py`

**Graph design note:** This is the novel piece. Campy's "semantic" and "graph" bundle sections contain nodes with `pathway_strength` (a KuzuDB-maintained graph property representing memory consolidation) and `confidence`. Phase A scores each node by `cosine_similarity(query_emb, node_emb) × pathway_strength`. Nodes scoring below the bottom `graph_prune_threshold` percentile are dropped. Remaining nodes emit in compact adjacency notation (node type prefix + text). Phase B adds full Personalized PageRank once `_stage_graph_structure` returns relationship data.

Node type prefixes: `C` (Concept), `D` (Decision), `L` (Lesson), `P` (Plan), `PR` (Procedure), `K` (Constraint), `?` (unknown).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compression_graph.py
import math
import pytest
from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression.graph_bundle import GraphBundleCompressor, _cosine_similarity, _node_prefix


def _graph_section(nodes: list[dict]) -> BundleSection:
    return BundleSection(
        section_type="semantic",
        content=nodes,
        token_estimate=sum(len(str(n)) for n in nodes),
        source_node_ids=[n.get("text", "")[:20] for n in nodes],
    )


def _make_nodes(n: int, high_strength: int = 1) -> list[dict]:
    """Create n nodes; first `high_strength` have pathway_strength=0.95, rest 0.05."""
    nodes = []
    for i in range(n):
        nodes.append({
            "text": f"node {i}",
            "type": "Concept" if i % 2 == 0 else "Decision",
            "pathway_strength": 0.95 if i < high_strength else 0.05,
            "confidence": 0.9,
        })
    return nodes


def test_cosine_similarity_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(_cosine_similarity(a, b)) < 1e-6


def test_node_prefix_mapping():
    assert _node_prefix("Concept") == "C"
    assert _node_prefix("Decision") == "D"
    assert _node_prefix("Lesson") == "L"
    assert _node_prefix("Unknown") == "?"


def test_prune_drops_low_strength_nodes():
    nodes = _make_nodes(10, high_strength=3)
    section = _graph_section(nodes)
    compressor = GraphBundleCompressor({"compression": {"graph_prune_threshold": 0.5}})
    result = compressor.compress(section, "test query", {})
    # Compact text should mention high-strength nodes
    text = result.content[0]["compact"] if result.content else ""
    assert "node 0" in text or "node 1" in text or "node 2" in text


def test_empty_section_returns_unchanged():
    section = _graph_section([])
    compressor = GraphBundleCompressor({})
    result = compressor.compress(section, "", {})
    assert result.content == []


def test_compact_notation_contains_type_prefix():
    nodes = [{"text": "use JWT", "type": "Decision", "pathway_strength": 0.9, "confidence": 0.9}]
    section = _graph_section(nodes)
    compressor = GraphBundleCompressor({"compression": {"graph_prune_threshold": 0.0}})
    result = compressor.compress(section, "auth", {})
    text = result.content[0]["compact"] if result.content else ""
    assert "D:" in text


def test_token_estimate_reduced_after_pruning():
    nodes = _make_nodes(20, high_strength=4)
    section = _graph_section(nodes)
    compressor = GraphBundleCompressor({"compression": {"graph_prune_threshold": 0.5}})
    result = compressor.compress(section, "test", {})
    assert result.token_estimate < section.token_estimate
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/test_compression_graph.py -v
```

Expected: `ModuleNotFoundError: No module named 'campy.brain.thalamus.compression.graph_bundle'`

- [ ] **Step 3: Implement `graph_bundle.py`**

```python
"""
campy/brain/thalamus/compression/graph_bundle.py

GraphBundleCompressor — graph-native compression for Campy memory bundles.

WHY THIS IS NOT TOON/ONTO:
Campy's "semantic" and "graph" bundle sections are subgraphs, not JSON arrays.
TOON/ONTO reduces syntactic overhead (curly braces, repeated keys) but keeps
all nodes — including irrelevant ones. GraphBundleCompressor prunes semantically
irrelevant nodes *before* serialization using graph signals:

  score(node) = cosine_similarity(query_emb, node_emb) × pathway_strength

  - cosine_similarity: how close this node is to what the agent asked
  - pathway_strength: Campy's graph-maintained consolidation weight (0–1).
    High pathway_strength = well-established memory. This is a native KuzuDB
    property, not a heuristic — it reflects the Gated Consolidation Loop output.

Nodes scoring below the bottom `graph_prune_threshold` percentile are dropped.
Remaining nodes emit in compact adjacency notation (type prefix + text).

PHASE B: When _stage_graph_structure in bundle_compiler.py returns relationship
data (adjacency), replace the simple score with Personalized PageRank:
  - Build adjacency from relationship data in the "graph" section
  - Use query_emb as the PageRank personalization vector
  - Use power iteration (20 steps, damping 0.85)
The interface of this compressor does not change — only the scoring function.
"""

from __future__ import annotations
import math
from typing import TYPE_CHECKING
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection

_PREFIX_MAP = {
    "Concept":         "C",
    "Decision":        "D",
    "Lesson":          "L",
    "Plan":            "P",
    "Procedure":       "PR",
    "Constraint":      "K",
    "Requirement":     "R",
    "ActionItem":      "A",
    "GlobalConstraint":"GK",
    "GlobalPreference":"GP",
}


def _node_prefix(node_type: str) -> str:
    return _PREFIX_MAP.get(node_type, "?")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _embed_query(query: str, config: dict) -> list[float] | None:
    try:
        from campy.brain.hippocampus.graph import embeddings as emb
        model_name = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        return emb.embed(query, model_name=model_name)
    except Exception:
        return None


def _embed_text(text: str, config: dict) -> list[float] | None:
    try:
        from campy.brain.hippocampus.graph import embeddings as emb
        model_name = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        return emb.embed(text, model_name=model_name)
    except Exception:
        return None


def _score_node(node: dict, query_emb: list[float] | None, config: dict) -> float:
    """
    Phase A scoring: cosine_similarity(query_emb, node_emb) × pathway_strength.
    Falls back to pathway_strength × confidence if embedding unavailable.
    """
    pathway_strength = float(node.get("pathway_strength", 0.5))
    confidence = float(node.get("confidence", 0.5))

    if query_emb is not None:
        text = node.get("text", "")
        node_emb = _embed_text(text, config) if text else None
        if node_emb is not None:
            sim = _cosine_similarity(query_emb, node_emb)
            return max(0.0, sim) * pathway_strength
    # Fallback: pure graph signal
    return pathway_strength * confidence


def _compact_line(node: dict) -> str:
    prefix = _node_prefix(node.get("type", ""))
    text = node.get("text", "").strip()
    return f"{prefix}:{text}"


class GraphBundleCompressor(Compressor):
    """
    Scores, prunes, and serializes graph bundle sections using graph-native signals.
    """

    def __init__(self, config: dict) -> None:
        self._config = config

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        from campy.brain.thalamus.bundle_compiler import BundleSection as BS

        if not section.content:
            return section

        effective_config = config or self._config
        threshold = effective_config.get("compression", {}).get("graph_prune_threshold", 0.30)

        # Score each node
        query_emb = _embed_query(query, effective_config) if query else None
        scored = [
            (node, _score_node(node, query_emb, effective_config))
            for node in section.content
            if isinstance(node, dict)
        ]

        if not scored:
            return section

        # Prune bottom `threshold` fraction by score
        scored.sort(key=lambda x: x[1])
        cutoff_index = max(0, int(len(scored) * threshold))
        surviving = [node for node, _ in scored[cutoff_index:]]

        if not surviving:
            surviving = [scored[-1][0]]  # always keep at least one node

        # Serialize in compact adjacency notation
        lines = [_compact_line(n) for n in surviving]
        compact_text = "\n".join(lines)

        return BS(
            section_type=section.section_type,
            content=[{"compact": compact_text}],
            token_estimate=len(compact_text) // 4,
            source_node_ids=section.source_node_ids,
        )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_compression_graph.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add campy/brain/thalamus/compression/graph_bundle.py tests/test_compression_graph.py
git commit -m "feat: add GraphBundleCompressor with graph-native node scoring and compact notation"
```

---

## Task 7: Config Defaults for [compression]

**Files:**
- Modify: `campy/brain/brainstem/config.py`

- [ ] **Step 1: Add compression defaults to `_DEFAULT_CONFIG`**

In `campy/brain/brainstem/config.py`, find the `_DEFAULT_CONFIG` dict (line ~14) and add the `compression` key after `loop`:

```python
    "compression": {
        "compression_model": "",      # empty = inherit from [llm]
        "graph_prune_threshold": 0.30,
        "structured_format": "toon",
        "ast_compression": True,
    },
```

- [ ] **Step 2: Verify config loads without error**

```bash
python -c "
from campy.brain.brainstem.config import load_config, _DEFAULT_CONFIG
cfg = _DEFAULT_CONFIG
assert cfg['compression']['graph_prune_threshold'] == 0.30
assert cfg['compression']['structured_format'] == 'toon'
print('config defaults ok')
"
```

Expected: `config defaults ok`

- [ ] **Step 3: Commit**

```bash
git add campy/brain/brainstem/config.py
git commit -m "feat: add [compression] defaults to config"
```

---

## Task 8: ask.py Orchestrator

**Files:**
- Create: `campy/brain/thalamus/ask.py`
- Create: `tests/test_ask_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ask_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ask_returns_llm_response():
    from campy.brain.thalamus.ask import run_ask

    mock_db = MagicMock()
    config = {
        "llm": {"provider": "ollama", "model": "llama3.1:8b"},
        "compression": {"graph_prune_threshold": 0.30},
    }

    mock_bundle = MagicMock()
    mock_bundle.sections = []
    mock_bundle.query = "what auth decision did we make?"

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "We decided to use JWT tokens."

    with patch(
        "campy.brain.thalamus.ask.compile_bundle",
        new_callable=AsyncMock,
        return_value=mock_bundle,
    ), patch(
        "campy.brain.thalamus.ask._get_llm",
        return_value=mock_llm,
    ), patch(
        "campy.brain.thalamus.ask._capture_turn",
        new_callable=AsyncMock,
    ) as mock_capture:
        result = await run_ask(
            query="what auth decision did we make?",
            session_id="sess-1",
            db=mock_db,
            config=config,
        )

    assert result == "We decided to use JWT tokens."
    mock_capture.assert_called_once()


@pytest.mark.asyncio
async def test_ask_calls_capture_with_answer():
    from campy.brain.thalamus.ask import run_ask

    mock_db = MagicMock()
    config = {"compression": {}}
    mock_bundle = MagicMock()
    mock_bundle.sections = []
    mock_bundle.query = "test"

    mock_llm = MagicMock()
    mock_llm.chat.return_value = "the answer"

    captured = {}

    async def fake_capture(answer, session_id, db, config):
        captured["answer"] = answer
        captured["session_id"] = session_id

    with patch("campy.brain.thalamus.ask.compile_bundle", new_callable=AsyncMock, return_value=mock_bundle), \
         patch("campy.brain.thalamus.ask._get_llm", return_value=mock_llm), \
         patch("campy.brain.thalamus.ask._capture_turn", side_effect=fake_capture):
        await run_ask("test", "sess-99", mock_db, config)

    assert captured["answer"] == "the answer"
    assert captured["session_id"] == "sess-99"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/test_ask_orchestrator.py -v
```

Expected: `ModuleNotFoundError: No module named 'campy.brain.thalamus.ask'`

- [ ] **Step 3: Implement `ask.py`**

```python
"""
campy/brain/thalamus/ask.py — Augmented Inference Orchestrator

Pipeline: augment → classify → compress → send → capture

This module is the single implementation shared by:
  - campy/cli/ask.py  (Typer CLI: human calls `campy ask "..."`)
  - campy/brain/thalamus/tools/__init__.py  (MCP tool: agent calls `ask`)

Both front doors call run_ask(). Neither duplicates logic.

COMPRESSION IS ALWAYS-ON (Option B):
  - Structured data (exact_fact, tabular): always compressed via TOON
  - Graph/semantic nodes: always scored + pruned via GraphBundleCompressor
  - Prose (summary): compressed via LLMCompressor only when prose is present
  - Code (code): compressed via ASTCodeCompressor only when code is present
"""

from __future__ import annotations
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)


def _get_llm(config: dict):
    """Return LLMClient for main inference. Returns None if unavailable."""
    try:
        from mcp_engine.llm.provider import create_llm_client
        return create_llm_client(config)
    except Exception:
        return None


async def _capture_turn(answer: str, session_id: str, db, config: dict) -> None:
    """Send the ask response through notify_turn for passive ingestion."""
    try:
        from campy.brain.thalamus.tools import notify_turn
        await notify_turn(
            params={"role": "assistant", "content": answer, "session_id": session_id},
            db=db,
            config=config,
        )
    except Exception as exc:
        _logger.warning("ask: capture_turn failed (non-fatal): %s", exc)


def _bundle_to_prompt(bundle, query: str) -> str:
    """Flatten compressed bundle sections into a single prompt string."""
    parts = [f"Query: {query}\n\nContext from memory:\n"]
    for section in bundle.sections:
        section_type = section.section_type
        for item in section.content:
            if not isinstance(item, dict):
                continue
            if "compact" in item:
                parts.append(f"[{section_type}]\n{item['compact']}")
            elif "toon" in item:
                parts.append(f"[{section_type}]\n{item['toon']}")
            elif "text" in item:
                parts.append(f"[{section_type}]\n{item['text']}")
            elif "source" in item:
                parts.append(f"[code]\n{item['source']}")
    return "\n\n".join(parts)


async def run_ask(
    query: str,
    session_id: str,
    db,
    config: dict,
    token_budget: int = 32000,
) -> str:
    """
    Full ask pipeline: augment → compress → send → capture.
    Returns the LLM answer as a string.
    """
    # 1. Augment
    from campy.brain.thalamus.bundle_compiler import compile_bundle
    bundle = await compile_bundle(
        query=query,
        db=db,
        config=config,
        token_budget=token_budget,
    )

    # 2. Compress (always-on, Option B)
    from campy.brain.thalamus.compression import build_default_registry
    _, router = build_default_registry(config)
    compressed_sections = [
        router.compress_section(section, query, config)
        for section in bundle.sections
    ]
    bundle.sections = compressed_sections

    # 3. Build prompt and send
    prompt = _bundle_to_prompt(bundle, query)
    llm = _get_llm(config)
    if llm is None:
        return "[Error: LLM unavailable. Check campy.toml [llm] configuration.]"

    messages = [
        {
            "role": "system",
            "content": (
                "You are Campy, an AI memory assistant. Answer the user's question "
                "using only the provided memory context. If the context does not "
                "contain enough information, say so explicitly."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    answer = llm.chat(messages)

    # 4. Capture
    await _capture_turn(answer, session_id, db, config)

    return answer
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_ask_orchestrator.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add campy/brain/thalamus/ask.py tests/test_ask_orchestrator.py
git commit -m "feat: add ask.py orchestrator — augment, compress, send, capture"
```

---

## Task 9: MCP Tool Schema and Handler

**Files:**
- Modify: `campy/brain/thalamus/tool_schemas.py`
- Modify: `campy/brain/thalamus/tools/__init__.py`

- [ ] **Step 1: Add `ask` schema to `tool_schemas.py`**

Open `campy/brain/thalamus/tool_schemas.py`. In the `TOOLS` list, append after the last entry:

```python
    {
        "name": "ask",
        "description": (
            "Answer a question using project memory. Campy augments the query with "
            "relevant memory, compresses the context bundle, makes an LLM inference "
            "call, and returns a synthesized answer. "
            "Use this when you want a memory-grounded answer, NOT for general chat. "
            "For raw facts use current_truth; for structured context use compile_context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":      {"type": "string", "description": "The question to answer from project memory."},
                "session_id": {"type": "string"},
                "token_budget": {
                    "type": "integer",
                    "default": 32000,
                    "description": "Token budget for the memory bundle before compression.",
                },
            },
            "required": ["query", "session_id"],
        },
    },
```

- [ ] **Step 2: Add `ask` handler to `tools/__init__.py`**

In `campy/brain/thalamus/tools/__init__.py`, add the handler function. Find the block where `compile_context` is defined (around line 2114) and add after it:

```python
async def ask(params: dict, db: "KuzuClient", config: dict) -> dict:
    """MCP tool handler for `ask`. Thin wrapper over run_ask()."""
    from campy.brain.thalamus.ask import run_ask
    query = params.get("query", "")
    session_id = params.get("session_id", "")
    token_budget = params.get("token_budget", 32000)
    if not query:
        return {"error": "query is required"}
    answer = await run_ask(
        query=query,
        session_id=session_id,
        db=db,
        config=config,
        token_budget=token_budget,
    )
    return {"answer": answer}
```

- [ ] **Step 3: Register in `TOOL_HANDLERS`**

In the `TOOL_HANDLERS` dict (around line 3218), add after `"compile_context"`:

```python
    "ask":              _with_phase("recalling", ask),
```

- [ ] **Step 4: Verify tool schema and handler are consistent**

```bash
python -c "
from campy.brain.thalamus.tool_schemas import TOOLS
from campy.brain.thalamus.tools import TOOL_HANDLERS
schema_names = {t['name'] for t in TOOLS}
handler_names = set(TOOL_HANDLERS.keys())
assert 'ask' in schema_names, 'ask missing from TOOLS'
assert 'ask' in handler_names, 'ask missing from TOOL_HANDLERS'
print('ask tool registered correctly')
"
```

Expected: `ask tool registered correctly`

- [ ] **Step 5: Run existing tool surface tests**

```bash
pytest tests/test_analogical.py::test_codex_adapter_has_all_tools -v
```

Expected: PASS (test is registry-derived, added in B288).

- [ ] **Step 6: Commit**

```bash
git add campy/brain/thalamus/tool_schemas.py campy/brain/thalamus/tools/__init__.py
git commit -m "feat: add ask MCP tool schema and handler"
```

---

## Task 10: CLI Front Door

**Files:**
- Create: `campy/cli/ask.py`
- Modify: `campy/cli/main.py`

- [ ] **Step 1: Create `campy/cli/ask.py`**

```python
"""
campy/cli/ask.py — CLI front door for `campy ask`.

Human-facing command: the user runs `campy ask "what did we decide about auth?"`
and gets a memory-grounded answer in plain text.

This is the non-coder "chat with your project's brain" entry point.
The implementation delegates entirely to run_ask() — no logic lives here.
"""

import asyncio
import typer
from typing import Optional
from rich.console import Console

app = typer.Typer(help="Ask Campy a question grounded in project memory.")
console = Console()


@app.command()
def ask(
    query: str = typer.Argument(..., help="Question to answer from project memory."),
    session_id: Optional[str] = typer.Option(
        None, "--session", "-s", help="Session ID for memory capture. Defaults to 'cli'."
    ),
    token_budget: int = typer.Option(
        32000, "--budget", "-b", help="Token budget for memory bundle before compression."
    ),
    ctx: typer.Context = typer.Option(None, hidden=True),
):
    """Ask Campy a question and get a memory-grounded answer."""
    config = {}
    if ctx and ctx.obj:
        config = ctx.obj.get("config", {})

    sid = session_id or "cli"

    try:
        from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
        from campy.brain.brainstem.config import load_config
        from campy.brain.thalamus.ask import run_ask

        if not config:
            config = load_config()

        db_path = config.get("database", {}).get("path", "~/.campy/brain.db")
        import os
        db_path = os.path.expanduser(db_path)
        db = KuzuClient(db_path, read_only=True)

        answer = asyncio.run(
            run_ask(query=query, session_id=sid, db=db, config=config, token_budget=token_budget)
        )
        console.print(answer)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
```

- [ ] **Step 2: Register in `campy/cli/main.py`**

In `campy/cli/main.py`, find the existing sub-app imports (around lines 26–31). Add:

```python
from campy.cli.ask import app as ask_app
```

Then find where other sub-apps are mounted with `app.add_typer(...)` and add:

```python
app.add_typer(ask_app, name="ask")
```

- [ ] **Step 3: Verify CLI command is registered**

```bash
python -m campy.cli.main ask --help
```

Expected: shows `ask` command help text with `QUERY` argument and `--session`, `--budget` options.

- [ ] **Step 4: Commit**

```bash
git add campy/cli/ask.py campy/cli/main.py
git commit -m "feat: add campy ask CLI command"
```

---

## Task 11: Regression Guard

**Files:**
- Create: `tests/test_compression_regression.py`

- [ ] **Step 1: Write the regression guard**

```python
# tests/test_compression_regression.py
"""
Regression guard: runs all four compressors on canonical fixtures and
asserts compression ratios do not regress by more than 5%.

If this test fails after a code change, the compression pipeline has
regressed. Check which compressor is affected and restore or improve it.
"""

import json
import math
import pytest
from campy.brain.thalamus.bundle_compiler import BundleSection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STRUCTURED_CONTENT = [
    {"key": f"setting_{i}", "value": f"value_{i}", "node_type": "GlobalConstraint"}
    for i in range(20)
]

_GRAPH_CONTENT = [
    {
        "text": f"concept about {'auth' if i < 5 else 'unrelated topic'} {i}",
        "type": "Concept" if i % 2 == 0 else "Decision",
        "pathway_strength": 0.9 if i < 5 else 0.05,
        "confidence": 0.85,
    }
    for i in range(20)
]

_PYTHON_SOURCE = '''
class AuthManager:
    def __init__(self, db, cache):
        self.db = db
        self.cache = cache
        self._sessions = {}

    def authenticate(self, username, password):
        if username in self.cache:
            return self.cache[username]
        user = self.db.find(username)
        if user and verify(password, user.hash):
            token = generate_token(user.id)
            self.cache[username] = token
            return token
        return None

    def logout(self, token):
        for key, val in list(self._sessions.items()):
            if val == token:
                del self._sessions[key]
'''


def _make_section(section_type: str, content: list) -> BundleSection:
    return BundleSection(
        section_type=section_type,
        content=content,
        token_estimate=max(1, len(json.dumps(content)) // 4),
        source_node_ids=[],
    )


# ---------------------------------------------------------------------------
# Minimum compression ratios (token_estimate_after / token_estimate_before)
# A ratio < 1.0 means compression reduced token count.
# The guard fails if the ratio exceeds the threshold (i.e., not enough compression).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("compressor_name,section_type,content,max_ratio", [
    (
        "structured_data",
        "exact_fact",
        _STRUCTURED_CONTENT,
        0.75,  # must reduce by at least 25%
    ),
    (
        "graph_bundle",
        "semantic",
        _GRAPH_CONTENT,
        0.70,  # must reduce by at least 30% (pruning + compact notation)
    ),
    (
        "ast_code",
        "code",
        [{"source": _PYTHON_SOURCE, "language": "python"}],
        0.40,  # must reduce by at least 60%
    ),
])
def test_compression_ratio_not_regressed(compressor_name, section_type, content, max_ratio):
    from campy.brain.thalamus.compression import build_default_registry

    config = {
        "compression": {
            "graph_prune_threshold": 0.50,
            "structured_format": "toon",
            "ast_compression": True,
        }
    }
    registry, _ = build_default_registry(config)
    compressor = registry.get(compressor_name)

    section = _make_section(section_type, content)
    result = compressor.compress(section, "auth", config)

    ratio = result.token_estimate / section.token_estimate
    assert ratio <= max_ratio, (
        f"{compressor_name} compression ratio {ratio:.2f} exceeds max {max_ratio:.2f}. "
        f"Before: {section.token_estimate} tokens, After: {result.token_estimate} tokens."
    )
```

- [ ] **Step 2: Run the regression guard**

```bash
pytest tests/test_compression_regression.py -v
```

Expected: all 3 parametrized cases PASS.

- [ ] **Step 3: Run the full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: no new failures introduced.

- [ ] **Step 4: Update tool-catalog.md**

Open `docs/tool-catalog.md`. In the Quick Reference table, add row 52:

```
| 52 | `ask` | Augmented Inference | Agent / Human CLI | Yes (LLM call) | Yes |
```

- [ ] **Step 5: Final commit**

```bash
git add tests/test_compression_regression.py docs/tool-catalog.md
git commit -m "feat: add compression regression guard and update tool catalog"
```

---

## Implementation Checklist

After all tasks complete, verify:

- [ ] `campy ask "test question"` runs from CLI and returns an answer
- [ ] `ask` appears in `campy/brain/thalamus/tool_schemas.py TOOLS` list
- [ ] `ask` appears in `TOOL_HANDLERS` in `tools/__init__.py`
- [ ] `pytest tests/test_compression_*.py tests/test_ask_orchestrator.py -v` — all pass
- [ ] `pytest tests/test_compression_regression.py -v` — all pass
- [ ] `pytest tests/test_analogical.py::test_codex_adapter_has_all_tools -v` — still passes
- [ ] GraphBundleCompressor is NOT replaced with StructuredDataCompressor anywhere

## Phase B Notes (do not implement now)

Phase B extends the same `compression/` module to wrap all other MCP tool responses:
- Wire `current_truth`, `compile_context`, `recall_relevant_lessons`, etc. through `ContentRouter`
- Implement `_stage_graph_structure` in `bundle_compiler.py` to return adjacency data
- Upgrade `GraphBundleCompressor` scoring to full Personalized PageRank using adjacency
