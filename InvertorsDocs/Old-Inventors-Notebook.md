# Side Quests - Inventor's Notebook

This document serves as the official record for the conception and development of the invention known as "Side Quests." All entries are to be considered confidential and proprietary.

## Journal of Updates

March 20, 2026 (Implementation): Completed full implementation of B17 (Semantic Quest Routing / Hippocampus), B18 (Working Memory Awareness), B3 (ChatGPT Desktop SSE Endpoint), and B2 (Cowork Plugin for Claude Desktop). All features implemented and tested — 474 tests passing across the full test suite, zero failures. Extracted canonical tool schemas into shared module (mcp_engine/tool_schemas.py) to prevent tool list drift across 4 stdio adapters + SSE endpoint. Created Claude Desktop / Cowork plugin with 4 skills (memory-awareness, recall, quest-management, status) following Anthropic's knowledge-work-plugins format.

March 16, 2026: B12 IP formalization. (1) Added Section 5.5.F "Out-of-Band Behavioral Integrity Monitoring" — named IP claim documenting the Brain Daemon's architectural isolation as a security property. The out-of-band process model means LLM prompt injection cannot alter the Brain's logic or stored GlobalConstraints. Step 4 Contradiction sense fires when notify_turn content conflicts with a high-confidence GlobalConstraint, providing passive conversation-layer security monitoring without explicit rules. (2) Added Claim #6 "Cocktail Party Effect (Selective Attention for Memory Formation)" to Section 5.7 — formalized the selective attention biomimetic principle as a distinct novelty claim. (3) Added Claim #7 "Out-of-Band Behavioral Integrity Monitoring via Contradiction Detection" to Section 5.7 — distinguished from Cocktail Party Effect: same Step 4 mechanism, positive vs. negative signal interpretation. Flagged to patent attorney as distinct claim from Cocktail Party Effect. (4) Updated CLAUDE.md with Anomaly/Security sense row in the Cocktail Party Effect sensory table.

March 7, 2026: Major architectural refinement session. (1) Corrected the Gated Consolidation Loop to a precise 7-step biomimetic sequence: NER Zoning → gist Rapid Classification → schema.org Sub-graph Routing → Heuristic Pattern Matching → Dual-Scope Retrieval → Contradiction Arbitration → Pathway Update. (2) Repositioned Dynamic Hybrid Ontology Routing (Steps 2–3) to PRECEDE pattern matching, enabling faster and more accurate confidence scoring — knowing the ontological shape of a concept before pattern matching dramatically narrows the template search space. (3) Explicitly integrated Kahneman's 'Thinking Fast and Slow' dual-process theory as a named biomimetic principle: Step 2 gist classification implements a System 1 (embedding similarity, sub-millisecond) / System 2 (LLM fallback for ambiguous cases) hybrid classifier. This is now a named novelty claim. (4) Specified a configurable LLM provider abstraction (Ollama default, GPT/Claude/Gemini as opt-in cloud providers). Uses an OpenAI-SDK-compatible interface so Ollama and cloud providers share the same code path. (5) Updated Phase 0 architecture: removed OpenClaw fork. Phase 0 is now a standalone Brain Daemon + direct MCP STDIO adapters for Claude Desktop, Claude Code, and Codex. OpenClaw fork is deferred to a later phase. (6) Defined Quest Lifecycle: MainQuest auto-created from git repo root hash + branch; manual SideQuest branching in Phase 0, with roadmap to full auto-detection via topic divergence embedding.

March 6, 2026: Integrated "Analogical Reasoning" (Cross-Quest Experience Transfer) into the Biomimetic Heuristic Engine. Documented the system's ability to infer learnings from historically distinct projects (e.g., pulling AWS deployment constraints from a project 3 months ago into a brand new MainQuest) without manual context loading. Added the "Cross-Project Analogical Test" to the Acceptance Criteria.

March 5, 2026 (Late PM): Refined the "Human-Agent Bridge" and "Open Brain" capabilities to ensure scalable graph normalization. Added a first-class Document instance node to prevent metadata bloat when ingesting large files, establishing a [DERIVED_FROM] relationship for DocumentExtracts. Clarified that vector embeddings are mandatory for core artifacts but optional for audit nodes, adding schema fields for embedding_model and embedding_dim. Appended explicit Acceptance Criteria for testing these ingestion pathways.

