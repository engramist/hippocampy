# SideQuests Brain — Preliminary Prior Art Search

Prepared: March 24, 2026  
Prepared for: Don J. Shelton  
Purpose: Document completion of Step 3 in the PPA filing guide by recording a preliminary prior-art search, the sources reviewed, the search strings used, and the current differentiation analysis.

---

## Scope and Caveat

This is a **preliminary prior-art search memo**, not a formal patentability opinion. The goal is to identify the closest public disclosures before filing the provisional application so the written description can clearly distinguish SideQuests from existing agent-memory systems, temporal knowledge graphs, and benchmark literature.

This search covered:

- Public product websites
- Open-source repositories and technical documentation
- Academic papers on agent memory and long-horizon evaluation
- MCP protocol documentation as ecosystem baseline

This memo does **not** replace a full interactive search in USPTO Patent Public Search, Google Patents, Espacenet, or a professional patent search report. It is sufficient as a disciplined pre-filing search record and a drafting aid for the provisional disclosure.

---

## Search Strategy Used

### Core problem-space queries

These are the exact search themes used from the filing guide and expanded during this search:

- "knowledge graph AI memory"
- "LLM memory persistence"
- "episodic memory neural network"
- "conversation context graph"
- "agent memory graph"
- "temporal knowledge graph agent memory"
- "persistent agent memory"
- "stateful agents memory"
- "AI memory layer"
- "context graph AI agents"
- "long-horizon memory agent benchmark"
- "multi-session agent memory benchmark"

### Source classes searched

1. USPTO guidance and search-planning materials
2. Public technical disclosures from direct competitors
3. Academic literature describing agent-memory systems or evaluation benchmarks
4. Protocol-level ecosystem materials relevant to MCP-based memory infrastructure

---

## USPTO Search Resources Consulted

These were reviewed to ground the search process:

1. USPTO Patent Process Overview  
   https://www.uspto.gov/patents/basics/patent-process-overview#step1

2. USPTO Basics of Prior Art Searching (PDF)  
   https://www.uspto.gov/sites/default/files/documents/Basics-of-Prior-Art-Searching.pdf

3. USPTO preliminary patent search tutorial  
   https://www.uspto.gov/video/cbt/prelim-patent-search/index.html

4. Patent Public Search landing page  
   https://ppubs.uspto.gov/pubwebapp/static/pages/landing.html

These sources confirm that prior art includes both patent literature and non-patent public disclosures such as product sites, papers, documentation, open-source repositories, and public demos.

---

## Closest Public Disclosures Found

### 1. Zep / Graphiti

Source set:

- Product site: https://www.getzep.com/
- Open-source engine: https://github.com/getzep/graphiti
- Paper: "Zep: A Temporal Knowledge Graph Architecture for Agent Memory"  
  https://arxiv.org/abs/2501.13956

What it discloses:

- A memory layer service for AI agents
- A temporal knowledge graph / context graph
- Dynamic synthesis of conversational and structured business data
- Historical fact invalidation rather than simple overwrite
- Hybrid retrieval over graph structure and embeddings
- MCP server support through Graphiti

Why it is important:

This is the **closest commercial / technical baseline** found. It shows that temporal knowledge graphs for agent memory were publicly disclosed before filing.

Why SideQuests is still distinct:

- Zep / Graphiti focuses on **context graph construction and retrieval**, not a biomimetic consolidation pipeline
- No disclosed **9-step Gated Consolidation Loop** with the specific ordered stages used by SideQuests
- No disclosed **Cocktail Party selective-attention gate** with named cognitive senses and confidence thresholds
- No disclosed **Semantic Quest Routing / Hippocampus mechanism** for attaching sessions to quests via multi-signal fusion and prediction-error reconsolidation
- No disclosed **Working Memory Awareness** via Session-to-Artifact [LOADED] state and smart reinjection policy
- No disclosed **Hebbian dual-edge promotion model** in the specific CO_OCCURS_WITH -> named semantic edge form described in SideQuests

Risk level:

- High relevance prior art
- Must be cited and distinguished clearly in the notebook and later nonprovisional

---

### 2. Mem0

Source set:

- Product site: https://mem0.ai/
- Documentation: https://docs.mem0.ai/

What it discloses:

- A universal memory layer for LLM applications
- Memory compression to reduce token usage
- Built-in observability over memory items
- Timestamped, versioned, exportable memory
- Persistent memory across sessions and domains

Why it is important:

Mem0 is a direct market-facing prior art reference for persistent memory and token-efficiency claims.

Why SideQuests is still distinct:

- Mem0 markets a **memory layer**, not a graph-native biomimetic cognition engine
- No disclosed **ontology-routed, shape-first semantic pipeline**
- No disclosed **temporal contradiction arbitration with DEPRECATED_BY + MergeEvent rollback lineage** in the SideQuests form
- No disclosed **quest-structured anchoring model** with MainQuest / SideQuest separation
- No disclosed **long-horizon working-memory state model** based on explicit [LOADED] edges and reinjection policies

