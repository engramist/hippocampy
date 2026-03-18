# Side Quests - Inventor's Notebook

This document serves as the official record for the conception and development of the invention known as "Side Quests." All entries are to be considered confidential and proprietary.

## Journal of Updates

March 16, 2026: B12 IP formalization. (1) Added Section 5.5.E "Out-of-Band Behavioral Integrity Monitoring" — named IP claim documenting the Brain Daemon's architectural isolation as a security property. The out-of-band process model means LLM prompt injection cannot alter the Brain's logic or stored GlobalConstraints. Step 4 Contradiction sense fires when notify_turn content conflicts with a high-confidence GlobalConstraint, providing passive conversation-layer security monitoring without explicit rules. (2) Added Claim #6 "Cocktail Party Effect (Selective Attention for Memory Formation)" to Section 5.7 — formalized the selective attention biomimetic principle as a distinct novelty claim. (3) Added Claim #7 "Out-of-Band Behavioral Integrity Monitoring via Contradiction Detection" to Section 5.7 — distinguished from Cocktail Party Effect: same Step 4 mechanism, positive vs. negative signal interpretation. Flagged to patent attorney as distinct claim from Cocktail Party Effect. (4) Updated CLAUDE.md with Anomaly/Security sense row in the Cocktail Party Effect sensory table.

March 7, 2026: Major architectural refinement session. (1) Corrected the Gated Consolidation Loop to a precise 7-step biomimetic sequence: NER Zoning → gist Rapid Classification → schema.org Sub-graph Routing → Heuristic Pattern Matching → Dual-Scope Retrieval → Contradiction Arbitration → Pathway Update. (2) Repositioned Dynamic Hybrid Ontology Routing (Steps 2–3) to PRECEDE pattern matching, enabling faster and more accurate confidence scoring — knowing the ontological shape of a concept before pattern matching dramatically narrows the template search space. (3) Explicitly integrated Kahneman's 'Thinking Fast and Slow' dual-process theory as a named biomimetic principle: Step 2 gist classification implements a System 1 (embedding similarity, sub-millisecond) / System 2 (LLM fallback for ambiguous cases) hybrid classifier. This is now a named novelty claim. (4) Specified a configurable LLM provider abstraction (Ollama default, GPT/Claude/Gemini as opt-in cloud providers). Uses an OpenAI-SDK-compatible interface so Ollama and cloud providers share the same code path. (5) Updated Phase 0 architecture: removed OpenClaw fork. Phase 0 is now a standalone Brain Daemon + direct MCP STDIO adapters for Claude Code and Codex. OpenClaw fork is deferred to a later phase. (6) Defined Quest Lifecycle: MainQuest auto-created from git repo root hash + branch; manual SideQuest branching in Phase 0, with roadmap to full auto-detection via topic divergence embedding.

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

Graph & Vector Store (e.g., Kùzu): Long-term, structured, and semantic memory. Crucial Capability ("The Human-Agent Bridge"): The database actively bridges the gap between what humans understand and what agents understand. Every core artifact node simultaneously stores raw natural language text (allowing humans to read and audit the Memory Control Panel) alongside FLOAT32 vector embeddings (allowing the AI to perform mathematical semantic RAG).

Ingestion Pipeline: Processes raw data using the core Gated Consolidation Loop (detailed in Section 5.3).

Universal Query API (Model Context Protocol - MCP): Allows any compliant AI client to plug into this structured "Project Brain."

5.3. The Gated Consolidation Loop (Core IP & Primary Defensible Moat)
Unlike traditional vector databases or baseline KG servers that act as passive storage, the primary invention is the MCP's active consolidation of memory by mimicking human cognitive heuristics — specifically the Representativeness, Availability, and Recognition heuristics identified in cognitive psychology, combined with Kahneman's dual-process theory of fast and slow thinking.

The Engine Contract:
Input: Raw chat message streams OR static natural language documents/notes + current quest graph state.
Output: (a) Updated artifact graph, (b) A ranked 'current truth' view (filtering deprecated nodes), (c) A fully reversible audit trail.