March 5, 2026 (PM): Explicitly documented two critical capabilities to ensure the system functions as a true "Universal Brain." 1) The Human-Agent Bridge: Formalized the requirement that core graph nodes must simultaneously store raw natural language and vector embeddings. 2) Universal Document Ingestion ("Open Brain" Capability): Expanded the ingestion pipeline to accept static documents and notes.

March 5, 2026 (Mid-Morning): Created a dedicated technical schematic (Section 5.4.C) for the Dynamic Hybrid Ontology Routing. Explicitly documented the two-stage extraction method utilizing the gist upper ontology for routing to granular sub-graphs of schema.org.

March 4, 2026 (Final PM): Hardened the novelty claims by transitioning the technical spine to a concrete "Gated Consolidation Loop." Added exact mechanical details for reversible merges (delta tracking), LLM arbitration guardrails, and a dual-scope retrieval system. Radically tightened the Phase 0 security manifest to mandate stdio transport and strict path canonicalization.

March 4, 2026 (Late PM): Explicitly defined the "Engine Contract" and the algorithmic "Consolidation Loop". Tightened the product wedge to focus on a tangible "Decision Log & Constraint Ledger".

March 4, 2026 (PM): Strategic Pivot based on market/security analysis. Acknowledged Zep, Mem0, and Letta as competitors. Re-centered our absolute core IP differentiator on the Biomimetic Heuristic Engine. Added Temporal Truth Handling and Reversible Merges.

March 4, 2026 (AM): Added Section 5.4 (Technical Schematics & Data Structures) to provide an "enabling disclosure" of the invention.

March 3, 2026: Integrated the Model Context Protocol (MCP) as the universal wrapper for the Memory Core.

February 28, 2026: Upgraded the Ingestion Pipeline design to utilize a "Biomimetic Memory Extraction Flow."

February 26, 2026: Refined Phase 0 strategy to focus on forking 'OpenClaw' as an "Open-Source Engine Swap." Defined local build strategy using Kùzu.

September 17-19, 2025: Initial formalization of core decoupled architecture, Graph-Native RAG, and the "branch and merge" workflow.

## 1. Title of Invention

A System and Method for Contextual Management of AI-Driven Projects Using a Gated Consolidation Loop and Relational Knowledge Graph.

## 2. Date of Conception

Initial Idea & Knowledge Graph Concept: August 17, 2025

## 3. Inventor(s)

Don J. Shelton

## 4. Problem Statement (The "Why")

Core Problem: AI language models (LLMs) suffer from "context-collapse" and "amnesia" during complex, multi-step projects. While emerging solutions offer "universal memory" (e.g., Zep, Mem0) or baseline Knowledge Graph MCP servers, they act as passive filing cabinets relying on standard vector similarity or basic routing. They fail to process information cognitively—by recognizing patterns, deterministically strengthening existing knowledge pathways, and anchoring exploratory tangents (Side Quests) back to primary objectives (the Main Quest). This lack of active, gated consolidation leads to cluttered, contradictory, and untrusted AI memory.

## 5. Detailed Description of the Invention (The "How")

5.1. Overview:
"Side Quests" is a software system that transcends basic AI memory. It introduces a novel method for structuring user-AI interactions by utilizing a Biomimetic Heuristic Engine (powered technically by a Gated Consolidation Loop) to transform a high-level goal into a dynamic, editable, relational knowledge graph. The core promise is: Never lose the main objective; side quests become structured, mergeable context powered by active cognitive processing.

5.2. System Architecture: A Decoupled, Modular Approach
A. The Side Quests Application (Frontend - The Memory Control Panel):
This is an interactive UI layer that provides "editability." Users can view the graph generated by the engine, pin crucial Decisions, flag incorrect AI memories, "forget" deprecated Constraints, and manually promote a SideQuest to a MainQuest.

B. The Memory Core Platform (MCP) Server (Backend):
Graph & Vector Store (e.g., Kùzu): Long-term, structured, and semantic memory. Crucial Capability ("The Human-Agent Bridge"): The database actively bridges the gap between what humans understand and what agents understand. Every core artifact node simultaneously stores raw natural language text alongside FLOAT32 vector embeddings.

Ingestion Pipeline: Processes raw data using the core Gated Consolidation Loop (detailed in Section 5.3).

Universal Query API (Model Context Protocol - MCP): Allows any compliant AI client to plug into this structured "Project Brain."

