# Side Quests Patent Figures (Draft Packet)

This document is a draft figure packet for provisional filing preparation.

Usage:
- Export each figure section below as a separate page image or PDF page.
- Keep labels exactly as FIG. 1 through FIG. 6.
- Preserve caption text consistency with the notebook specification.

## FIG. 1 - System Architecture (Decoupled Brain Model)

Caption:
FIG. 1 illustrates the modular, decoupled system topology comprising per-client adapters, two separate message capture paths, a local Brain Daemon, graph/vector persistence, and a user-facing memory control panel.

```mermaid
flowchart LR
  subgraph Capture
    H[Hook: UserPromptSubmit] -->|user turns, zero LLM| BD
    N[notify_turn MCP call] -->|assistant turns| BD
  end
  subgraph Client
    A[AI Client Adapter] --> H
    A --> N
    A --> T[MCP Tool Surface]
  end
  T --> BD[Brain Daemon]
  BD --> D[(Graph + Vector Store)]
  BD --> S[Background Sweep]
  BD --> P[Memory Control Panel 127.0.0.1]
```

## FIG. 2 - 9-Step Gated Consolidation Loop

Caption:
FIG. 2 illustrates the ordered 9-step consolidation method from incoming turn or document input through concept extraction, dual-process classification, sub-graph routing, relation extraction, confidence gating, retrieval, arbitration, and pathway update with auditable lineage.

```mermaid
flowchart TD
  S0[Input Turn or Document Chunk] --> S1[1 NER/Zoning]
  S1 --> S1B[1b Relation Fast Path]
  S1B --> S2[2 Dual Process gist Classification]
  S2 --> S3[3 schema.org Subgraph Routing]
  S3 --> S3B[3b Semantic Relation Extraction]
  S3B --> S4[4 Confidence Gate]
  S4 -->|<60| N[Noise Log]
  S4 -->|60-90| T[Tentative confidence_low]
  S4 -->|>90| C1[Confirmed Artifact]
  T --> S5[5 Dual Scope Retrieval]
  C1 --> S5
  S5 --> S6[6 Contradiction Arbitration]
  S6 --> S7[7 Pathway Update + Lineage]
```

## FIG. 3 - Cocktail Party Effect: Selective Attention and Confidence Gating

Caption:
FIG. 3 illustrates the passive selective attention mechanism (the Cocktail Party Effect) in which specific cognitive senses fire on inbound content, confidence scoring gates the result into noise, tentative, or confirmed paths, and confirmed artifacts enter structural memory while tentative artifacts remain eligible for re-scoring.

```mermaid
flowchart TD
  I[Inbound Turn - Always Listening] --> SE[Sense Evaluation]
  SE --> DS{Decision Sense?}
  SE --> CS{Constraint Sense?}
  SE --> PS{Plan Sense?}
  SE --> ES{Entity Mention Sense?}
  SE --> XS{Contradiction Sense?}
  SE --> AS{Anomaly Sense?}
  DS & CS & PS & ES & XS & AS --> G1{Confidence Score}
  G1 -->|<60| G2[Noise Path: Vector Log Only]
  G1 -->|60-90| G3[Tentative: confidence_low true]
  G1 -->|>90| G4[Confirmed: Full Structural Write]
  G3 --> G5[Eligible for Background Re-Scoring]
  G4 --> G6[Eligible for Retrieval + Pathway Strengthening]
  AS -->|GlobalConstraint Violated| AL[Anomaly Alert]
```

## FIG. 4 - Temporal Truth and Reversible Merge Lineage

Caption:
FIG. 4 illustrates temporal truth handling in which additive evidence strengthens existing artifact pathway_strength, contradictory evidence preserves prior state under a DEPRECATED_BY edge, and a MergeEvent audit record enables deterministic rollback.

```mermaid
flowchart LR
  T0[Existing Artifact Node] --> T1{New Evidence Type}
  T1 -->|Additive| T2[Increment pathway_strength]
  T1 -->|Contradiction| T3[Create New Artifact Node]
  T3 -->|DEPRECATED_BY| T0
  T3 --> T4[MergeEvent Audit Record]
  T4 --> T5[State Delta Stored]
  T5 --> T6[Deterministic Rollback: Delete MergeEvent]
  T1 -->|Uncertain| T7[Soft-Lock: confidence_low true]
  T7 --> T8[Await Arbitration or User Review]
```