The Gated Consolidation Loop — 7-Step Biomimetic Algorithm:

Step 1 — Zoning / NER (Concept Extraction)
The system first performs Named Entity Recognition (NER) — a well-established NLP process sometimes called 'zoning' — to extract the raw concepts present in the incoming text: people, places, organizations, physical objects, quantities, events, and actions. This step uses a fast local NLP model (spaCy) with zero LLM cost and produces a structured list of typed entities as input to the classification pipeline.

Step 2 — gist Rapid Classification (Kahneman System 1 / System 2)
Once raw concepts are extracted, the system maps each concept to a high-level ontological class using the gist upper ontology (Semantic Arts). gist has a tiny token footprint, making this classification extremely fast. The classifier implements a hybrid dual-process architecture, explicitly modeled on Kahneman's 'Thinking Fast and Slow':
  • System 1 (Fast, Automatic): Embedding cosine similarity is computed between the concept embedding and pre-labeled gist class centroids. If similarity > 0.85, the classification is accepted immediately — no LLM call, sub-millisecond latency.
  • System 2 (Slow, Deliberate): If similarity falls in the 0.60–0.85 ambiguous range, the system escalates to a constrained local LLM call (via the configured provider) to resolve the classification deliberately.
  • Early Exit (< 0.60): If no gist class can be confidently assigned, the message is classified as noise and exits early to standard vector logging — no further pipeline processing.
This design is authentically biomimetic: the human brain uses fast heuristic pattern recognition for familiar inputs and reserves deliberate reasoning for genuinely ambiguous cases. The system improves over time: messages resolved by System 2 are saved as labeled examples, gradually improving the embedding centroids and reducing future System 2 escalations.
gist classes used: PhysicalThing, PlannedEvent, Restriction, Magnitude, Category, Agent, Event.

Step 3 — schema.org Sub-graph Routing (Speed & Precision)
The gist class from Step 2 acts as a router. The system dynamically loads ONLY the relevant sub-graph of the schema.org vocabulary — not the full dictionary — based on the gist classification. For example, gist:Restriction routes to schema:Demand properties; gist:PlannedEvent routes to schema:Action properties. This targeted context window gives the pipeline the precise 'shape' of what it is looking at, dramatically narrowing the search space for the pattern matching step that follows. This ordering — ontology routing BEFORE pattern matching, not after — is a key architectural decision: knowing the semantic shape of a concept in advance enables faster, more accurate artifact classification with fewer false positives.

Step 4 — Heuristic Pattern Matching (Representativeness Heuristic)
With full ontological context now established (gist class + schema.org shape), the system applies the Representativeness Heuristic to classify the message into a specific work artifact type. Extracted concept embeddings are compared against a template set for each artifact type, constrained to only the templates relevant to the schema.org sub-graph from Step 3. A composite confidence score is computed:
  • < 60% confidence: Vector-log the message as noise. No structural extraction.
  • 60% – 90% confidence: Soft-lock. Extract candidate artifact nodes but flag for user confirmation in the Memory Control Panel UI.
  • > 90% confidence: Hard-lock. Proceed directly to Steps 5–7 for full structural extraction and graph insertion.

Step 5 — Dual-Scope Candidate Retrieval (Availability Heuristic)
Before creating any new graph nodes, the system checks whether this concept already exists — mimicking the brain's Availability Heuristic (surfacing what has been seen before). Retrieval is scoped in two passes:
  • Branch Scope: Filter by structural proximity (must share the same MainQuest branch) combined with vector similarity. Finds local duplicates first.
  • Global Scope: If no branch-level hit is found, search GlobalConstraint and GlobalPreference nodes (workspace-level artifacts) to prevent pointless duplication across different quests.

Step 6 — Constrained Contradiction Arbitration
LLM contradiction detection is strictly governed to prevent non-deterministic failures. Arbitration only triggers if vector similarity between the candidate and an existing node falls in the 'gray zone' (0.75–0.92), or if the artifact types match identically (e.g., Decision vs. Decision). The local LLM is forced into a strict output schema: {classification: additive|contradiction|uncertain, rationale_tokens: [...], referenced_nodes: [...]}. If 'uncertain', the system defaults to a UI soft-lock rather than making an autonomous decision.