Risk level:

- High relevance commercial prior art
- Important for distinguishing "memory layer" from "active cognitive consolidation engine"

---

### 3. Letta

Source set:

- Product site: https://www.letta.com/
- Docs: https://docs.letta.com/

What it discloses:

- Stateful / memory-first AI agents
- Persistent agents instead of stateless sessions
- Background memory subagents that improve prompts, context, and skills over time
- Portable memory across devices and models

Why it is important:

Letta is another strong baseline for persistent agent memory and stateful agent operation.

Why SideQuests is still distinct:

- Letta emphasizes **stateful personalized agents**, not a graph-native consolidation architecture with explicit temporal truth and gating
- No disclosed **quest-routing memory model**
- No disclosed **dual-process classification (System 1 / System 2)** mapped to gist / schema.org routing
- No disclosed **synaptic pruning + archive / resurrection** mechanics with pathway strength and decay configuration
- No disclosed **out-of-band anomaly detection** claim based on passive interception and constraint contradiction sensing

Risk level:

- Moderate to high relevance product prior art

---

### 4. MCP protocol baseline

Source:

- https://modelcontextprotocol.io/

What it discloses:

- MCP as an open standard for connecting AI applications to tools, data sources, and workflows
- Broad ecosystem support across clients including Claude, ChatGPT, VS Code, Cursor, and others

Why it is important:

MCP itself is **not** the invention. It is infrastructure prior art that makes clear the novelty cannot rest on "using MCP for memory."

Why SideQuests is still distinct:

- The inventive step is **not MCP transport**
- SideQuests uses MCP as a transport wrapper around a separate brain daemon and consolidation engine
- The novelty lies in the **cognitive processing model**, graph schema, quest routing, contradiction handling, pruning, and audit lineage

Risk level:

- Background ecosystem prior art
- Should be framed as plumbing, not as the source of novelty

---

### 5. MemOS: A Memory OS for AI System

Source:

- https://arxiv.org/abs/2507.03724

What it discloses:

- Memory as a manageable system resource for LLM-based systems
- Memory representations spanning plaintext, activation-based, and parameter-level memory
- MemCubes with provenance and versioning
- Schedules and evolves heterogeneous memory across temporal scales

Why it is important:

This is a strong conceptual prior art reference for explicit memory-management layers in AI systems.

Why SideQuests is still distinct:

- MemOS is a **memory operating system** abstraction, not a graph-native consolidation loop for AI project and conversation structure
- No disclosed **MainQuest / SideQuest quest topology**
- No disclosed **Cocktail Party effect gating**
- No disclosed **DEPRECATED_BY / MergeEvent reversible contradiction lineage**
- No disclosed **Hippocampus routing with prediction-error rerouting**

Risk level:

- Moderate relevance research prior art

---

### 6. MemoryArena: Benchmarking Agent Memory in Interdependent Multi-Session Agentic Tasks

Source:

- https://arxiv.org/abs/2602.16313

What it discloses:

- A benchmark specifically targeting memory in interdependent, multi-session agent tasks
- Evaluation framing relevant to long-horizon agent behavior

Why it is important:

This is not product prior art for the SideQuests architecture itself, but it is highly relevant non-patent literature showing the field had already identified **multi-session agent memory** as a real and important problem.

Why SideQuests is still distinct:

- It is a **benchmark / evaluation artifact**, not a disclosed implementation of the claimed mechanisms
- It supports the problem statement but does not appear to disclose the SideQuests solution stack

Risk level:

- Supporting academic prior art
- Useful to show the problem was recognized, while the proposed solution remains distinct

---

### 7. AMA-Bench: Evaluating Long-Horizon Memory for Agentic Applications

Source:

- https://arxiv.org/abs/2602.22769

What it discloses:

- A benchmark centered on long-horizon memory for agentic applications
- Evaluation emphasis on retention across longer tasks and broader agent workflows

Why it is important:

Like MemoryArena, this shows the problem area was active and recognized by the research community.

Why SideQuests is still distinct:

- It is an **evaluation benchmark**, not the claimed technical architecture
- It does not, on its face, disclose the specific SideQuests mechanisms: quest routing, biomimetic selective attention, reversible lineage, or Hebbian promotion

Risk level:

- Supporting academic prior art

---

## Preliminary Differentiation Themes to Preserve in the PPA

The current search suggests the strongest drafting position is **not** to claim "AI memory" broadly. That space is crowded. Instead, the PPA should keep emphasizing the specific combination below.

### A. The 9-step Gated Consolidation Loop

This remains the strongest differentiator because the closest systems found focus on storage, retrieval, or graph construction, not the exact ordered biomimetic consolidation process.

### B. Cocktail Party selective attention

The strongest novelty theme here is not merely filtering but the use of named cognitive senses plus confidence gating to determine whether content becomes noise, tentative memory, or confirmed structural memory.

