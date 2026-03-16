# SideQuest Project — Session Memories Backup

**Created:** March 7, 2026
**Last Updated:** March 9, 2026
**Source:** Claude Code auto-memory (`~/.claude/projects/.../memory/MEMORY.md`)

---

## Project Status
- Phase 0 planning complete. Ready to start M1 implementation.
- Key docs:
  - `InvertorsDocs/Side Quests - Inventor's Notebook (2).docx` — updated spec (.docx)
  - `InvertorsDocs/SideQuests-InventorsNotebook.md` — markdown copy of notebook
  - `InvertorsDocs/SideQuestPlan01.md` — Phase 0 implementation plan
  - `CLAUDE.md` — implementation guide for Claude Code sessions

---

## Architecture Decisions (Locked)

- **No OpenClaw in Phase 0.** Standalone Brain Daemon + direct MCP STDIO adapters for Claude Code and Codex. OpenClaw fork is deferred to Phase 1.
- **LLM:** Configurable via `sidequests.toml`. Ollama (default, local, no data leaves machine). OpenAI/Anthropic/Google as opt-in cloud. All providers use OpenAI-SDK-compatible interface.
- **UI:** FastAPI web app, bound to `127.0.0.1` only (no external access).
- **Quest lifecycle:** MainQuest auto-created from git repo root hash + branch. SideQuest manually declared via `branch_quest` MCP tool. Future goal: auto-detect via topic divergence embedding.
- **Hardware:** Apple Silicon Mac (M-series). Ollama + `llama3.1:8b` is the recommended default.

---

## Gated Consolidation Loop — Order (now 9 steps)

1. **spaCy NER (Zoning)** — zero LLM cost, extracts raw concepts
1b. **Relation Extraction: Fast Path** — universal verb patterns only (REQUIRES, ENABLES, REPLACES, CONTRADICTS, PART_OF). Zero LLM cost, domain-agnostic. `step1b_relations.py`. REBEL dropped (Wikipedia-trained, domain-mismatched).
2. **gist hybrid classification** — System 1 (embedding >0.85) / System 2 (LLM fallback 0.60–0.85) / early exit noise (<0.60). Centroids seeded from `GistSeedExamples.md` (105 examples, 15 per class).
3. **schema.org sub-graph routing** — BEFORE pattern matching (this ordering is intentional and is a novelty claim)
3b. **Relation Extraction: Semantic Path** — Ollama with gist+schema.org type context. Handles CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO. Triggered: >1 entity AND Step 1b found nothing. `step3b_relations.py`. "Know the shape before semantic work" principle applied to relation extraction.
4. **Heuristic pattern matching + Cocktail Party selective attention** — confidence gate IS the attention filter. <60% noise, 60–90% confidence_low, >90% full attention. Named IP claim: Cocktail Party Effect.
5. **Dual-scope retrieval** — branch scope first, then global
6. **Constrained contradiction arbitration** — gray zone 0.75–0.92 only
7. **Pathway update** — strengthen (log decay formula) or DEPRECATED_BY edge. CO_OCCURS_WITH written at end of Step 7.

---

## Key Design Principles

- **Kahneman System 1/2 is a named novelty claim** for Step 2 — not just an optimization. Document explicitly in IP filings.
- **Ontology routing (Steps 2–3) precedes pattern matching (Step 4) by design** — this is IP. Knowing semantic shape before pattern matching narrows template space.
- **pathway_strength decay formula:** `new_strength = current + 1 * log(1 + 1/days_since_last_access)`
- **System 2 LLM fallback examples are saved** → gist centroids improve over time (self-improving classifier)
- **gist → schema.org routing table** is proprietary IP — do not publish before provisional patent filing.
- **Graph is a first-class citizen** — any entity with identity, relationships, or query value is a node, not a property.

---

## Graph Schema Additions (March 8, 2026)