Step 7 — Pathway Update (Recognition/Availability Heuristic)
The final step updates the graph based on the arbitration result, mimicking how the brain reinforces existing neural pathways rather than creating redundant memories:
  • Additive result: The system does NOT create a duplicate node. It increments pathway_strength on the existing node using the formula: new_strength = current_strength + 1 * decay_factor, where decay_factor = log(1 + 1/days_since_last_access) ensures recent and frequently accessed pathways surface more strongly in RAG retrievals.
  • Contradiction detected: The old node is preserved (never deleted). A new artifact node is created and a [DEPRECATED_BY] edge is drawn from the old to the new, capturing the full evolution of thought. The old node remains in the audit trail but is filtered from the 'current truth' view.

Universal File Ingestion ('The Open Brain' Capability):
The ingestion pipeline accepts any natural language text document or note file. When parsing a document, the system creates a primary normalized Document instance node (storing URI, hash, and metadata) and generates multiple DocumentExtract child nodes containing semantically chunked text (split at paragraph and section boundaries). The Gated Consolidation Loop processes these extracts exactly as it would a chat stream, with precise provenance tracking (location_uri + line ranges) back to the source file.

5.4. Technical Schematics & Data Structures (Enabling Disclosure)
A. The Work-Artifact Graph Schema:
Driven by the Consolidation Loop, the schema is designed around actual knowledge-worker artifacts rather than generic facts. All core artifact nodes enforce the "Human-Agent Bridge" by requiring text_raw, embedding, embedding_model, and embedding_dim fields. Embeddings are explicitly optional on system audit/event nodes.

Nodes:

MainQuest, SideQuest

Decision, Constraint, Requirement, ActionItem

GlobalConstraint, GlobalPreference (Workspace-level artifacts to prevent duplication)

Document: Represents a physical file instance to prevent metadata bloat. Fields: document_id, location_uri, content_hash, last_modified_at, mime_type. Can be mapped via property to gist:Content or schema:DigitalDocument.

Message / DocumentExtract: Raw chat transcript or parsed document chunk. Fields include exact byte_start/byte_end or line ranges for pinpoint provenance.

MergeEvent: An audit node to track when pathways are combined (Embeddings OPTIONAL).

Relationships:

(SideQuest)-[BELONGS_TO]->(MainQuest)

(DocumentExtract)-[DERIVED_FROM]->(Document)

(Message | DocumentExtract)-[ESTABLISHED]->(Decision | Constraint)

(Decision)-[DEPRECATES]->(Decision) (Temporal Truth handling)

B. Deterministic Dual-Pointer Structure for Reversible Merges:To guarantee user trust, merges must be non-destructive. Instead of overwriting node text, the system utilizes a dual-pointer MergeEvent node containing exact state deltas:

MergeEvent Schema: {pre_pathway_strength, delta_pathway_strength, optional alias_added[], metadata_patch}
OriginalMessage_A -> [TRIGGERED] -> MergeEvent_1 <- [TRIGGERED] <- OriginalMessage_B
MergeEvent_1 -> [UPDATES_PATHWAY] -> Concept_Node
If a user flags a merge as incorrect via the UI, the MergeEvent is deleted, and the exact deltas are reversed, instantly and deterministically reverting the Concept_Node to its prior state and severing the incorrect provenance.

C. Dynamic Hybrid Ontology Routing (Prerequisite to Pattern Matching — Speed & Precision):
The Dynamic Hybrid Ontology Routing (Steps 2–3 of the Gated Consolidation Loop) is positioned BEFORE heuristic pattern matching by design. Knowing the ontological class and semantic shape of a concept before attempting artifact classification dramatically narrows the pattern-matching template space, enabling faster and more accurate confidence scoring with fewer false positives. This ordering is a key architectural decision and a component of the system's novelty.

