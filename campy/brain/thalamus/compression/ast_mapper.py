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


def _get_python_parser():
    """
    Build a tree-sitter Parser for Python.

    tree-sitter-languages 1.10.2 ships a pre-compiled languages.so that was
    built against tree-sitter ~0.21, but tree-sitter 0.25 changed Language()
    to accept only an integer pointer. get_parser() / get_language() in
    tree_sitter_languages therefore fail with TypeError. We work around this by
    loading the shared library directly via ctypes, obtaining the raw C pointer
    to tree_sitter_python, and constructing a Language from that integer.
    """
    import ctypes
    import warnings
    import importlib.util
    import os

    # Locate the compiled languages bundle bundled with tree_sitter_languages.
    spec = importlib.util.find_spec("tree_sitter_languages")
    if spec is None:
        return None
    pkg_dir = os.path.dirname(spec.origin)
    so_path = os.path.join(pkg_dir, "languages.so")
    if not os.path.exists(so_path):
        return None

    try:
        import tree_sitter
        lib = ctypes.cdll.LoadLibrary(so_path)
        fn = lib.tree_sitter_python
        fn.restype = ctypes.c_void_p
        ptr = fn()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            lang = tree_sitter.Language(ptr)
        return tree_sitter.Parser(lang)
    except Exception:
        return None


def _fold_python(source: str) -> str:
    """Fold Python source to class/method signatures using tree-sitter."""
    parser = _get_python_parser()
    if parser is None:
        return source

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
        # Normalize any internal whitespace/newlines in params
        params = " ".join(params.split())
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