### Session & Infrastructure Nodes
| Node | Key Fields | Purpose |
|------|-----------|---------|
| `Session` | `session_id`, `started_at`, `last_active_at`, `onboarded (BOOLEAN)`, `purpose` | Tracks each LLM connection; enables Option C onboarding (full prompt on first session, short fragment after) |
| `LLMProvider` | `provider_id`, `provider_name`, `model_name`, `is_local`, `context_window` | First-class node (not property) — enables cross-LLM analytics and contradiction rate by model |
| `Workspace` | `workspace_id`, `path`, `os`, `hostname` | Separates physical machine context from session; enables multi-machine/multi-user scenarios |

### Ontology Nodes
| Node | Key Fields | Purpose |
|------|-----------|---------|
| `GistClass` | `name` | gist upper-level classes stored as graph nodes |
| `SchemaOrgType` | `name`, `properties[]` | schema.org types + relevant property subsets stored as graph nodes |

The gist → schema.org routing table is stored as `(GistClass)-[ROUTES_TO]->(SchemaOrgType)` edges — queryable, updatable without code deploys, seeded at schema init (M1).

**Full routing table (locked March 9, 2026):**
| gist Class | schema.org Type | Properties |
|------------|----------------|------------|
| gist:Restriction | schema:Demand | eligibleCustomerType, availability, validFrom, validThrough, businessFunction, description |
| gist:PlannedEvent | schema:Action | agent, object, target, actionStatus, startTime, endTime, result, instrument |
| gist:PhysicalThing | schema:Product | name, identifier, description, version, inLanguage, isAccessoryOrSparePartFor |
| gist:Magnitude | schema:QuantitativeValue | value, unitCode, unitText, minValue, maxValue, valueReference |
| gist:Category | schema:DefinedTerm | name, description, termCode, inDefinedTermSet, sameAs |
| gist:Agent (person) | schema:Person | name, jobTitle, description, email, knowsAbout |
| gist:Agent (org/system) | schema:Organization | name, description, member, parentOrganization, contactPoint |
| gist:Event | schema:Event | name, startDate, endDate, eventStatus, location, organizer, description |

Agent disambiguation: spaCy PERSON → schema:Person, ORG → schema:Organization (uses Step 1 output, zero extra LLM cost).

### New Relationships
```
(Session)-[USED]->(LLMProvider)
(Session)-[IN_WORKSPACE]->(Workspace)
(Session)-[WORKING_ON]->(MainQuest | SideQuest)
(MainQuest)-[ANCHORED_TO]->(Workspace)
(Message)-[SENT_IN]->(Session)
(Decision | Constraint)-[ESTABLISHED_IN]->(Session)
(GistClass)-[ROUTES_TO]->(SchemaOrgType)
```

### Pre-Build Decisions (March 8, 2026)

| Decision | Choice |
|----------|--------|
| IPC protocol | JSON-RPC 2.0 over Unix socket — same as MCP. `asyncio` + built-in `json`, no library. |
| Tool schemas | JSON Schema. M2 LLM-facing tool: `current_truth` only. `ingest_message` is internal — passive ingestion via adapter, not LLM-callable. |
| Confidence model | Living property — no blocking gate. 60–90% stored with `confidence_low=true`. Re-scored event-driven (Step 7) + background sweep. Auto-promote >90%, auto-archive <60%. |
| Memory audit | `sidequests review` CLI is optional audit tool, not required gate. M7 replaces with web UI. |
| current_truth ranking | Results ranked by `pathway_strength × confidence` — low-confidence nodes surface but rank lower. |
| Installation | `sidequests setup [--target]` — writes `sidequests.toml`, registers `.mcp.json` (Claude Code) or `claude_desktop_config.json` (Claude desktop), etc. |
| SchemaOrgType property subsets | Full routing table locked (see Ontology Nodes section above). Agent dual-routing: PERSON/ORG from spaCy Step 1 output. |
| Always-on system prompt fragment | ~28 tokens. "Brain capturing automatically" + current_truth + offer branch_quest. No ingest_message trigger — passive ingestion is automatic. |
| CO_OCCURS_WITH write timing | End of Step 7, for all concept pairs from same message that cleared noise floor (>60%). strength = min(confidence_A, confidence_B). |