Two-Stage Routing Mechanism (executed during Steps 2–3):
Stage 1 — High-Speed Classification (gist): The system maps extracted concepts using gist (Semantic Arts), a minimalist upper ontology with a tiny token footprint. The gist classification is resolved via the System 1/System 2 hybrid (embedding similarity first, LLM fallback for ambiguous cases). This produces a stable, coarse ontological type (e.g., gist:Restriction, gist:PlannedEvent) at minimal compute cost.

Stage 2 — Granular Extraction (schema.org Sub-graph): The gist class acts as a router. The system dynamically fetches ONLY the mapped, relevant sub-graph of the schema.org vocabulary — not the full dictionary. The LLM uses this tiny, targeted context window to extract detailed, standardized attributes. This guarantees high precision and interoperable standardization while completely avoiding the latency, cost, and hallucination risks of loading full ontologies.

Core gist → schema.org Routing Table (Proprietary IP):
  gist:Restriction      → schema:Demand (properties: name, description, eligibleRegion, validFrom)
  gist:PlannedEvent     → schema:Action (properties: name, actionStatus, agent, object, result)
  gist:PhysicalThing    → schema:Product (properties: name, brand, manufacturer, material, identifier)
  gist:Magnitude        → schema:QuantitativeValue (properties: value, unitCode, unitText, minValue)
  gist:Category         → schema:DefinedTerm (properties: name, termCode, inDefinedTermSet)
  gist:Agent            → schema:Person or schema:Organization (properties: name, identifier, memberOf)
  gist:Event            → schema:Event (properties: name, startDate, location, organizer)
This routing table is a core component of the proprietary enabling disclosure and will not be published prior to provisional patent filing.

5.5. Initial User & Adoption Target (Local Multi‑Assistant “SideQuests Brain”)

Initial User: The Inventor (DJ) — a developer routinely executing workflows across multiple AI coding and work assistants (Claude Code, Codex, Gemini CLI) on single, long-running projects.

Core Goal: A single, isolated local “SideQuests Brain” that all assistants can read from and write to concurrently, ensuring constraints and decisions persist across diverse AI tools without manual re-explanation.

A. Local Deployment Architecture (Phase 0 — Standalone Brain Daemon):
Phase 0 builds the Brain Daemon as a fully standalone Python service — not as a fork of any existing agent framework. This decision was made to establish a clean, IP-unencumbered foundation and to prove the Gated Consolidation Loop independently before integrating with third-party orchestration frameworks. Integration with agent frameworks (including OpenClaw) is deferred to a later phase.

Because Kùzu is an embedded DB, it cannot be safely opened concurrently from multiple processes in READ_WRITE mode. The deployment architecture is segmented to solve this while strictly adhering to the 'no TCP/HTTP listening ports' security mandate:

SideQuests Brain Daemon: A single background Python process that owns the Kùzu database in READ_WRITE mode, runs the full Gated Consolidation Loop, serves the Memory Control Panel web UI (bound strictly to 127.0.0.1), and exposes a secure local IPC API via Unix domain socket (macOS/Linux) or named pipe (Windows).

Per-Client MCP STDIO Adapters: Each AI assistant (Claude Code, Codex, Gemini CLI) spawns its own lightweight STDIO MCP server process. This adapter acts purely as a thin proxy, translating MCP JSON-RPC messages over the local IPC socket to the Brain Daemon. Phase 0 implements adapters for Claude Code and Codex. Additional adapters are added in Phase 1.

LLM Provider Configuration: The Brain Daemon uses a configurable LLM provider abstraction defined in sidequests.toml. The default is Ollama (local, no data leaves the machine). Users may optionally configure cloud providers (OpenAI, Anthropic, Google) by supplying an API key via environment variable. All LLM calls use an OpenAI-SDK-compatible interface so Ollama and cloud providers share the same code path with only base_url and api_key differing. This is a deliberate design choice to maximize portability and allow users to bring their own preferred model.

B. Cross-Assistant Integration (Seamless Continuity):To ensure seamless hand-offs between agents, the framework utilizes deterministic identifiers:

MainQuest Anchoring: The MainQuest ID is generated deterministically by default (e.g., a hash of the project repo root path + current git branch). This automatically aligns all local CLI tools to the exact same conversational context.

Shared Tool Surface: All adapters expose the exact same read/write toolset (ingest_message, upsert_artifacts, apply_merge, current_truth, diff_since, get_open_loops).

C. Local Acceptance Criteria:The system is successfully reduced to practice when the following cross-tool and data-fidelity checks pass:

Multi-Agent State Share: A Decision established via Claude Code is immediately visible and respected by a subsequent prompt in Codex CLI.

Temporal Deprecation Flow: Deprecating a Constraint in Codex instantly updates the diff_since view when queried by Gemini CLI.

Deterministic Rollback: Rolling back a MergeEvent via the UI immediately updates the "current truth" retrieval for all connected assistants.

The Bridge Test: Create a constraint from a chat message. The UI successfully displays the raw text and provenance, while retrieval uses embedding similarity to accurately surface it via a paraphrased query.

The Open Brain Test: Ingest a local markdown document (e.g., an IFS coaching framework). The system creates a normalized Document node and multiple DocumentExtracts. A Constraint pulled from that doc appears in the current_truth retrieval and exports with exact location_uri and line ranges.

The Cross-Project Analogical Test: Start a brand new MainQuest (e.g., "Move demo to AWS"). The system successfully surfaces and applies a Constraint or Decision (e.g., "Use IAM roles, not static keys") established in a distinct, separate MainQuest completed 3 months prior, proving cross-context experience transfer.

D. Adoption Path:
Phase 0: Standalone local Brain Daemon with direct MCP STDIO adapters for Claude Code and Codex. Proves the Gated Consolidation Loop independently. Local-first, fully offline-capable.
Phase 1: Publish standalone MCP STDIO adapters for additional ecosystem tools (Gemini CLI). OpenClaw engine swap (forking the framework and replacing its memory layer with the Brain Daemon).
Phase 2: Future consideration of remote/hosted enterprise variants only after filing IP and proving local security paradigms at scale.

Phase 0: Local-first, open-source engine swap focusing on personal developer velocity and secure defaults.

Phase 1: Publish standalone MCP STDIO adapters for popular ecosystem tools (Claude Code, Codex, Gemini CLI).

Phase 2: Future consideration of remote/hosted enterprise variants only after filing IP and proving local security paradigms.

E. Out-of-Band Behavioral Integrity Monitoring (Named IP Claim):
The Brain Daemon operates as a separate process from any LLM session. It receives conversation content via notify_turn (fire-and-forget) and processes it through the Gated Consolidation Loop independently.

Security properties of this architecture:
1. Architectural isolation: The Brain Daemon cannot be prompt-injected through the LLM's context window — it is a different OS process running its own logic. Malicious content injected into the LLM's context has no execution path to alter the Brain's processing rules or its stored GlobalConstraints.
2. GlobalConstraints as policy baseline: The decay rate of 0.999/day means security-class constraints are effectively permanent (~2 years to half-strength), providing a stable, long-lived policy baseline that survives across projects, sessions, and model upgrades.
3. Contradiction sense fires automatically: When notify_turn content conflicts with a high-confidence GlobalConstraint, the Gated Consolidation Loop Step 4 Contradiction sense fires, flagging the content without requiring any explicit security rules or a separate monitoring system.

Scope (important for patent claim precision):
• Conversation-layer only — detects constraint override language and goal hijacking attempts in conversation content.
• Does NOT detect OS-level actions (filesystem writes, network calls, subprocess execution).
• Detects: prompt injection attempts that try to override constraints, goal hijacking ("ignore previous instructions"), and constraint violation language.

Distinction from Cocktail Party Effect (important for claim separation):
The Cocktail Party Effect is the selective attention mechanism for memory formation — it fires on decision language, plan language, and entity mentions, forming the positive signal that writes to the graph. Out-of-Band Behavioral Integrity Monitoring applies the same Step 4 confidence gate to a negative signal — content that contradicts established policy. Both use the same architectural mechanism (the Contradiction sense in Step 4 of the Gated Consolidation Loop), but the Cocktail Party Effect is about knowledge acquisition and the Behavioral Integrity Monitor is about policy enforcement. These are distinct claims.