C. Working Memory Awareness (Context Engine):
**Implementation Status (March 20, 2026):** Fully implemented in `mcp_engine/working_memory.py`. Key functions:
- `track_loaded()` — creates LOADED edges when current_truth returns results
- `deduplicate_results()` — applies 0.3x demotion factor to already-loaded nodes
- `estimate_tokens()` — heuristic: len(text) // 3 chars per token
- `get_session_token_state()` — returns utilization, loaded count, bloat warning
- `check_context_health()` — fires warning at 75% utilization
- `get_handoff_context()` — retrieves top 5 LOADED nodes from prior session

Constants: BLOAT_WARNING_THRESHOLD = 0.75, DEDUP_DEMOTION_FACTOR = 0.3, DEFAULT_TOKEN_LIMIT = 128000, CHARS_PER_TOKEN = 3.
Tested: 7 test classes in tests/test_working_memory.py covering token estimation, load tracking, deduplication, context health, session handoff, token state, and context_status tool.

5.3. The Gated Consolidation Loop (Core IP & Primary Defensible Moat)
Unlike traditional vector databases or baseline KG servers that act as passive storage, the primary invention is the MCP's active consolidation of memory by mimicking human cognitive heuristics — specifically the Representativeness, Availability, and Recognition heuristics identified in cognitive psychology, combined with Kahneman's dual-process theory of fast and slow thinking.

The Engine Contract:
Input: Raw chat message streams OR static natural language documents/notes + current quest graph state.
Output: (a) Updated artifact graph, (b) A ranked 'current truth' view (filtering deprecated nodes), (c) A fully reversible audit trail.

The Gated Consolidation Loop — 7-Step Biomimetic Algorithm:

Step 1 — Zoning / NER (Concept Extraction)
The system first performs Named Entity Recognition (NER) to extract the raw concepts: people, places, organizations, physical objects, quantities, events, and actions. This step uses a fast local NLP model (spaCy) with zero LLM cost.

Step 2 — gist Rapid Classification (Kahneman System 1 / System 2)
Maps each concept to a high-level ontological class using the gist upper ontology. 
  • System 1 (Fast, Automatic): Embedding cosine similarity > 0.85 accepted immediately.
  • System 2 (Slow, Deliberate): If similarity 0.60–0.85, escalate to constrained local LLM call.
  • Early Exit (< 0.60): Classified as noise.

Step 3 — schema.org Sub-graph Routing (Speed & Precision)
Dynamically loads relevant sub-graph of schema.org vocabulary based on gist classification. Narrowing the search space BEFORE pattern matching enables faster, more accurate classification.

Step 4 — Heuristic Pattern Matching (Representativeness Heuristic)
Classifies the message into a specific work artifact type. 
  • < 60% confidence: Vector-log as noise.
  • 60% – 90% confidence: Soft-lock (user confirmation required).
  • > 90% confidence: Hard-lock (direct insertion).

Step 5 — Dual-Scope Candidate Retrieval (Availability Heuristic)
Checks if concept already exists in Branch Scope (structural proximity) or Global Scope (GlobalConstraint/Preference nodes).

Step 6 — Constrained Contradiction Arbitration
Strictly governed LLM arbitration triggers in the 'gray zone' (0.75–0.92) or for identical artifact types.

Step 7 — Pathway Update (Recognition/Availability Heuristic)
Reinforces existing neural pathways:
  • Additive result: Increments pathway_strength (new_strength = current_strength + 1 * decay_factor).
  • Contradiction detected: Creates new node + [DEPRECATED_BY] edge from old.

Universal File Ingestion ('The Open Brain' Capability):
Ingests documents by creating Document instance nodes and semantically chunked DocumentExtract child nodes, processed via the Gated Consolidation Loop with precise provenance tracking.

5.4. Technical Schematics & Data Structures (Enabling Disclosure)
A. The Work-Artifact Graph Schema:
Driven by the Consolidation Loop, structured around knowledge-worker artifacts.

Nodes:
- MainQuest, SideQuest
  - MainQuest new fields: `git_repo_root STRING`, `purpose_embedding FLOAT[384]`, `routing_method STRING`
- Decision, Constraint, Requirement, ActionItem
- GlobalConstraint, GlobalPreference
- Document: Fields: document_id, location_uri, content_hash, last_modified_at, mime_type.
- Message / DocumentExtract: Fields include byte_start/byte_end or line ranges for provenance.
- Session: Tracks working memory state. Fields: `session_id`, `routing_state`, `routing_confidence`, `routing_method`, `content_embedding FLOAT[384]`, `token_estimate INT64`, `token_limit INT64`, `loaded_node_count INT32`, `last_injection_at TIMESTAMP`.
- MergeEvent: Audit node for reversible merges.