## FIG. 5 - Working Memory Awareness, Smart Deduplication, and Session Handoff

Caption:
FIG. 5 illustrates working-memory state tracking via Session-to-Artifact [LOADED] edges, token burden estimation, smart deduplication with relevance demotion, refresher reinjection, and Session Handoff Intelligence that seeds a new session with the prior session's top loaded artifacts.

```mermaid
flowchart TD
  W0[current_truth Retrieval] --> W1[Inject Artifact into Active Session]
  W1 --> W2[Session --LOADED--> Artifact Edge]
  W2 --> W3[Record token_estimate + injected_at]
  W3 --> W4[Subsequent Retrieval]
  W4 --> W5{Already LOADED?}
  W5 -->|Yes| W6[Demote: relevance x 0.3]
  W5 -->|No| W7[Rank Normally]
  W6 --> W8{High-Salience Refresher?}
  W8 -->|Yes| W9[Allow Reinjection]
  W8 -->|No| W10[Suppress Redundant Injection]
  W3 --> W11{New Session on Same Quest?}
  W11 -->|Yes| W12[Session Handoff Intelligence]
  W12 --> W13[Load Top 5 LOADED from Prior Session]
  W13 --> W14[Inject into New Session Context]
```

## FIG. 6 - Semantic Quest Routing (Hippocampus Mechanism)

Caption:
FIG. 6 illustrates the multi-signal routing fusion method that dynamically associates a new session thread with an existing quest, escalates to LLM disambiguation on ambiguity, and triggers prediction-error-driven memory reconsolidation using Long-Term Depression (LTD) when an incorrect attachment is detected.

```mermaid
flowchart TD
  R0[New Session Thread] --> R1[Extract Initial Signals]
  R1 --> R1A[Semantic Intent Embedding]
  R1 --> R1B[Entity Overlap via 1-hop]
  R1 --> R1C[Workspace / OS Context]
  R1A & R1B & R1C --> R2[Compute Fused Routing Confidence]
  R2 -->|>0.85 High| R3[Attach to Existing MainQuest]
  R2 -->|0.60-0.85 Ambiguous| R4[Escalate to LLM Disambiguation]
  R2 -->|<0.60 Low| R5[Create New MainQuest]
  R3 --> R6[Monitor Prediction Error]
  R4 --> R6
  R5 --> R6
  R6 -->|Detected| R7[Detach Thread]
  R7 --> R8[Weaken False Link via LTD]
  R8 --> R9[Draw REROUTED_FROM Audit Edge]
  R9 --> R10[Re-anchor to Correct Quest]
```

## FIG. 7 - Synaptic Pruning, Hebbian Learning, and Long-Term Potentiation

Caption:
FIG. 7 illustrates the use-based memory strengthening and time-decay pruning model, in which pathway_strength increases on access and decays exponentially during inactivity, archived nodes are resurrected by embedding similarity above a threshold, and implicit CO_OCCURS_WITH edges are promoted to named semantic edges via Hebbian Long-Term Potentiation.

```mermaid
flowchart TD
  A0[Artifact Node] --> A1{Accessed?}
  A1 -->|Yes| A2[Strengthen: strength += log-based delta]
  A1 -->|No| A3[Decay: strength x= decay_rate ^ days_inactive]
  A3 --> A4{Below archive_threshold?}
  A4 -->|Yes| A5[Archive: archived = true]
  A4 -->|No| A6[Stay Active]
  A5 --> A7{Similarity to Active Node > resurrection_threshold?}
  A7 -->|Yes| A8[Resurrect: archived = false, strength reset]
  A7 -->|No| A9[Remain Archived]
  B0[Concept A co-occurs with Concept B] --> B1[CO_OCCURS_WITH Edge: count++]
  B1 --> B2{count > co_occurrence_threshold?}
  B2 -->|Yes| B3[Promote to Named Semantic Edge]
  B3 --> B4[ENABLES / REQUIRES / CHOSEN_OVER etc]
  B4 --> B5[inferred_by: system or LLM or user]
  B2 -->|No| B6[Remain Implicit Hebbian Evidence]
```

## Export Checklist

1. One figure per output page.
2. Retain label format: FIG. X.
3. Keep captions synchronized with the Brief Description in the investor notebook Section 6.1.
4. Verify line-work readability in grayscale print.
5. Include FIG. 1 through FIG. 7 in the provisional filing appendix.