5.6. Evaluation & Proof of Efficacy (Internal Benchmark):
To definitively prove the value of the Gated Consolidation Loop against competitors, the system will be evaluated against a brutal internal benchmark.

Dataset: 50 simulated "weeks-long" multi-session project transcripts containing natural topic drift, changing constraints, and side tangents. Defined annotation rules clearly map what constitutes a Decision vs. a Constraint.

Baselines for Comparison:

Plain Vector-Write (e.g., standard Postgres/pgvector app).

Baseline MCP Server-Memory (Basic Knowledge Graph).

Temporal-KG Baseline (e.g., Zep).

Target Trust & Performance Metrics:

Harmful Merge Rate: Target < 2% (False merges that alter the core meaning of a constraint).

False Deprecation Rate: Target < 2% (Nodes erroneously marked as deprecated).

Constraint Recall Accuracy: Improves recall by >30% over standard vector-write in late-stage queries by filtering [DEPRECATED_BY] edges.

Correction Speed: Cuts time-to-correct-memory to <10 seconds via the deterministic dual-pointer reversible merge UI.

5.7. Novelty & Non-Obviousness:
While universal memory layers exist, they focus on unstructured vector retrieval, and baseline MCP KG servers simply map entities. Side Quests is novel specifically because of its Gated Consolidation Loop and the specific cognitive science principles it implements:

1. Kahneman Dual-Process Architecture (System 1 / System 2): The Step 2 gist classifier explicitly implements Kahneman's 'Thinking Fast and Slow' — a fast, automatic System 1 path (embedding cosine similarity) handles high-confidence cases at sub-millisecond latency, while a slow, deliberate System 2 path (LLM call) activates only for genuinely ambiguous inputs. This is not a generic optimization; it is a deliberate biomimetic design choice that mirrors how human cognition allocates attention.

2. Ontology-First Pattern Matching: By routing through gist and schema.org BEFORE applying heuristic pattern matching, the system uses ontological context to constrain the pattern-matching template space — the same way a human expert narrows their classification heuristics once they recognize the general category of what they are looking at.

3. Representativeness Heuristic (Pattern Matching): The artifact classification step explicitly models the Representativeness Heuristic — evaluating how well a concept matches the prototype of an artifact type rather than applying rigid rules.

4. Availability Heuristic (Dual-Scope Retrieval): The candidate retrieval step models the Availability Heuristic — surfacing what the system has 'seen before' via branch-scoped and global-scoped vector similarity, mimicking how humans recall relevant prior experiences.

5. Gated Consolidation Loop mechanisms: Tiered confidence gating, strict LLM contradiction guardrails, deterministic dual-pointer reversible merges, and pathway_strength decay all contribute to a system that transforms passive memory into an active, self-correcting cognitive processor.