Relationships:
- (SideQuest)-[BELONGS_TO]->(MainQuest)
- (DocumentExtract)-[DERIVED_FROM]->(Document)
- (Message | DocumentExtract)-[ESTABLISHED]->(Decision | Constraint)
- (Decision)-[DEPRECATES]->(Decision) (Temporal Truth handling)
- (Session)-[REROUTED_FROM]->(MainQuest) (Audit trail for prediction error)
- (Session)-[LOADED]->(multiple artifact types) (Working memory tracking)

B. Deterministic Dual-Pointer Structure for Reversible Merges:
Uses a dual-pointer MergeEvent node containing state deltas for non-destructive, reversible merges.

C. Dynamic Hybrid Ontology Routing:
Positioned BEFORE heuristic pattern matching to narrow the template space and improve precision.
- Stage 1: High-Speed gist classification (System 1/2).
- Stage 2: Granular schema.org sub-graph extraction.

5.5. Initial User & Adoption Target (Local Multi‑Assistant “SideQuests Brain”)

Initial User: The Inventor (DJ) — a developer routinely executing workflows across multiple AI coding and work assistants (Claude Desktop, Claude Code, Codex, Gemini CLI, ChatGPT Desktop).

Core Goal: A single, isolated local “SideQuests Brain” that all assistants can read from and write to concurrently.

A. Local Deployment Architecture (Phase 0 — Standalone Brain Daemon):
Phase 0 builds the Brain Daemon as a fully standalone Python service. It provides a secure local IPC API (Unix socket/named pipe) and an MCP-over-SSE transport for HTTP-capable clients (ChatGPT Desktop).

B. Cross-Assistant Integration (Seamless Continuity):
MainQuest Anchoring: Deterministic ID hash of project repo root + branch auto-aligns CLI tools.

C. Semantic Quest Routing (The Hippocampus):
**Implementation Status (March 20, 2026):** Fully implemented in `mcp_engine/hippocampus.py`. Key functions:
- `route_session()` — main entry point, returns (quest_id, confidence, method, is_new_quest)
- `_system1_git_match()` — legacy hash match for backward compatibility
- `_system1_semantic_match()` — Python-side cosine similarity against active quest purpose_embeddings
- `_system2_disambiguate()` — LLM picks the right quest or creates new
- `update_routing_strength()` — per-message progressive consolidation
- `reconsolidate()` — prediction error re-routing with REROUTED_FROM audit trail

D. Local Acceptance Criteria:
Successfully reduced to practice when multi-agent state share, temporal deprecation flow, deterministic rollback, the bridge test, the open brain test, and the cross-project analogical test pass.

E. Shared Tool Surface:
All adapters (stdio + SSE) expose the exact same 11 tools defined in `mcp_engine/tool_schemas.py`:
- `notify_turn` — forward turns to Brain
- `current_truth` — retrieve relevant memory
- `branch_quest` — create side quest
- `diff_since` — changes since prior session
- `get_open_loops` — unresolved tentative nodes
- `analogical_search` — cross-quest pattern search
- `ingest_document` — feed documents to Brain
- `explore_graph` — directed graph traversal
- `complete_quest` — mark quest as done
- `set_quest` — explicitly bind session to quest
- `context_status` — context window health awareness

F. Out-of-Band Behavioral Integrity Monitoring (Named IP Claim):
The Brain Daemon operates as a separate process from the LLM session, providing conversation-layer security. 
1. Architectural isolation: Different OS process, immune to prompt injection via the LLM's context window.
2. GlobalConstraints as policy baseline: Persistent security policy.
3. Contradiction sense fires automatically: Detects prompt injection, goal hijacking, and constraint violation.

G. Adoption Path:
Phase 0: Standalone daemon with stdio adapters. 
Phase 1: Additional adapters (Gemini CLI) + OpenClaw engine swap.
Phase 2: Remote/hosted enterprise variants after IP filing.

5.6. Evaluation & Proof of Efficacy (Internal Benchmark):
Evaluated against a benchmark of 50 multi-session transcripts. Target: < 2% harmful merge rate, < 2% false deprecation rate, > 30% recall improvement.

