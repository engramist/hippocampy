from __future__ import annotations

import os
import shutil
import tempfile
import uuid
import logging
import hashlib
import re
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from campy.brain.hippocampus.graph.gateway import get_gateway


logger = logging.getLogger(__name__)

@dataclass
class WikiPage:
    title: str
    persona: str
    source_node_ids: list[str] = field(default_factory=list)
    source_edge_ids: list[str] = field(default_factory=list)
    body_sections: list[tuple[str, str]] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)
    related_pages: list[str] = field(default_factory=list)
    slug: str = ""

    def __post_init__(self):
        if not self.slug:
            self.slug = self.title.replace(" ", "-").lower()
            # Basic slugification, could be more robust
            self.slug = "".join(c for c in self.slug if c.isalnum() or c == "-")

async def export_wiki_projection(db, config: dict) -> dict:
    """
    Main entry point for generating the wiki projection.
    Called from sweep.py.
    """
    wiki_cfg = config.get("wiki_projection", {})
    if not wiki_cfg.get("enabled", False):
        return {"status": "disabled"}

    # Load personas from config
    personas = _load_personas(config)
    vault_dir = Path(wiki_cfg.get("vault_dir", "wiki")).resolve()

    summary = {
        "status": "success",
        "personas_processed": 0,
        "pages_written": 0,
        "errors": 0,
        "vault_path": str(vault_dir),
        "generated_at": datetime.now().isoformat() + "Z",
        "drift_detected": 0
    }

    try:
        for persona_cfg in personas:
            p_summary = await _export_single_persona(db, persona_cfg, summary["generated_at"], vault_dir)
            summary["pages_written"] += p_summary["pages_written"]
            summary["personas_processed"] += 1
            summary["drift_detected"] += p_summary.get("drift_detected", 0)
            if p_summary["status"] == "error":
                summary["errors"] += 1

        # Write global Home.md at the vault root
        global_home = f"# SideQuests Brain Wiki\n\nGenerated at: {summary['generated_at']}\n\n## Personas\n"
        for p in personas:
            # Relative link from vault root to persona home
            rel_path = os.path.relpath(p["output_dir"], vault_dir)
            global_home += f"- [[{rel_path}/Home|{p['name'].capitalize()} Persona]]\n"
        
        # Add links to manual notes and conflicts if they exist
        global_home += "\n## Human Knowledge\n"
        global_home += "- [[manual-notes/Home|Manual Notes]]\n"
        
        _write_atomic(vault_dir / "Home.md", global_home)
        
        # Ensure manual-notes directory exists with a placeholder Home.md
        manual_notes_dir = vault_dir / "manual-notes"
        manual_notes_dir.mkdir(parents=True, exist_ok=True)
        if not (manual_notes_dir / "Home.md").exists():
            _write_atomic(manual_notes_dir / "Home.md", "# Manual Notes\n\nPlace your human-authored Markdown notes here. SideQuests will not overwrite them.\n")

    except Exception as e:
        logger.exception("Wiki projection failed")
        summary["status"] = "error"
        summary["error_detail"] = str(e)
        summary["errors"] += 1

    return summary

def _load_personas(config: dict) -> list[dict]:
    wiki_cfg = config.get("wiki_projection", {})
    personas = wiki_cfg.get("personas", [])
    
    if not personas:
        # Default implicit persona
        personas = [{
            "name": "default",
            "output_dir": wiki_cfg.get("output_dir", "wiki/personas/default"),
            "max_pages_per_sweep": wiki_cfg.get("max_pages_per_sweep", 50),
            "include_domains": None,
            "include_node_types": None,
            "home_title": "Default Memory"
        }]
    
    # Ensure output_dir is absolute
    vault_dir = Path(wiki_cfg.get("vault_dir", "wiki")).resolve()
    processed = []
    for p in personas:
        p_out = p.get("output_dir")
        if p_out:
            p["output_dir"] = Path(p_out).resolve()
        else:
            p["output_dir"] = vault_dir / "personas" / p["name"]
        
        if not p.get("name"):
            p["name"] = "unknown"
        processed.append(p)
            
    return processed