6. Cocktail Party Effect (Selective Attention for Memory Formation): The Brain Daemon passively receives all conversation turns via notify_turn. The Step 4 confidence gate acts as a selective attention filter — most conversation noise passes through unrecorded; only specific signal patterns (decision language, constraint language, entity mentions, contradictions to existing knowledge) cause the Brain to fire and write to the graph. This is biomimetically modeled on the cocktail party effect, where the human auditory system selectively attends to salient signals (one's own name, emotional language) from a background of undifferentiated noise.

7. Out-of-Band Behavioral Integrity Monitoring via Contradiction Detection:
An AI memory system operating as a separate process from the LLM session, where high-confidence policy constraints (GlobalConstraint nodes with pathway_strength decay rate ≥ 0.999/day) serve as a persistent security baseline, and the Contradiction sense (Step 4, Gated Consolidation Loop) automatically flags conversational content that conflicts with established constraints, providing prompt injection detection and goal hijacking detection without requiring explicit security rules or a separate monitoring system. The architectural separation (Brain Daemon ≠ LLM process) is itself the security property: malicious content injected into the LLM's context window has no execution path to alter the Brain's logic, stored constraints, or processing rules.

The explicit Quest-oriented UX and Constraint Ledger serve as the highly marketable structural outputs of this proprietary method.

## 6. Diagrams and Flowcharts

System Architecture Diagram

User Flow Diagram (Branch, Explore, Merge, Deprecate, Export Decision Log)

MCP Ingestion Pipeline Flowchart (Detailing the Gated Consolidation Loop)

## 7. Prior Art

Direct Competitors: * Zep, Mem0, Letta: These platforms provide universal, cross-platform memory layers, and Zep specifically utilizes temporal knowledge graphs. MCP Baseline KG Server: Official implementation of basic graph memory via MCP.

Differentiation: Side Quests improves upon these by shifting the "inventive step" away from the mere existence of a graph, and onto the Gated Consolidation Loop (tiered gating, contradiction guardrails, ontology routing, and deterministic reversible merges). This method guarantees high-trust, audited memory structures specifically tuned for a Task-Oriented Narrative Structure (Main Quest/Side Quest paradigm leading to a Constraint Ledger).

Indirect Competitors:

Standard AI Chatbots (ChatGPT, Gemini, Claude): Linear single-thread conversation model.

Autonomous Agents (e.g., OpenClaw): Rely on flat markdown file memory causing "compaction."

## 8. Reduction to Practice Plan

Phase 0: Standalone Brain Daemon & Direct MCP Adapter Prototype
Build the single local Brain Daemon utilizing Kùzu as an embedded graph/vector DB. The daemon exposes a Unix domain socket IPC interface accessed by thin STDIO MCP adapters for Claude Code and Codex. Phase 0 does NOT fork or modify OpenClaw; the Gated Consolidation Loop is proven independently first. The Memory Control Panel is a local FastAPI web app bound strictly to 127.0.0.1. Build milestones:
M1: Kùzu schema + config + IPC daemon skeleton + LLM provider abstraction
M2: ingest_message + current_truth tools (basic vector write/read, no Loop)
M3: Gated Consolidation Loop Steps 1–4 (NER, gist hybrid, schema.org routing, pattern matching)
M4: Loop Steps 5–7 (dual-scope retrieval, contradiction arbitration, pathway update + MergeEvent)
M5: Quest Lifecycle (git-anchor MainQuest, manual SideQuest branching, RAG read flow)
M6: Open Brain document ingestion pipeline
M7: Memory Control Panel web UI
M8: Codex adapter + Cross-Quest Analogical Reasoning

Build the single local Brain Daemon utilizing Kùzu as an embedded graph/vector DB, accessed via thin local IPC MCP adapters by OpenClaw, Claude Code, and other local CLI tools.

Strict Security Mandate & Local Sandbox Hardening: Due to active malware vulnerabilities in the OpenClaw skill ecosystem (and specifically web-based localhost hijacking), and to guarantee the absolute safety of private local files (e.g., family documents, coaching files), the Phase 0 build will enforce these non-negotiable hard limits:

STDIO Transport Mandatory: The MCP Server/Agent integration must use stdio transport. No listening TCP/HTTP ports are permitted, neutralizing WebSocket/localhost hijacking vectors. Inter-process communication between adapters and the Daemon uses secure Unix domain sockets/named pipes.

Chroot & Path Canonicalization: Read/Write operations are strictly confined to the immediate openclaw-sidequests project directory. All paths must be canonicalized (e.g., realpath).

Symlink & Escape Blocking: Strict denial of .. escapes and symlink traversal. Only allowlisted file extensions (e.g., .db, .log) may be written.

No Third-Party Skills: All community extensions and external package loading mechanisms are hard-disabled. Contradiction arbitration must be handled by a rule-based engine or a strictly sandboxed local model.

## Appendix A: Intellectual Property (IP) Strategy Roadmap

(Ongoing - Documenting conception, preparing for Provisional Patent Application before open-source release). To protect enabling disclosure, technical schemas and algorithmic loop details within this document will not be published to open-source repositories prior to filing.