5.7. Novelty & Non-Obviousness:
Novel cognitive science principles:
1. Kahneman Dual-Process Architecture (System 1 / System 2).
2. Ontology-First Pattern Matching.
3. Representativeness Heuristic (Artifact classification).
4. Availability Heuristic (Dual-scope retrieval).
5. Gated Consolidation Loop mechanisms (Tiered gating, contradiction guardrails, reversible merges).
6. Cocktail Party Effect (Selective attention filter).
7. Out-of-Band Behavioral Integrity Monitoring via Contradiction Detection.
8. Semantic Quest Routing — Context-based routing to subgraphs without filesystem anchors.
9. Hippocampus Mechanism — Two-phase (System 1/2) binding with progressive consolidation.
10. Prediction Error Reconsolidation — Automatic re-routing with audit trail.
11. Multi-Signal Routing Fusion — Combining git, semantic, and entity signals into unified confidence.
12. Context Window as Working Memory Model — Session-tracked working memory buffer.
13. Smart Deduplication via Load Tracking — Demoting already-loaded graph nodes.
14. Declarative Knowledge Plugin Architecture — File-based plugin teaching LLM memory tool use without code execution.

## 6. Diagrams and Flowcharts

System Architecture Diagram
User Flow Diagram
MCP Ingestion Pipeline Flowchart

## 7. Prior Art

Direct Competitors: Zep, Mem0, Letta, MCP Baseline KG Server.
Differentiation: Gated Consolidation Loop, tiered gating, contradiction guardrails, ontology routing, and deterministic reversible merges for Task-Oriented Narrative Structure.

## 8. Reduction to Practice

### Implementation Status (as of March 20, 2026)

All 8 core milestones (M1–M8) are fully implemented and tested. Post-M8 features B17, B18, B3, and B2 are also complete.

**Test Evidence:**
- 474 automated tests passing (0 failures, 18 skipped)
- Test categories: adapter integration (145), analogical reasoning (30), hippocampus routing (28), working memory (22), web/SSE endpoints (39), plugin structure (26), quest lifecycle, tools, schema
- All tests run in under 7 seconds on commodity hardware

**Implementation Evidence by Milestone:**
- M1 (Schema + Config): Kùzu schema with 15+ node types, 20+ relationship types, HNSW vector indexes.
- M2 (Passive Ingestion): Claude Code UserPromptSubmit hook + notify_turn MCP tool.
- M3 (Loop Steps 1–4): spaCy NER, gist System 1/2 classification, schema.org routing, Step 4 pattern matching + selective attention.
- M4 (Loop Steps 5–7): Dual-scope retrieval, contradiction arbitration, pathway update + MergeEvent + synaptic pruning.
- M5 (Quest Lifecycle): Git-anchored MainQuest, manual SideQuest branching, RAG read flow.
- M6 (Open Brain): Document + DocumentExtract pipeline with semantic chunking.
- M7 (Memory Control Panel): FastAPI web app with graph visualization, soft-lock UI, merge rollback.
- M8 (Multi-Agent + Analogical): Claude Desktop, Codex, Gemini CLI adapters.

**Post-M8 Features:**
- B13: One-command installer (`sidequests install`) with launchd daemon setup.
- B17 (Hippocampus): Semantic Quest Routing with System 1/2 routing. Module: `mcp_engine/hippocampus.py`.
- B18 (Working Memory): Context window awareness with LOADED edge tracking. Module: `mcp_engine/working_memory.py`.
- B3 (SSE Transport): MCP-over-SSE transport for ChatGPT Desktop. `mcp_engine/tool_schemas.py`.
- B2 (Cowork Plugin): Claude Desktop / Cowork plugin following Anthropic's format.

**Adapter Coverage (5 clients):**
- Claude Code (stdio adapter)
- Claude Desktop (Cowork plugin + stdio adapter)
- Codex (stdio adapter)
- Gemini CLI (stdio adapter)
- ChatGPT Desktop (SSE endpoint)

## Appendix A: Intellectual Property (IP) Strategy Roadmap

(Ongoing - Documenting conception, preparing for Provisional Patent Application before open-source release). To protect enabling disclosure, technical schemas and algorithmic loop details within this document will not be published to open-source repositories prior to filing.

---

## Witness Attestation

I have reviewed this Inventor's Notebook and confirm that the entries accurately describe the invention as explained to me by the inventor.

**Witness 1:**
Name: ___________________________
Signature: ___________________________
Date: ___________________________

**Witness 2:**
Name: ___________________________
Signature: ___________________________
Date: ___________________________

**Inventor:**
Name: Don J. Shelton
Signature: ___________________________
Date: ___________________________