### LLM Adapter Instruction Model (Locked March 9, 2026)
- **Always-on system prompt fragment** (~28 tokens, every session): "Brain capturing automatically" + current_truth + offer branch_quest. No ingest_message trigger — passive ingestion is automatic.
- **Onboarding skill** (run once per LLM+Quest combination) — full cognitive model: Brain always-on, selective attention, two controls (current_truth + branch_quest), confidence_low handling.
- **Option C onboarding state** — Brain Daemon tracks `onboarded` on `Session` node per LLM+Quest; first session gets full prompt, subsequent sessions get short fragment.
- **Purpose/intent capture** — triggered by first confirmed (>90%) artifact. Ollama synthesizes 1-2 sentence purpose. Stored confidence_low=true on Session.purpose + MainQuest/SideQuest.purpose. User edits via Memory Control Panel (M7).

---

## Biomimetic Heuristics (Named Cognitive Science Principles — All IP Claims)

| Loop Step / Mechanism | Cognitive Principle |
|----------------------|-------------------|
| Step 2 — gist hybrid classifier | Kahneman System 1 (fast, automatic) / System 2 (deliberate) |
| Step 4 — selective attention gate | Cocktail Party Effect (always-on passive Brain, confidence gate IS the attention filter) |
| Step 4 — artifact pattern matching | Representativeness Heuristic |
| Step 5 — candidate retrieval | Availability Heuristic |
| Step 7 — pathway strengthening | Recognition Heuristic / Neural Pathway Reinforcement |
| Background sweep — decay + archive | Synaptic Pruning ("use it or lose it") |
| Background sweep — decay formula | Ebbinghaus Forgetting Curve (exponential decay without recall) |
| CO_OCCURS_WITH edge accumulation | Hebbian Learning — "fire together, wire together" |
| altLabel accumulation | Hebbian Learning — "wire together" at label level |
| CO_OCCURS_WITH → named edge promotion | Long-Term Potentiation (LTP) — implicit → explicit |

## Hebbian Promotion — Three Triggers (in order)
1. **Loop explicit extraction** — Step 1b verb pattern match (`inferred_by: "system"`) or Step 3b Ollama (`inferred_by: "LLM"`), confidence 0.85+. REBEL dropped.
2. **LLM auto** — co_occurrence_count ≥ 10 (configurable, `[hebbian] co_occurrence_threshold = 10`), LLM names the relationship. `inferred_by: "LLM"`, confidence 0.70–0.85
3. **User manual** — Memory Control Panel. `inferred_by: "user"`, confidence 1.0 (trusted)
CO_OCCURS_WITH always preserved alongside named edge (dual-edge, implicit + explicit layers).

## Label Nodes (SKOS-Inspired, Graph-Native)
- `Label` node: text, embedding (own vector), language, label_type (preferred|alternative|hidden), confidence, source, created_at
- `(ArtifactNode)-[HAS_PREF_LABEL|HAS_ALT_LABEL|HAS_HIDDEN_LABEL]->(Label)`
- current_truth searches concept AND label embeddings — findable via any phrasing
- Labels also decay via Synaptic Pruning (unused altLabels archive over time)

---

## User Preferences

- DJ runs Apple Silicon Mac (M-series). Ollama + `llama3.1:8b` is the default local LLM.
- Prefers iterative discussion before building — asks clarifying questions before committing to implementation choices.
- Thinks in biomimetic / cognitive science terms — use that framing when explaining design choices.
- Wants configurable options (e.g., LLM provider) rather than hardcoded defaults — design for flexibility from the start.

---

## Files Created This Session

| File | Location | Purpose |
|------|----------|---------|
| `Side Quests - Inventor's Notebook (2).docx` | `InvertorsDocs/` | Updated notebook with all refined specs |
| `SideQuests-InventorsNotebook.md` | `InvertorsDocs/` | Markdown copy of notebook |
| `SideQuestPlan01.md` | `InvertorsDocs/` | Phase 0 implementation plan |
| `CLAUDE.md` | `SideQuest/` | Claude Code implementation guide |
| `Memories.md` | `InvertorsDocs/` | This file — session memory backup |
| `GistSeedExamples.md` | `InvertorsDocs/` | 105 seed examples (15 per gist class) for Step 2 centroid bootstrapping |
