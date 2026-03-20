# SideQuests Brain — Provisional Patent Application (PPA) Filing Guide

**Prepared by:** Claude (Senior Dev / Architect)
**Date:** March 20, 2026
**For:** Don J. Shelton

---

## TL;DR

File the PPA now. Your Inventor's Notebook is 90% ready. Budget $1,500–3,000 for attorney + filing fees. Do NOT publish any code until the filing receipt is in hand.

---

## Action Plan

### Step 1: Update the Inventor's Notebook (This Week)

The current notebook (Mar 20 docx) has strong IP claims but needs cleanup before handing to an attorney. See `B-notebook-update.md` for the Gemini delegation plan. Key fixes:

- Replace stale tool names (`ingest_message` → `notify_turn`)
- Add reduction-to-practice evidence (474 tests, all milestones built)
- Document B17/B18/B3/B2 as implemented features, not just plans
- Add witness signature blocks
- Align milestone descriptions with actual build order

### Step 2: Find a Patent Attorney (This Week)

**What to look for:**
- Specializes in **software patents** or **AI/ML patents**
- Experience navigating post-Alice (2014) patent eligibility for software methods
- Offers **flat-fee PPA filing** (not hourly — you're handing them a near-complete disclosure)
- Licensed USPTO patent agent or attorney

**Where to find them:**
- USPTO Patent Attorney Search: https://oedci.uspto.gov/OEDCI/
- LegalZoom / UpCounsel for flat-fee options (budget tier)
- Ask in r/patentlaw or r/startups for referrals
- Local IP law firms (search "[your city] software patent attorney")

**What to tell them:**
> "I'm a solo inventor seeking a Provisional Patent Application for a software system. I qualify for Micro Entity status. I have a comprehensive 30+ page Inventor's Notebook with 13 explicitly defined novelty claims, full architectural specifications, database schemas, and a working prototype with 474 passing tests. I need you to review the disclosure, shape the claims for post-Alice eligibility, and file the PPA."

**Red flags to avoid:**
- Attorney who wants to charge hourly to "understand" the invention (your notebook IS the understanding)
- Anyone who says software patents are easy/guaranteed
- Firms that won't give a flat-fee quote upfront

### Step 3: File the PPA ($64–$3,000)

**USPTO filing fee:** $64 (Micro Entity) or $128 (Small Entity)
- You qualify as Micro Entity if: individual inventor, not named on >4 prior patents, gross income below ~$228K
- File as Micro Entity unless your attorney says otherwise

**Attorney fee:** $800–$3,000 depending on how much shaping they do
- Low end: attorney reviews your notebook, formats as PPA, files as-is
- High end: attorney restructures claims, writes additional dependent claims, adds patent-specific language

**Total realistic budget: $1,500–$2,500**

### Step 4: After Filing — You're Patent Pending

Once you have the USPTO filing receipt:

1. **Publish code to GitHub** — now safe, priority date is locked
2. **Add "Patent Pending" to README and website**
3. **Start B4 (PyPI publish)** and B5 (Smithery listing) — currently blocked by this
4. **Set a calendar reminder for 10 months out** — you have 12 months to convert to a full utility patent, but you need lead time

### Step 5: Full Utility Patent (Within 12 Months) — $8,000–$15,000

**Do not let the PPA lapse without converting.** If you miss the 12-month window, you lose your priority date and any public disclosure (GitHub, blog, demo) could be used against you.

Options:
- **Self-fund the conversion** — budget $8K–15K for attorney fees + USPTO fees
- **Option C exit** — if acquired/licensed before the deadline, the acquiring company's legal team handles this
- **PCT international filing** — only if you want protection outside the US (~$3K–5K additional, due at 12 months)

---

## What Gemini Got Right

1. **File now, before any public disclosure** — Correct and critical
2. **Your notebook is strong enabling disclosure** — True, saves thousands in attorney hours
3. **Micro/Small Entity status** — Correct, you qualify
4. **12-month grace period** — Correct
5. **Cost estimate ($1,500–3,000 for PPA)** — Reasonable range

## What Gemini Got Wrong or Oversold

1. **"You might never have to pay the full patent cost"** — Dangerously optimistic. The "get acquired in 12 months" scenario is a lottery ticket. Budget for the $8K–15K utility patent conversion. If you let the PPA lapse, you lose everything.

2. **Software patents are hard to enforce** — Gemini didn't mention this. Post-Alice Corp. v. CLS Bank (2014 Supreme Court), pure software method patents face significant eligibility challenges under 35 U.S.C. § 101. Your biomimetic framing helps (it's not "do X on a computer" — it's a specific 9-step algorithmic method modeled on cognitive science), but the attorney needs to shape claims carefully around the *specific algorithmic steps*, not high-level concepts.

3. **International protection** — Gemini glossed over this. A US PPA provides zero international protection. If you want rights outside the US, you need a PCT filing within 12 months (~$3K–5K). For a solo founder, US-only is likely fine initially.

4. **"Patent Pending" doesn't stop anyone** — It's a deterrent and a negotiating asset, not a legal barrier. Someone can still build the same thing. The patent only matters if you can afford to enforce it (litigation = $500K+). For your Option C exit strategy, it matters as an *asset on the balance sheet*, not as a weapon.

---

## Your Two Strongest Claims

If budget is tight and the attorney can only deeply shape 2–3 claims, prioritize:

### 1. Gated Consolidation Loop (Method Patent)
The 9-step biomimetic pipeline is your primary moat. No competitor does this. The specific sequence (NER → Dual-Process Classification → Ontology Routing → Shape-First Relation Extraction → Selective Attention Gating → Dual-Scope Retrieval → Constrained Arbitration → Pathway Update + Synaptic Pruning) is novel, non-obvious, and demonstrably implemented.

**Post-Alice framing:** This is not "memory storage on a computer." It's a specific multi-step algorithmic method that transforms passive data into a self-correcting knowledge graph using quantified cognitive heuristics (confidence thresholds, decay curves, Hebbian strength functions). The method produces a measurably different technical result (auditable graph with reversible merges) that couldn't be done mentally.

### 2. Semantic Quest Routing / Hippocampus Mechanism (System Patent)
Multi-signal routing fusion with progressive consolidation and prediction error reconsolidation. Novel because: (a) no prior art combines semantic similarity + workspace signals + entity overlap into a unified routing confidence, (b) the tentative→consolidated→locked state machine with automatic reconsolidation is unique, (c) it solves a real technical problem (routing conversations to knowledge subgraphs without filesystem anchors).

### Secondary claims worth including:
- Cocktail Party Effect (passive selective attention architecture)
- Working Memory Awareness (LOADED edge tracking + smart deduplication)
- Out-of-Band Anomaly Detection (conversation-layer security from architectural isolation)

---

## Notebook Issues to Fix Before Filing

| Issue | Location | Fix |
|-------|----------|-----|
| `ingest_message` referenced | Section 5.5.E | Replace with `notify_turn` |
| Milestones describe B17/B18 as M4/M5 | Section 8 | Align with actual build order (B17/B18 built after M8) |
| No reduction-to-practice evidence | Section 8 | Add: "474 tests passing, all milestones implemented" with dates |
| Missing Cowork Plugin as distribution mechanism | Section 5.5 | Add B2 plugin architecture as novel integration |
| `explore_graph` not flagged as a claim | Section 5.7 | Consider adding RLM-inspired directed traversal |
| No witness signatures | Throughout | Add signature/date blocks per entry |
| Spec sections don't match journal entries | Sections 5.3–5.5 | Reconcile; journal is more current |

---

## Timeline

| When | What | Cost |
|------|------|------|
| This week | Update notebook (B-notebook-update.md) | $0 |
| This week | Contact 2–3 patent attorneys for quotes | $0 |
| Within 2 weeks | Attorney reviews notebook, shapes claims | $800–2,500 |
| Within 3 weeks | PPA filed with USPTO | $64–128 |
| Same day as filing receipt | Publish to GitHub, start PyPI/Smithery | $0 |
| Month 10 | Begin utility patent conversion | $8K–15K |

---

## Files Referenced

- `InvertorsDocs/Side Quests - Inventor's Notebook_Mar20_2026.docx` — Current notebook (needs updates)
- `InvertorsDocs/SideQuests-InventorsNotebook.md` — Markdown version (may be older)
- `B-notebook-update.md` — Gemini delegation plan for notebook fixes
- `CLAUDE.md` — Full technical specification (enabling disclosure)