async def _export_single_persona(db, persona_cfg: dict, timestamp: str, vault_dir: Path) -> dict:
    output_dir = persona_cfg["output_dir"]
    max_pages = persona_cfg.get("max_pages_per_sweep", 50)
    
    os.makedirs(output_dir / "pages", exist_ok=True)

    summary = {"status": "success", "pages_written": 0, "drift_detected": 0}

    try:
        pages = await _select_pages_for_persona(db, persona_cfg, max_pages)
        
        # Write individual pages
        for page in pages:
            content = _render_page(page, timestamp)
            page_path = output_dir / "pages" / f"{page.slug}.md"
            drifted = _write_atomic(page_path, content)
            if drifted:
                summary["drift_detected"] += 1
            summary["pages_written"] += 1

        # Write index and home pages
        home_content = _render_home_page(pages, {"generated_at": timestamp}, persona_cfg)
        _write_atomic(output_dir / "Home.md", home_content)
        
        index_pages = _render_index_pages(pages)
        for name, content in index_pages.items():
            _write_atomic(output_dir / f"{name}.md", content)

    except Exception as e:
        logger.error(f"Persona {persona_cfg['name']} projection failed: {e}")
        summary["status"] = "error"

    return summary

def _row_val(row: Any, idx: int, *keys: str) -> Any:
    if isinstance(row, dict):
        for k in keys:
            if k in row:
                return row[k]
        return None
    if isinstance(row, (list, tuple)) and idx < len(row):
        return row[idx]
    for k in keys:
        if hasattr(row, k):
            return getattr(row, k)
    return None

