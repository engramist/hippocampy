# Side Quests — Executive Summary & Strategic Roadmap

**Confidential — Patent Pending**
USPTO Provisional Application No. 64/017,066 | Filed March 25, 2026 | Priority Deadline: March 25, 2027

---

## What It Is

Side Quests is a **local-first AI memory server** that gives any LLM-based agent persistent, structured, long-term memory. It runs as a background daemon on the user's machine, connects to any MCP-compatible AI assistant (Claude, Codex, ChatGPT, Gemini), and builds a living knowledge graph from conversations — automatically, with zero manual tagging.

The core invention is the **Gated Consolidation Loop** — a 9-step processing pipeline modeled on human cognitive heuristics (Kahneman dual-process theory, Hebbian learning, synaptic pruning, the Cocktail Party Effect). It replaces brute-force RAG context windows with intelligent, selective memory consolidation into a graph-native database (Kùzu).

## The Problem

Every AI agent today is amnesiac. Each conversation starts from zero. The industry's answer — dump everything into a vector database or cram it into a massive context window — is expensive, lossy, and architecturally broken:

- **For solo developers and small teams:** orchestrating multiple AI agents (Claude for planning, Codex for implementation, ChatGPT for research) means re-explaining your entire architecture to each one, every session. Token costs compound. Decisions get forgotten. Constraints get violated. A study by Alibaba (SWE-CI benchmark) showed 75% of frontier models break previously working code during long-term maintenance because they lose track of prior constraints.

- **For creators and coaches:** professionals like a wellness coach building year-long content programs need ChatGPT to remember six months of brand voice, curriculum structure, and messaging frameworks. Instead, the agent suffers "context rot" — it loses the thread after a few sessions and starts generating generic content disconnected from the established program identity.

