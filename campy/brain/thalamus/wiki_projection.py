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

async def _select_pages_for_persona(db, persona_cfg: dict, limit: int) -> list[WikiPage]:
    """
    Select nodes from KuzuDB for a specific persona.
    """
    pages = []
    include_domains = persona_cfg.get("include_domains")
    include_node_types = persona_cfg.get("include_node_types")
    persona_name = persona_cfg["name"]

    def _rows(result):
        if result.__class__.__module__.startswith("kuzu") and hasattr(result, "has_next") and hasattr(result, "get_next"):
            while result.has_next():
                yield result.get_next()
            return
        yield from result

    # 1. Lessons
    if not include_node_types or "Lesson" in include_node_types:
        try:
            params = {"lim": limit}
            where_clauses = ["l.archived = false", "l.lesson_type = 'synthesis'"]
            if include_domains:
                where_clauses.append("l.domain IN $domains")
                params["domains"] = include_domains
            
            where_str = " AND ".join(where_clauses)
            
            res = db.execute(
                f"MATCH (l:Lesson) WHERE {where_str} "
                "RETURN l.lesson_id, l.text_raw, l.domain, l.pathway_strength "
                "ORDER BY l.pathway_strength DESC LIMIT $lim",
                params
            )
            for row in _rows(res):
                pages.append(WikiPage(
                    title=f"Lesson: {row[1][:40]}...",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[("Summary", row[1]), ("Domain", row[2] or "unknown")]
                ))
        except Exception:
            logger.debug(f"Failed to query lessons for persona {persona_name}")

    # 2. Procedures
    if (not include_node_types or "Procedure" in include_node_types) and len(pages) < limit:
        try:
            params = {"lim": limit - len(pages)}
            where_clauses = ["p.archived = false"]
            if include_domains:
                where_clauses.append("p.domain IN $domains")
                params["domains"] = include_domains
                
            where_str = " AND ".join(where_clauses)
            
            res = db.execute(
                f"MATCH (p:Procedure) WHERE {where_str} "
                "RETURN p.procedure_id, p.name, p.description, p.archetype "
                "ORDER BY p.name LIMIT $lim",
                params
            )
            for row in _rows(res):
                pages.append(WikiPage(
                    title=f"Procedure: {row[1]}",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[("Description", row[2]), ("Archetype", row[3] or "generic")]
                ))
        except Exception:
            logger.debug(f"Failed to query procedures for persona {persona_name}")

    # 3. ARC Runs (B225)
    if (not include_node_types or "ArcRun" in include_node_types) and len(pages) < limit:
        try:
            params = {"lim": limit - len(pages)}
            res = db.execute(
                "MATCH (r:ArcRun) "
                "RETURN r.run_id, r.summary, r.domain, r.status, r.task_count, "
                "r.solved_count, r.failed_count, r.step_count, r.source_files "
                "ORDER BY r.created_at DESC LIMIT $lim",
                params
            )
            for row in _rows(res):
                # B229 — World Model Health section
                wm_section = ""
                try:
                    wm_res = db.execute(
                        "MATCH (r:ArcRun {run_id: $run_id})-[:ARC_RUN_HAS_WORLD_MODEL_SUMMARY]->(s:ArcWorldModelSummary) "
                        "RETURN s.graph_bounded, s.compiler_active, s.falsification_active, "
                        "s.reasoning_gated, s.planner_grounded, s.memory_transfer_active, "
                        "s.single_action_stall_detected, s.full_reasoning_cycles_avoided "
                        "ORDER BY s.created_at DESC LIMIT 1",
                        {"run_id": row[0]}
                    )
                    if wm_res.has_next():
                        wm_row = wm_res.get_next()
                        wm_section = (
                            f"bounded={bool(wm_row[0])}, compiler={bool(wm_row[1])}, "
                            f"falsification={bool(wm_row[2])}, reasoning_gated={bool(wm_row[3])}, "
                            f"planner={bool(wm_row[4])}, memory_transfer={bool(wm_row[5])}\n\n"
                            f"stall_detected={bool(wm_row[6])}, cycles_avoided={wm_row[7] or 0}"
                        )
                except Exception:
                    pass

                pages.append(WikiPage(
                    title=f"ARC Run: {row[0]}",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[
                        ("Summary", row[1] or ""),
                        ("Status", row[3] or "unknown"),
                        ("Run Metrics", f"tasks={row[4] or 0}, solved={row[5] or 0}, failed={row[6] or 0}, steps={row[7] or 0}"),
                        ("World Model Health", wm_section or "No world-model evaluation data found for this run."),
                        ("Domain", row[2] or ""),
                        ("Provenance", f"Graph source: {row[0]}\n\nArtifact paths: {row[8] or '[]'}"),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcRun for persona {persona_name}")

    # 4. ARC Task Results (B225)
    if (not include_node_types or "ArcTaskResult" in include_node_types) and len(pages) < limit:
        try:
            params = {"lim": limit - len(pages)}
            res = db.execute(
                "MATCH (t:ArcTaskResult) "
                "RETURN t.task_result_id, t.summary, t.domain, t.status, t.task_id, "
                "t.puzzle_id, t.correct, t.steps, t.failure_class "
                "ORDER BY t.created_at DESC LIMIT $lim",
                params
            )
            for row in _rows(res):
                pages.append(WikiPage(
                    title=f"ARC Task: {row[4] or row[5] or row[0]}",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[
                        ("Summary", row[1] or ""),
                        ("Status", row[3] or "unknown"),
                        ("Task Metrics", f"task_id={row[4] or ''}, puzzle_id={row[5] or ''}, correct={bool(row[6])}, steps={row[7] or 0}"),
                        ("Failure Class", row[8] or ""),
                        ("Domain", row[2] or ""),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcTaskResult for persona {persona_name}")

    # 5. ARC Artifacts (B225)
    if (not include_node_types or "ArcArtifact" in include_node_types) and len(pages) < limit:
        try:
            params = {"lim": limit - len(pages)}
            res = db.execute(
                "MATCH (a:ArcArtifact) "
                "RETURN a.artifact_id, a.artifact_kind, a.path, a.content_hash, "
                "a.record_count, a.captured_at, a.ingested_at, a.domain, a.summary "
                "ORDER BY a.ingested_at DESC LIMIT $lim",
                params
            )
            for row in _rows(res):
                pages.append(WikiPage(
                    title=f"ARC Artifact: {row[1] or row[0]}",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[
                        ("Summary", row[8] or ""),
                        ("Artifact", f"kind={row[1] or ''}, records={row[4] or 0}"),
                        ("Path", row[2] or ""),
                        ("Content Hash", row[3] or ""),
                        ("Captured", str(row[5] or "")),
                        ("Ingested", str(row[6] or "")),
                        ("Domain", row[7] or ""),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcArtifact for persona {persona_name}")

    # 6. ARC Events (B225)
    if (not include_node_types or "ArcEvent" in include_node_types) and len(pages) < limit:
        try:
            params = {"lim": limit - len(pages)}
            res = db.execute(
                "MATCH (e:ArcEvent) "
                "RETURN e.event_id, e.run_id, e.task_id, e.event_type, e.timestamp, "
                "e.step_index, e.actor, e.tool_name, e.action_name, e.outcome, "
                "e.domain, e.summary "
                "ORDER BY e.timestamp DESC, e.step_index DESC LIMIT $lim",
                params
            )
            for row in _rows(res):
                step = row[5] if row[5] is not None else "unknown"
                label = row[3] or row[8] or row[7] or row[0]
                pages.append(WikiPage(
                    title=f"ARC Event: step {step} {label}",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[
                        ("Summary", row[11] or ""),
                        ("Event", f"type={row[3] or ''}, step={step}, timestamp={row[4] or ''}"),
                        ("Run", row[1] or ""),
                        ("Task", row[2] or ""),
                        ("Actor And Tool", f"actor={row[6] or ''}, tool={row[7] or ''}, action={row[8] or ''}"),
                        ("Outcome", row[9] or ""),
                        ("Domain", row[10] or ""),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcEvent for persona {persona_name}")

    # 7. ARC World Model Steps (B229)
    if (not include_node_types or "ArcWorldModelStep" in include_node_types) and len(pages) < limit:
        try:
            params = {"lim": limit - len(pages)}
            res = db.execute(
                "MATCH (s:ArcWorldModelStep) "
                "RETURN s.world_model_step_id, s.task_id, s.step_index, s.node_count, "
                "s.edge_count, s.compiled_claim_count, s.action_effect_class, s.reasoning_mode, "
                "s.planner_candidate_count, s.single_action_stall_detected, s.summary "
                "ORDER BY s.created_at DESC LIMIT $lim",
                params
            )
            for row in _rows(res):
                pages.append(WikiPage(
                    title=f"ARC WM Step: task {row[1]} step {row[2]}",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[
                        ("Summary", row[10] or ""),
                        ("Graph Metrics", f"nodes={row[3] or 0}, edges={row[4] or 0}, claims={row[5] or 0}"),
                        ("Execution", f"action_effect={row[6] or ''}, reasoning={row[7] or ''}, candidates={row[8] or 0}, stall_detected={bool(row[9])}"),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcWorldModelStep for persona {persona_name}")

    # 8. ARC World Model Summaries (B229)
    if (not include_node_types or "ArcWorldModelSummary" in include_node_types) and len(pages) < limit:
        try:
            params = {"lim": limit - len(pages)}
            res = db.execute(
                "MATCH (s:ArcWorldModelSummary) "
                "RETURN s.world_model_summary_id, s.task_id, s.graph_bounded, s.compiler_active, "
                "s.falsification_active, s.reasoning_gated, s.planner_grounded, s.memory_transfer_active, "
                "s.single_action_stall_detected, s.full_reasoning_cycles_avoided, s.summary "
                "ORDER BY s.created_at DESC LIMIT $lim",
                params
            )
            for row in _rows(res):
                pages.append(WikiPage(
                    title=f"ARC WM Summary: task {row[1]}",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[
                        ("Summary", row[10] or ""),
                        ("Flags", f"bounded={bool(row[2])}, compiler={bool(row[3])}, falsification={bool(row[4])}, reasoning_gated={bool(row[5])}, planner_grounded={bool(row[6])}, memory_transfer={bool(row[7])}"),
                        ("Stalls and Savings", f"stall_detected={bool(row[8])}, reasoning_cycles_avoided={row[9] or 0}"),
                    ]
                ))
        except Exception:
            logger.debug(f"Failed to query ArcWorldModelSummary for persona {persona_name}")

    # 9. ARC Mechanics (B226)
    if (not include_node_types or "ArcMechanic" in include_node_types) and len(pages) < limit:
        try:
            params = {"lim": limit - len(pages)}
            res = db.execute(
                "MATCH (m:ArcMechanic) "
                "RETURN m.mechanic_id, m.name, m.signature, m.confidence, "
                "m.terminal_relevance, m.coordinate_relevance, m.evidence_count, m.summary "
                "ORDER BY m.confidence DESC LIMIT $lim",
                params
            )
            for row in _rows(res):
                pages.append(WikiPage(
                    title=f"ARC Mechanic: {row[1] or row[0]}",
                    persona=persona_name,
                    source_node_ids=[row[0]],
                    body_sections=[
                        ("Summary", row[7] or ""),
                        ("Signature", row[2] or "unknown"),
                        ("Stats", f"confidence={row[3] or 0.0}, evidence_count={row[6] or 0}"),
                        ("Relevance", f"terminal={row[4] or 0.0}, coordinate={row[5] or 0.0}"),
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