async def _select_pages_for_persona(db, persona_cfg: dict, limit: int) -> list[WikiPage]:
    """Select nodes from KuzuDB for a specific persona."""
    gw = get_gateway(db)
    pages = []
    include_domains = persona_cfg.get("include_domains")
    include_node_types = persona_cfg.get("include_node_types")
    persona_name = persona_cfg["name"]

    def _rows(result):
        if result is None:
            return
        if isinstance(result, list):
            yield from result
            return
        if result.__class__.__module__.startswith("kuzu") and hasattr(result, "has_next") and hasattr(result, "get_next"):
            while result.has_next():
                yield result.get_next()
            return
        yield from result

    # 1. Lessons
    if not include_node_types or "Lesson" in include_node_types:
        try:
            if include_domains:
                res = await gw.run("thalamus.wiki_lessons_by_domain", domains=include_domains, lim=limit)
            else:
                res = await gw.run("thalamus.wiki_lessons", lim=limit)
            for row in _rows(res):
                lid = _row_val(row, 0, "l.lesson_id", "lesson_id")
                text = _row_val(row, 1, "l.text_raw", "text_raw") or ""
                domain = _row_val(row, 2, "l.domain", "domain")
                pages.append(WikiPage(
                    title=f"Lesson: {text[:40]}...",
                    persona=persona_name,
                    source_node_ids=[lid],
                    body_sections=[("Summary", text), ("Domain", domain or "unknown")]
                ))
        except Exception:
            logger.debug(f"Failed to query lessons for persona {persona_name}")

    # 2. Procedures
    if (not include_node_types or "Procedure" in include_node_types) and len(pages) < limit:
        try:
            lim = limit - len(pages)
            if include_domains:
                res = await gw.run("thalamus.wiki_procedures_by_domain", domains=include_domains, lim=lim)
            else:
                res = await gw.run("thalamus.wiki_procedures", lim=lim)
            for row in _rows(res):
                pid = _row_val(row, 0, "p.procedure_id", "procedure_id")
                name = _row_val(row, 1, "p.name", "name")
                desc = _row_val(row, 2, "p.description", "description")
                arch = _row_val(row, 3, "p.archetype", "archetype")
                pages.append(WikiPage(
                    title=f"Procedure: {name}",
                    persona=persona_name,
                    source_node_ids=[pid],
                    body_sections=[("Description", desc), ("Archetype", arch or "generic")]
                ))
        except Exception:
            logger.debug(f"Failed to query procedures for persona {persona_name}")

    # 3. ARC Runs (B225)
    if (not include_node_types or "ArcRun" in include_node_types) and len(pages) < limit:
        try:
            lim = limit - len(pages)
            res = await gw.run("thalamus.wiki_arc_runs", lim=lim)
            for row in _rows(res):
                run_id = _row_val(row, 0, "r.run_id", "run_id")
                summary_val = _row_val(row, 1, "r.summary", "summary")
                domain = _row_val(row, 2, "r.domain", "domain")
                status = _row_val(row, 3, "r.status", "status")
                task_count = _row_val(row, 4, "r.task_count", "task_count")
                solved_count = _row_val(row, 5, "r.solved_count", "solved_count")
                failed_count = _row_val(row, 6, "r.failed_count", "failed_count")
                step_count = _row_val(row, 7, "r.step_count", "step_count")
                source_files = _row_val(row, 8, "r.source_files", "source_files")

                wm_section = ""
                try:
                    wm_res = await gw.run("thalamus.wiki_arc_run_wm_summary", run_id=run_id)
                    wm_rows = list(_rows(wm_res))
                    if wm_rows:
                        wm_row = wm_rows[0]
                        s_bounded = _row_val(wm_row, 0, "s.graph_bounded", "graph_bounded")
                        s_compiler = _row_val(wm_row, 1, "s.compiler_active", "compiler_active")
                        s_falsification = _row_val(wm_row, 2, "s.falsification_active", "falsification_active")
                        s_reasoning = _row_val(wm_row, 3, "s.reasoning_gated", "reasoning_gated")
                        s_planner = _row_val(wm_row, 4, "s.planner_grounded", "planner_grounded")
                        s_transfer = _row_val(wm_row, 5, "s.memory_transfer_active", "memory_transfer_active")
                        s_stall = _row_val(wm_row, 6, "s.single_action_stall_detected", "single_action_stall_detected")
                        s_cycles = _row_val(wm_row, 7, "s.full_reasoning_cycles_avoided", "full_reasoning_cycles_avoided")
                        wm_section = (
                            f"bounded={bool(s_bounded)}, compiler={bool(s_compiler)}, "
                            f"falsification={bool(s_falsification)}, reasoning_gated={bool(s_reasoning)}, "
                            f"planner={bool(s_planner)}, memory_transfer={bool(s_transfer)}\n\n"
                            f"stall_detected={bool(s_stall)}, cycles_avoided={s_cycles or 0}"
                        )
                except Exception:
                    pass

                pages.append(WikiPage(
                    title=f"ARC Run: {run_id}",
                    persona=persona_name,
                    source_node_ids=[run_id],
                    body_sections=[
                        ("Summary", summary_val or ""),
                        ("Status", status or "unknown"),
                        ("Run Metrics", f"tasks={task_count or 0}, solved={solved_count or 0}, failed={failed_count or 0}, steps={step_count or 0}"),
                        ("World Model Health", wm_section or "No world-model evaluation data found for this run."),
                        ("Domain", domain or ""),
                        ("Provenance", f"Graph source: {run_id}\n\nArtifact paths: {source_files or '[]'}"),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcRun for persona {persona_name}")

    # 4. ARC Task Results (B225)
    if (not include_node_types or "ArcTaskResult" in include_node_types) and len(pages) < limit:
        try:
            lim = limit - len(pages)
            res = await gw.run("thalamus.wiki_arc_task_results", lim=lim)
            for row in _rows(res):
                task_res_id = _row_val(row, 0, "t.task_result_id", "task_result_id")
                summary_val = _row_val(row, 1, "t.summary", "summary")
                domain = _row_val(row, 2, "t.domain", "domain")
                status = _row_val(row, 3, "t.status", "status")
                task_id = _row_val(row, 4, "t.task_id", "task_id")
                puzzle_id = _row_val(row, 5, "t.puzzle_id", "puzzle_id")
                correct = _row_val(row, 6, "t.correct", "correct")
                steps = _row_val(row, 7, "t.steps", "steps")
                failure_class = _row_val(row, 8, "t.failure_class", "failure_class")
                pages.append(WikiPage(
                    title=f"ARC Task: {task_id or puzzle_id or task_res_id}",
                    persona=persona_name,
                    source_node_ids=[task_res_id],
                    body_sections=[
                        ("Summary", summary_val or ""),
                        ("Status", status or "unknown"),
                        ("Task Metrics", f"task_id={task_id or ''}, puzzle_id={puzzle_id or ''}, correct={bool(correct)}, steps={steps or 0}"),
                        ("Failure Class", failure_class or ""),
                        ("Domain", domain or ""),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcTaskResult for persona {persona_name}")

    # 5. ARC Artifacts (B225)
    if (not include_node_types or "ArcArtifact" in include_node_types) and len(pages) < limit:
        try:
            lim = limit - len(pages)
            res = await gw.run("thalamus.wiki_arc_artifacts", lim=lim)
            for row in _rows(res):
                aid = _row_val(row, 0, "a.artifact_id", "artifact_id")
                kind = _row_val(row, 1, "a.artifact_kind", "artifact_kind")
                path = _row_val(row, 2, "a.path", "path")
                chash = _row_val(row, 3, "a.content_hash", "content_hash")
                rcount = _row_val(row, 4, "a.record_count", "record_count")
                captured_at = _row_val(row, 5, "a.captured_at", "captured_at")
                ingested_at = _row_val(row, 6, "a.ingested_at", "ingested_at")
                domain = _row_val(row, 7, "a.domain", "domain")
                summary_val = _row_val(row, 8, "a.summary", "summary")
                pages.append(WikiPage(
                    title=f"ARC Artifact: {kind or aid}",
                    persona=persona_name,
                    source_node_ids=[aid],
                    body_sections=[
                        ("Summary", summary_val or ""),
                        ("Artifact", f"kind={kind or ''}, records={rcount or 0}"),
                        ("Path", path or ""),
                        ("Content Hash", chash or ""),
                        ("Captured", str(captured_at or "")),
                        ("Ingested", str(ingested_at or "")),
                        ("Domain", domain or ""),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcArtifact for persona {persona_name}")

    # 6. ARC Events (B225)
    if (not include_node_types or "ArcEvent" in include_node_types) and len(pages) < limit:
        try:
            lim = limit - len(pages)
            res = await gw.run("thalamus.wiki_arc_events", lim=lim)
            for row in _rows(res):
                eid = _row_val(row, 0, "e.event_id", "event_id")
                run_id = _row_val(row, 1, "e.run_id", "run_id")
                task_id = _row_val(row, 2, "e.task_id", "task_id")
                etype = _row_val(row, 3, "e.event_type", "event_type")
                timestamp_val = _row_val(row, 4, "e.timestamp", "timestamp")
                step_idx = _row_val(row, 5, "e.step_index", "step_index")
                actor = _row_val(row, 6, "e.actor", "actor")
                tool_name = _row_val(row, 7, "e.tool_name", "tool_name")
                action_name = _row_val(row, 8, "e.action_name", "action_name")
                outcome = _row_val(row, 9, "e.outcome", "outcome")
                domain = _row_val(row, 10, "e.domain", "domain")
                summary_val = _row_val(row, 11, "e.summary", "summary")
                step = step_idx if step_idx is not None else "unknown"
                label = etype or action_name or tool_name or eid
                pages.append(WikiPage(
                    title=f"ARC Event: step {step} {label}",
                    persona=persona_name,
                    source_node_ids=[eid],
                    body_sections=[
                        ("Summary", summary_val or ""),
                        ("Event", f"type={etype or ''}, step={step}, timestamp={timestamp_val or ''}"),
                        ("Run", run_id or ""),
                        ("Task", task_id or ""),
                        ("Actor And Tool", f"actor={actor or ''}, tool={tool_name or ''}, action={action_name or ''}"),
                        ("Outcome", outcome or ""),
                        ("Domain", domain or ""),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcEvent for persona {persona_name}")

    # 7. ARC World Model Steps (B229)
    if (not include_node_types or "ArcWorldModelStep" in include_node_types) and len(pages) < limit:
        try:
            lim = limit - len(pages)
            res = await gw.run("thalamus.wiki_arc_wm_steps", lim=lim)
            for row in _rows(res):
                step_id = _row_val(row, 0, "s.world_model_step_id", "world_model_step_id")
                task_id = _row_val(row, 1, "s.task_id", "task_id")
                step_idx = _row_val(row, 2, "s.step_index", "step_index")
                ncount = _row_val(row, 3, "s.node_count", "node_count")
                ecount = _row_val(row, 4, "s.edge_count", "edge_count")
                ccount = _row_val(row, 5, "s.compiled_claim_count", "compiled_claim_count")
                effect_class = _row_val(row, 6, "s.action_effect_class", "action_effect_class")
                rmode = _row_val(row, 7, "s.reasoning_mode", "reasoning_mode")
                pcand = _row_val(row, 8, "s.planner_candidate_count", "planner_candidate_count")
                stall = _row_val(row, 9, "s.single_action_stall_detected", "single_action_stall_detected")
                summary_val = _row_val(row, 10, "s.summary", "summary")
                pages.append(WikiPage(
                    title=f"ARC WM Step: task {task_id} step {step_idx}",
                    persona=persona_name,
                    source_node_ids=[step_id],
                    body_sections=[
                        ("Summary", summary_val or ""),
                        ("Graph Metrics", f"nodes={ncount or 0}, edges={ecount or 0}, claims={ccount or 0}"),
                        ("Execution", f"action_effect={effect_class or ''}, reasoning={rmode or ''}, candidates={pcand or 0}, stall_detected={bool(stall)}"),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcWorldModelStep for persona {persona_name}")

    # 8. ARC World Model Summaries (B229)
    if (not include_node_types or "ArcWorldModelSummary" in include_node_types) and len(pages) < limit:
        try:
            lim = limit - len(pages)
            res = await gw.run("thalamus.wiki_arc_wm_summaries", lim=lim)
            for row in _rows(res):
                wm_id = _row_val(row, 0, "s.world_model_summary_id", "world_model_summary_id")
                task_id = _row_val(row, 1, "s.task_id", "task_id")
                s_bounded = _row_val(row, 2, "s.graph_bounded", "graph_bounded")
                s_compiler = _row_val(row, 3, "s.compiler_active", "compiler_active")
                s_falsification = _row_val(row, 4, "s.falsification_active", "falsification_active")
                s_reasoning = _row_val(row, 5, "s.reasoning_gated", "reasoning_gated")
                s_planner = _row_val(row, 6, "s.planner_grounded", "planner_grounded")
                s_transfer = _row_val(row, 7, "s.memory_transfer_active", "memory_transfer_active")
                s_stall = _row_val(row, 8, "s.single_action_stall_detected", "single_action_stall_detected")
                s_cycles = _row_val(row, 9, "s.full_reasoning_cycles_avoided", "full_reasoning_cycles_avoided")
                summary_val = _row_val(row, 10, "s.summary", "summary")
                pages.append(WikiPage(
                    title=f"ARC WM Summary: task {task_id}",
                    persona=persona_name,
                    source_node_ids=[wm_id],
                    body_sections=[
                        ("Summary", summary_val or ""),
                        ("Flags", f"bounded={bool(s_bounded)}, compiler={bool(s_compiler)}, falsification={bool(s_falsification)}, reasoning_gated={bool(s_reasoning)}, planner_grounded={bool(s_planner)}, memory_transfer={bool(s_transfer)}"),
                        ("Stalls and Savings", f"stall_detected={bool(s_stall)}, reasoning_cycles_avoided={s_cycles or 0}"),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcWorldModelSummary for persona {persona_name}")

    # 9. ARC Mechanics (B226)
    if (not include_node_types or "ArcMechanic" in include_node_types) and len(pages) < limit:
        try:
            lim = limit - len(pages)
            res = await gw.run("thalamus.wiki_arc_mechanics", lim=lim)
            for row in _rows(res):
                mid = _row_val(row, 0, "m.mechanic_id", "mechanic_id")
                name = _row_val(row, 1, "m.name", "name")
                sig = _row_val(row, 2, "m.signature", "signature")
                conf = _row_val(row, 3, "m.confidence", "confidence")
                trev = _row_val(row, 4, "m.terminal_relevance", "terminal_relevance")
                crev = _row_val(row, 5, "m.coordinate_relevance", "coordinate_relevance")
                ecount = _row_val(row, 6, "m.evidence_count", "evidence_count")
                summary_val = _row_val(row, 7, "m.summary", "summary")
                pages.append(WikiPage(
                    title=f"ARC Mechanic: {name or mid}",
                    persona=persona_name,
                    source_node_ids=[mid],
                    body_sections=[
                        ("Summary", summary_val or ""),
                        ("Signature", sig or "unknown"),
                        ("Stats", f"confidence={conf or 0.0}, evidence_count={ecount or 0}"),
                        ("Relevance", f"terminal={trev or 0.0}, coordinate={crev or 0.0}"),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcMechanic for persona {persona_name}")

    return pages


def _compute_hash(content: str) -> str:
    """Compute a stable hash of the page body content."""
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

def _render_page(page: WikiPage, timestamp: str) -> str:
    """Render a single WikiPage into Markdown string."""
    body_lines = []
    for section_title, content in page.body_sections:
        body_lines.append(f"## {section_title}\n")
        body_lines.append(f"{content}\n")
    
    if page.related_pages:
        body_lines.append("## Related Pages\n")
        for related in page.related_pages:
            body_lines.append(f"- [[{related}]]")
        body_lines.append("")

    # Body used for hashing excludes frontmatter and read-only notice
    body_content_for_hash = "\n".join(body_lines)
    content_hash = _compute_hash(body_content_for_hash)

    lines = [
        "---",
        "sidequests_projection: true",
        "projection_version: 1",
        f"persona: {page.persona}",
        f"generated_at: \"{timestamp}\"",
        f"projection_hash: \"{content_hash}\"",
        f"source_node_ids: {page.source_node_ids}",
        "manual_edits_supported: false",
        "---",
        "\n> [!INFO] Read-only Projection\n> This page is generated from SideQuests graph memory. Manual edits will be overwritten. Use `manual-notes/` for human-authored content.\n",
        f"\n# {page.title}\n",
        body_content_for_hash,
        "\n---\n",
        f"*Source IDs: {', '.join(page.source_node_ids)}*"
    ]
    
    return "\n".join(lines)

def _render_home_page(pages: list[WikiPage], summary: dict, persona_cfg: dict) -> str:
    title = persona_cfg.get("home_title", f"{persona_cfg['name'].capitalize()} Memory")
    lines = [
        f"# {title} ({summary['generated_at']})\n",
        "Welcome to your SideQuests Brain Wiki persona projection.\n",
        "## Recent Pages\n"
    ]
    for p in pages[:10]:
        lines.append(f"- [[pages/{p.slug}|{p.title}]]")
    
    lines.append("\n## Navigation\n")
    lines.append("- [[Index]]")
    lines.append("- [[Topics]]")
    lines.append("- [[Sources]]")
    
    return "\n".join(lines)

def _render_index_pages(pages: list[WikiPage]) -> dict[str, str]:
    # Index.md
    index_lines = ["# Index\n", "All generated pages in this persona:\n"]
    for p in sorted(pages, key=lambda x: x.title):
        index_lines.append(f"- [[pages/{p.slug}|{p.title}]]")
    
    # Topics.md (Stub for now)
    topics_lines = ["# Topics\n", "Thematic grouping of your knowledge.\n", "*(Automatic topic clustering coming soon)*\n"]
    
    # Sources.md (Stub for now)
    sources_lines = ["# Sources\n", "Knowledge grouped by source provenance.\n"]
    
    return {
        "Index": "\n".join(index_lines),
        "Topics": "\n".join(topics_lines),
        "Sources": "\n".join(sources_lines)
    }

def _write_atomic(path: Path, content: str) -> bool:
    """Write content to path atomically. Returns True if drift was detected."""
    path.parent.mkdir(parents=True, exist_ok=True)
    drifted = False
    
    if path.exists():
        try:
            with open(path, 'r') as f:
                existing = f.read()
            
            if "sidequests_projection: true" in existing:
                # Extract stored hash and body to check for drift
                hash_match = re.search(r'projection_hash: "(.*?)"', existing)
                if hash_match:
                    stored_hash = hash_match.group(1)
                    # Find where the body starts (after frontmatter)
                    parts = existing.split("---", 2)
                    if len(parts) >= 3:
                        # Extract the actual body as it would have been hashed
                        # Heuristic: the body starts after the read-only notice and title
                        # but in the existing file it's hard to precisely find the start.
                        # Instead, we check if the WHOLE file below frontmatter was edited.
                        existing_content_below_fm = parts[2].strip()
                        
                        new_parts = content.split("---", 2)
                        new_content_below_fm = new_parts[2].strip()
                        
                        if existing_content_below_fm != new_content_below_fm:
                            # User changed something. Let's see if they changed the body.
                            # We can check if the EXISTING body matches its OWN stored hash.
                            # Since we don't know where it starts, we'll use a simpler 'diff' check.
                            conflict_path = path.with_suffix(".conflict.md")
                            os.replace(path, conflict_path)
                            logger.info(f"Drift detected in {path}, moved to {conflict_path}")
                            drifted = True
        except Exception as e:
            logger.error(f"Error during drift detection for {path}: {e}")

    with tempfile.NamedTemporaryFile('w', delete=False, dir=path.parent) as tf:
        tf.write(content)
        temp_name = tf.name
    os.replace(temp_name, path)
    return drifted

def _slugify(title: str) -> str:
    # Already implemented in WikiPage __post_init__ but keeping helper for clarity
    slug = title.replace(" ", "-").lower()
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    return slug