- **For autonomous agent loops:** the emerging paradigm of overnight research agents (à la Karpathy's auto-research) requires a "scientific ledger" — a durable record of what hypotheses were tested, what failed, and what constraints were established. Without it, agents regress and repeat failed experiments.

## How It Works

Side Quests listens passively to all connected AI sessions. The Gated Consolidation Loop processes each message through:

1. **NER/Zoning** — spaCy extracts entities and relations (zero LLM cost)
2. **Rapid Classification** — embedding similarity against ontological centroids; only escalates to LLM when uncertain (Kahneman System 1/2)
3. **Ontological Routing** — gist upper ontology → schema.org sub-graphs give each concept its semantic "shape" before downstream processing (Shape-First Principle)
4. **Selective Attention** — confidence gating filters noise. Most conversation passes through unrecorded. Only meaningful signal fires: decisions, constraints, plans, contradictions to existing knowledge (Cocktail Party Effect)
5. **Retrieval + Arbitration** — checks existing graph for matches and contradictions before storing
6. **Pathway Strengthening** — frequently accessed knowledge strengthens; unused knowledge decays and archives (Hebbian learning + synaptic pruning). Nothing is deleted.

The result: agents share a single persistent brain. A decision made in Claude is instantly available in Codex. A constraint established three months ago surfaces automatically when relevant — and only when relevant.

## Where We Are Today (March 2026)

**Working and verified:**
- Brain Daemon with 11 MCP tools, Unix socket IPC
- Gated Consolidation Loop (Steps 1–7) processing messages end-to-end
- Cross-agent memory sharing verified (Claude Code ↔ Gemini CLI, both reading/writing the same Kùzu graph)
- Claude Code adapter (full), Codex adapter (verified), ChatGPT Desktop SSE adapter (endpoint responding), Gemini CLI adapter (verified)
- 409 tests passing, guided installer (`sidequests install`)
- Hallucination defense (assistant turns capped below confirmation threshold)
- Proactive insight surfacing, hippocampus-based routing, working memory

**Known gaps:**
- Background sweep (time-decay, archival, resurrection) — designed, not yet coded
- PyPI package not yet published (wheel builds clean, `twine check` passes)
- ChatGPT Desktop requires manual connector step in the app UI
- No public documentation or README yet
- No longitudinal benchmark data yet

## Who It's For

**Phase 1 market (now):** Developers using MCP-compatible AI coding agents who are frustrated by context loss across sessions and agents. They're already looking for this — the "Memory Wall" is the #1 pain point in AI developer tooling discussions.

**Phase 2 market (6+ months):** Non-technical professionals (coaches, content creators, consultants) who use ChatGPT/Claude for ongoing work and need the AI to maintain continuity over weeks and months. Michelle Shelton's IFS coaching practice is the internal proof-of-concept for this market.

**Phase 3 market (12+ months):** Enterprise and autonomous agent platforms that need durable memory infrastructure for long-running agent deployments.

## Intellectual Property

**Patent-pending claims (PPA filed, priority date March 25, 2026):**
- Gated Consolidation Loop (9-step biomimetic pipeline)
- Shape-First Principle (ontological grounding before semantic work)
- Kahneman System 1/2 hybrid classifier
- Cocktail Party Effect selective attention gate
- gist → schema.org graph-native routing table
- Hebbian promotion (CO_OCCURS_WITH → named semantic edge)

The 12-month provisional period expires March 25, 2027. A non-provisional utility application must be filed by that date.

---

# Strategic Roadmap

## Phase 1: Stabilize & Dogfood (April–May 2026)

**Goal:** Make the product reliable enough for daily use by real humans.

| Task | Detail |
|------|--------|
| Implement background sweep | Time-decay, archival, resurrection — the pruning system that keeps the graph clean without manual intervention |
| Fix remaining data quality issues | Duplicate concept dedup, markdown leakage in NER, generic word filtering |
| Michelle pilot | Wire ChatGPT Desktop adapter for her IFS coaching workflow. Track what breaks, what's missing, what's confusing. This is real user testing, not a demo. |
| Daily dogfooding | Use Side Quests as primary memory across all DJ's coding agent sessions. Log every failure. |
| PyPI publish | `pip install sidequests-brain` works on Python 3.12/3.13 on macOS and Linux |
| Public README + basic docs | Honest README: what it does, how to install, what works, what doesn't |

**Exit criteria:** Two humans (DJ + Michelle) using it daily for 3+ weeks without data loss or session-breaking bugs.

## Phase 2: Harden & Open Source (June–August 2026)

**Goal:** Make it good enough that strangers can install and use it without hand-holding.

| Task | Detail |
|------|--------|
| GitHub public launch | Lift embargo. Clean commit history. MIT or Apache-2.0 license. |
| Community onboarding | README, CONTRIBUTING.md, issue templates. GitHub Discussions enabled. |
| Installer polish | Handle edge cases surfaced by Phase 1. Support more OS/Python combos. |
| Engine tuning | Adjust confidence thresholds, pruning rates, centroid quality based on Phase 1 telemetry |
| Memory Control Panel polish | The web UI graph visualization needs to be intuitive for non-developers (Michelle test) |
| Smithery listing | Publish to the MCP server directory for discoverability |

**Exit criteria:** 10+ external users have installed, used, and submitted at least one issue or piece of feedback.

## Phase 3: Benchmark & Measure (July–October 2026)

**Goal:** Generate rigorous, reproducible evidence that this approach works better than raw context windows.

| Task | Detail |
|------|--------|
| SWE-CI benchmark run | 71 consecutive codebase updates — Side Quests vs. baseline agent. Measure constraint violation rate, token spend, task success rate. |
| Autonomous research loop test | Hook Side Quests into an auto-research harness. Measure Hypothesis Regression Rate (how often the agent repeats a failed experiment). |
| LoCoBench / AMA-Bench adaptation | Multi-session interdependent tasks. Measure memory retention vs. basic vector RAG. |
| Token economics analysis | Quantify actual cost savings: tokens consumed with vs. without Side Quests across real multi-agent workflows. |
| Internal benchmark report | Published on GitHub as reproducible methodology + raw data |

**Exit criteria:** At minimum, quantified results on 2 of the 3 benchmark approaches showing measurable improvement over baseline.

## Phase 4: Publish & Establish Credibility (September 2026–March 2027)

**Goal:** Get the results in front of the people who matter — academics, practitioners, and the developer community.

| Task | Detail |
|------|--------|
| Whitepaper draft | Package benchmark results into a rigorous paper. Target audience: AI engineering practitioners + graph database researchers. |
| Journal/conference submission | Primary targets: IEEE Software, TMLR, Empirical Software Engineering (EMSE). Conference targets: ICSE, NeurIPS workshops. Note: expect 6–12 month review cycles — submit early. |
| Blog series | Technical deep-dives published on personal site / dev.to / medium. These are the accessible versions of the research for the developer audience. |
| LLM architectural bias study | The second research thread from the notebook (Idea 3). Can run in parallel — different methodology, complementary findings. |
| Conference talks / demos | Submit to local meetups, PyCon, or AI-focused virtual conferences. Live demo of cross-agent memory is compelling. |

**Exit criteria:** At least one paper submitted to a peer-reviewed venue. At least one public talk/demo delivered.

## Phase 5: Grow & Engage (October 2026–March 2027)

**Goal:** Build the community and visibility that creates strategic options.

| Task | Detail |
|------|--------|
| Developer outreach | Engage with creators documenting the Memory Wall problem (Nate B. Jones, Alex Finn, Igor Kudryk, Ray Fernando, OpenClaw community). Not "sponsorship" — genuine collaboration. Show them the tool, let them evaluate it honestly. |
| GitHub presence | Respond to issues, accept PRs, write release notes. Healthy open-source hygiene. |
| Integration partnerships | Work with MCP client teams (Anthropic, OpenAI) to ensure Side Quests is listed/recommended in their ecosystem docs. |
| Michelle's creator workflow showcase | If her use case is working well, document it as a case study. Non-technical users adopting AI memory is a powerful narrative. |
| Non-provisional patent prep | Engage patent attorney. Review PPA claims against actual implementation. File utility application before March 25, 2027 deadline. |

**Exit criteria:** Growing GitHub star count. Active issue tracker. At least 2 external contributors. Patent attorney engaged.

## Phase 6: Strategic Positioning (Q1–Q2 2027)

**Goal:** Be in a position to choose your path — not have it chosen for you.

With published benchmarks, a live open-source community, a filed utility patent, and real users, you have multiple credible options:

| Option | What it requires |
|--------|-----------------|
| **License the IP** | A tech company (Anthropic, Microsoft, Apple, OpenAI) wants to integrate biomimetic memory into their platform. You license the patent. Requires: proven results + filed utility patent. |
| **Acquisition** | A company acquires Side Quests (code + IP + you). Requires: demonstrated traction + strategic fit + willing buyer. This is an *outcome*, not a plan. |
| **Sustain as open-source + consulting** | Side Quests becomes the standard open-source MCP memory layer. You consult on enterprise deployments. Requires: community + credibility. |
| **SaaS / hosted version** | Hosted Side Quests for teams who don't want to run it locally. Requires: significant engineering investment beyond solo capacity. |

The point of this roadmap is to build toward **optionality**, not to bet everything on a single exit. Do the work. Prove it works. Let the results create the leverage.

---

## Key Dates

| Date | Event |
|------|-------|
| March 25, 2026 | PPA filed (64/017,066) — priority date established |
| April 2026 | Phase 1 begins — stabilization + dogfooding |
| June 2026 | Target: GitHub public launch |
| July 2026 | Benchmarking begins |
| September 2026 | Target: first paper submission |
| January 2027 | Engage patent attorney for non-provisional |
| **March 25, 2027** | **HARD DEADLINE: Non-provisional utility patent must be filed** |

---

*This document is a living plan. Update it as reality changes. The roadmap is a compass, not a contract.*
