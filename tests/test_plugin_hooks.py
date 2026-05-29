import importlib.util
from pathlib import Path


HOOK_MODULE = Path(__file__).parent.parent / "plugin" / "hooks" / "campy_hook.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("campy_hook", HOOK_MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_load_manifest_reads_trigger_dict(tmp_path, monkeypatch):
    module = _load_module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"triggers": [{"hook_type": "PreToolUse", "pattern": "deploy"}]}')
    monkeypatch.setenv("CAMPY_TRIGGER_MANIFEST", str(manifest))

    loaded = module.load_manifest()

    assert loaded == [{"hook_type": "PreToolUse", "pattern": "deploy"}]


def test_match_triggers_filters_by_hook_tool_and_scope(monkeypatch):
    module = _load_module()
    manifest = [
        {"hook_type": "PreToolUse", "tool": "Bash", "project_scope": "/repo", "pattern": "deploy", "name": "deploy-safety"},
        {"hook_type": "PostToolUse", "tool": "Bash", "project_scope": "/repo", "pattern": "error", "name": "error-help"},
    ]

    matches = module.match_triggers(manifest, "PreToolUse", tool_name="Bash", content="deploy prod", cwd="/repo/app")

    assert [match["name"] for match in matches] == ["deploy-safety"]


def test_format_context_snippets_uses_context_snippet_and_node_type():
    module = _load_module()
    text = module.format_context_snippets([
        {"name": "deploy-safety", "node_type": "Lesson", "context_snippet": "Run smoke tests first."}
    ])

    assert "Lesson: deploy-safety" in text
    assert "Run smoke tests first." in text