### C. Semantic Quest Routing / Hippocampus mechanism

No searched source disclosed the MainQuest / SideQuest routing structure with multi-signal fusion and prediction-error-driven rerouting.

### D. Working Memory Awareness

Explicit Session-to-Artifact [LOADED] tracking plus smart reinjection appears differentiable from general persistent-memory claims.

### E. Temporal truth with deterministic rollback

The DEPRECATED_BY + MergeEvent lineage model should be emphasized. Temporal invalidation exists in Zep / Graphiti, but the exact reversible merge-event audit mechanism remains a key distinction.

### F. Synaptic pruning + Hebbian promotion

The configurable decay / archive / resurrection pathway combined with CO_OCCURS_WITH -> named edge promotion is still a strong candidate novelty cluster.

---

## Search Results Summary Table

| Reference | Type | Relevance | Core overlap | Main differentiator for SideQuests |
|---|---|---:|---|---|
| Zep / Graphiti | Product + OSS + paper | Very high | Temporal knowledge graph, evolving facts, hybrid retrieval | No 9-step biomimetic consolidation loop; no quest routing; no working-memory [LOADED] model |
| Mem0 | Product + docs | High | Persistent memory, token reduction, observability | No graph-native cognitive pipeline; no reversible merge lineage; no quest model |
| Letta | Product + docs | High | Stateful agents, persistent memory, background improvement | No graph-native consolidation architecture; no selective attention / pruning / rollback stack |
| MCP | Protocol standard | Medium | Tool/data interoperability for AI | Infrastructure only, not memory invention |
| MemOS | Research paper | Medium | Explicit memory management layer for AI systems | Different abstraction layer; no SideQuests-specific graph and routing model |
| MemoryArena | Benchmark paper | Medium | Multi-session agent-memory problem framing | Benchmark only, not the claimed system |
| AMA-Bench | Benchmark paper | Medium | Long-horizon agent-memory problem framing | Benchmark only, not the claimed system |

---

## Recommended Claim Drafting Guardrails

Based on the current search, avoid positioning the invention as:

- "an AI memory system"
- "a persistent memory layer for LLMs"
- "a temporal knowledge graph for agents"
- "MCP-based agent memory"

Those themes are already crowded.

Instead, keep centering the provisional disclosure on:

1. A **computer-implemented method** with a specific ordered sequence of consolidation steps
2. A **quest-structured graph model** that preserves project objective hierarchy
3. A **confidence-gated cognitive attention model** for deciding what enters structural memory
4. A **temporal truth / rollback lineage model**
5. A **working-memory state model** for controlling reinjection and token bloat
6. A **use-strengthening / inactivity-weakening model** with archive and resurrection behavior

---

## Recommended Next Search Passes Before Nonprovisional Filing

This memo is enough for the provisional filing, but before a later nonprovisional filing, do a deeper structured patent search in these channels:

1. USPTO Patent Public Search
2. Google Patents
3. Espacenet / WIPO Patentscope
4. Semantic Scholar / Google Scholar for additional agent-memory literature

### Suggested patent-search strings for the later pass

- "temporal knowledge graph agent memory"
- "persistent conversational memory graph"
- "AI agent memory invalidation"
- "context graph agent retrieval"
- "memory layer for large language model"
- "long-term memory for conversational agent"
- "episodic memory graph artificial intelligence"
- "session routing artificial intelligence graph"
- "contradiction handling knowledge graph memory"

---

## Filing-Use Conclusion

The current prior-art search supports the following drafting position:

- The general field of AI memory, stateful agents, temporal knowledge graphs, and MCP-based integrations is clearly occupied.
- The strongest defensible novelty for SideQuests is the **specific biomimetic consolidation architecture and its coupled graph/state mechanisms**, not generic persistent memory.
- The provisional application should therefore keep using the notebook's strongest language around the **Gated Consolidation Loop**, **Cocktail Party Effect**, **Semantic Quest Routing**, **Working Memory Awareness**, **Synaptic Pruning**, **Hebbian Long-Term Potentiation**, and **deterministic reversible lineage**.

---

## Sources Reviewed

- https://www.uspto.gov/patents/basics/patent-process-overview#step1
- https://www.uspto.gov/sites/default/files/documents/Basics-of-Prior-Art-Searching.pdf
- https://www.uspto.gov/video/cbt/prelim-patent-search/index.html
- https://ppubs.uspto.gov/pubwebapp/static/pages/landing.html
- https://www.getzep.com/
- https://github.com/getzep/graphiti
- https://arxiv.org/abs/2501.13956
- https://mem0.ai/
- https://docs.mem0.ai/
- https://www.letta.com/
- https://docs.letta.com/
- https://modelcontextprotocol.io/
- https://arxiv.org/abs/2507.03724
- https://arxiv.org/abs/2602.16313
- https://arxiv.org/abs/2602.22769