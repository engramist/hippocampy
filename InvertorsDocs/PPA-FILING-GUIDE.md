# SideQuests Brain — Provisional Patent Application (PPA) Filing Guide

**Prepared by:** GitHub Copilot (Senior Dev / Architect)
**Updated:** March 24, 2026
**For:** Don J. Shelton — **Pro Se (self-filing, no attorney)**

---

## TL;DR

You are filing the PPA yourself. USPTO fully supports this — it calls it filing "pro se" and provides a free assistance program. Your total out-of-pocket cost is **$64** (Micro Entity USPTO filing fee). The PPA itself does not require formal claims or a sworn declaration — just a written description and a cover sheet. Do NOT publish any code until the filing receipt (email confirmation from Patent Center) is in your hands.

---

## Free USPTO Resources for Pro Se Filers

Use these before and after filing — all free, all staffed by USPTO examiners:

| Resource | Link / Contact | What for |
|----------|---------------|----------|
| **Pro Se Assistance Program** | https://www.uspto.gov/patents/basics/using-legal-services/pro-se-assistance-program | Outreach, checklists, guides — start here |
| **Inventors Assistance Center (IAC)** | IndependentInventor@uspto.gov · 800-786-9199 | General questions answered by former examiners |
| **Patent Center (filing portal)** | https://patentcenter.uspto.gov | Where you actually file online |
| **Patent Electronic Business Center** | https://www.uspto.gov/learning-and-resources/support-centers/patent-electronic-business-center | Help with the online filing system |
| **Patent Pro Bono Program** | https://www.uspto.gov/patents/basics/using-legal-services/pro-bono/patent-pro-bono-program | Free attorney help if income-constrained |
| **Patent Public Search** | https://ppubs.uspto.gov | Prior art search before filing |

---

## Action Plan

### Step 1: Update the Inventor's Notebook (This Week)

Your notebook is the written description that goes directly into the PPA. Under 35 U.S.C. § 112(a) the written description must be complete enough that someone skilled in the field could reproduce the invention — your CLAUDE.md + notebook already satisfies this. Clean it up:

- Replace stale tool names (`ingest_message` → `notify_turn`)
- Add reduction-to-practice evidence (tests passing, all milestones built, dates)
- Document B17/B18/B3/B2 as implemented features, not just plans
- Add witness signature/date blocks to journal entries
- Align milestone descriptions with actual build order

> **PPA does NOT require formal patent claims** — a pre-publication technical description is sufficient. Your notebook + CLAUDE.md architecture spec is your written description.

---

### Step 2: Create and Verify Your USPTO.gov Account (Takes 2–3 Days)

You **must** have a verified USPTO.gov account before you can file electronically via Patent Center. Identity verification is required and takes time — do this now, before your documents are ready.

1. Go to https://my.uspto.gov and create an account
2. Complete identity verification (required for Patent Center access)
3. Once verified, log into Patent Center at https://patentcenter.uspto.gov
4. Optionally contact the Patent Electronic Business Center for help: https://www.uspto.gov/learning-and-resources/support-centers/patent-electronic-business-center

---

### Step 3: Run a Prior Art Search (Before Filing)

USPTO requires you to know what's already out there. This doesn't block filing, but the examiner will do their own search when you convert to a nonprovisional — knowing the landscape helps you shape later claims.

Completed search memo for this step: `InvertorsDocs/PriorArtSearch.md`

- **Patent Public Search tool:** https://ppubs.uspto.gov/pubwebapp/static/pages/landing.html
- **USPTO prior art search guide (PDF):** https://www.uspto.gov/sites/default/files/documents/Basics-of-Prior-Art-Searching.pdf
- **Video tutorial (36 min):** https://www.uspto.gov/video/cbt/prelim-patent-search/index.html
- Search for: "knowledge graph AI memory", "LLM memory persistence", "episodic memory neural network", "conversation context graph"

---

### Step 4: Prepare Your PPA Documents (DOCX Format — Required)

**File everything in DOCX format.** As of January 17, 2024, USPTO charges a non-DOCX surcharge of up to **$400** for specifications, claims, and abstracts not submitted in DOCX. Avoid this by using the USPTO DOCX template.

**Documents to prepare:**

| Document | Required? | Notes |
|---------|----------|-------|
| **Written Description** (specification) | ✅ Yes | Your Inventor's Notebook + architecture spec. Must satisfy 35 U.S.C. §112(a) — complete enough to reproduce. |
| **Drawings** | Optional but strongly recommended | A drawing necessary to understand the invention cannot be added after filing. Your `SideQuests-Patent-Figures.excalidraw` renders to static images — export each FIG. as PNG/PDF before filing. |
| **Cover Sheet (Form PTO/SB/16)** | ✅ Yes | Download: https://www.uspto.gov/sites/default/files/documents/sb0016.pdf |
| **Formal patent claims** | ❌ Not required for PPA | PPAs are not examined — no claims required. Do include an informal claim section to preserve priority scope. |
| **Oath/Declaration** | ❌ Not required for PPA | Required only for nonprovisional. |
| **Prior art (IDS)** | ❌ Not permitted in PPA | Do not include — provisional applications are not examined. |

**Cover sheet (PTO/SB/16) must include:**
- Checkbox: "This is a PROVISIONAL APPLICATION FOR PATENT"
- Name(s) of all inventors (just you: Don J. Shelton)
- Inventor residence (city, state, country)
- Title of the invention (suggested: *"Biomimetic Gated Consolidation System for Persistent AI Memory with Graph-Native Knowledge Representation"*)
- Correspondence address (your email/address for USPTO correspondence)
- Any U.S. Government agency with a property interest (leave blank — none)

**USPTO DOCX Specification Template:** https://view.officeapps.live.com/op/view.aspx?src=https%3A%2F%2Fwww.uspto.gov%2Fsites%2Fdefault%2Ffiles%2Fdocuments%2FDOCX_Template_2_0.docx

---

### Step 5: File via Patent Center — $64 (Micro Entity)

**You qualify as Micro Entity if:**
- Individual inventor (not assigned to a large entity)
- Not named as inventor on more than 4 prior U.S. patents
- Gross income in prior year did not exceed ~$228,512 (3× median household income — verify current threshold at USPTO fee schedule)

**Filing steps in Patent Center:**
1. Log in at https://patentcenter.uspto.gov
2. Click "File a new application" → select **Provisional Application**
3. Upload documents in this order:
   - Specification (DOCX) — your written description
   - Drawings (PDF or DOCX) — your FIG. 1–7 static images
   - Cover sheet: either use the fillable PDF PTO/SB/16 or enter the cover sheet data directly in Patent Center's guided form
4. Select **Micro Entity** status and submit the Micro Entity form (PTO/SB/15A)
5. Pay the **Provisional Application Filing Fee: $64** (Micro Entity)
   - Verify current fee before paying: https://www.uspto.gov/learning-and-resources/fees-and-payment/uspto-fee-schedule
   - Accepted payment: credit card, USPTO deposit account, EFT
6. Submit. You will receive an **email confirmation with your Application Number** — this is your filing receipt and your priority date.

> **Provisional filing can also be done by mail** (Commissioner for Patents, P.O. Box 1450, Alexandria, VA 22313-1450) but electronic filing via Patent Center is faster, cheaper, and gives you immediate confirmation.

---

### Step 6: After Filing — You're Patent Pending

The day you receive your USPTO filing receipt email:

1. **Note your Application Number and Filing Date** — keep these permanently
2. **Publish your GitHub repository** — priority date is locked
3. **Add "Patent Pending" to README, website, and npm/PyPI package description**
4. **Start PyPI publish (B4) and Smithery listing (B5)** — both were blocked pending this
5. **Set a calendar reminder for Month 10** — you have 12 months total; filing the nonprovisional at Month 11 is cutting it close. Month 10 gives you transition time.

---

### Step 7: Full Utility Patent (Within 12 Months) — Decision Point

**The 12-month window cannot be extended.** (There is a 14-month restoration petition for $2,000+ but do not rely on it.) If you let the PPA lapse without filing a nonprovisional:
- You lose your March 2026 priority date
- Any public disclosure (GitHub, blog, demo, conference) that occurred during the 12 months could be used as prior art to reject your later claims

**Your options at Month 10–11:**

| Option | Cost | Notes |
|--------|------|-------|
| **Pro se nonprovisional** | ~$320–800 USPTO fees (Micro Entity) | Hard — nonprovisionals require formal claims and full prosecution. Doable but risky without claim drafting experience. |
| **Hire a patent attorney for just the nonprovisional** | $5K–12K | By this point your priority date is proven and the attorney does less disclosure drafting. Lower cost than a full engagement from scratch. |
| **Patent Pro Bono Program** | $0 | Apply early — waitlist exists. For underresourced independent inventors. https://www.uspto.gov/patents/basics/using-legal-services/pro-bono/patent-pro-bono-program |
| **Law School Clinic Program** | $0 | Supervised law students file on your behalf. https://www.uspto.gov/learning-and-resources/ip-policy/public-information-about-practitioners/law-school-clinic-1 |
| **Option C (acquisition)** | $0 | Acquiring company's legal team handles conversion. Only reliable if a term sheet is in hand. |

**Recommended path:** File the PPA now (pro se, $64). At Month 4–5, contact the Patent Pro Bono Program and one law school clinic — long onboarding timelines. If neither comes through by Month 9, hire an attorney for just the nonprovisional conversion (~$5K).

---

## Your Two Strongest Claims (For Nonprovisional)

These are the claims that most need to survive post-*Alice Corp. v. CLS Bank* (2014) software eligibility scrutiny under 35 U.S.C. § 101. Frame them as specific algorithmic methods tied to a technical result — not abstract ideas implemented on a generic computer.

### 1. Gated Consolidation Loop (Method Patent — Primary Moat)

The 9-step biomimetic pipeline. No competitor does this. The specific sequence — NER → Dual-Process Classification → Ontology Routing → Shape-First Relation Extraction → Selective Attention Gating → Dual-Scope Retrieval → Constrained Arbitration → Pathway Update + Synaptic Pruning — is novel, non-obvious, and demonstrably implemented.

**Post-Alice framing:** This is a specific multi-step algorithmic method with measurable numerical parameters (confidence thresholds, decay rate exponents, Hebbian strength delta functions) that transforms unstructured conversational data into a self-correcting knowledge graph. The method produces a technically different result (auditable graph with reversible merge events) that couldn't be performed mentally and isn't achievable with a generic database.

### 2. Semantic Quest Routing / Hippocampus Mechanism (System Patent)

Multi-signal routing fusion with progressive consolidation and prediction-error reconsolidation via Long-Term Depression. Novel: (a) no prior art fuses semantic similarity + workspace OS context + entity-overlap into a single routing confidence value, (b) the tentative→consolidated→locked state machine with automatic reconsolidation is unique, (c) it solves the specific technical problem of routing AI conversations to knowledge subgraphs using content-addressable memory rather than filesystem anchors.

### Secondary claims worth including in the nonprovisional:
- Cocktail Party Effect (passive selective attention via a named-sense confidence gate)
- Working Memory Awareness (LOADED edge tracking + smart deduplication)
- Out-of-Band Anomaly Detection (architectural isolation of brain from LLM context window)
- Synaptic Pruning with Hebbian LTP promotion (CO_OCCURS_WITH → named semantic edge)

---

## Important Legal Realities (No Attorney to Tell You This)

1. **"Patent Pending" is a deterrent, not a shield.** Someone can still build the same thing during your pending period. The value to you is as a balance-sheet asset for an acquisition or licensing deal, not as a weapon.

2. **Software patents face eligibility challenges.** Post-*Alice*, examiners reject claims framed as "do X on a computer." Your biomimetic framing and specific algorithmic steps are strong, but expect at least one § 101 office action during nonprovisional examination. This is normal — respond by pointing to the specific numerical thresholds and technical effects.

3. **PPA disclosure quality sets your ceiling.** The nonprovisional claims can only cover subject matter disclosed in the PPA. Include everything: architecture, all 9 steps, all named IP claims (Cocktail Party Effect, Synaptic Pruning, Hebbian LTP, Shape-First Principle). Anything omitted from the PPA cannot be added later.

4. **US PPA provides zero international protection.** A PCT filing gives you 30-month entry into ~150 countries from your priority date, but costs ~$3K–5K additional. For a solo founder, US-only protection is the right first move. You can still file PCT within 12 months of this PPA if international rights become strategically necessary.

5. **The USPTO does not mail maintenance reminders.** Utility patents require maintenance fees at 3.5, 7.5, and 11.5 years. Missing one expires your patent — set calendar reminders now for those dates (from your eventual issue date).

---

## Notebook Issues to Fix Before Filing

| Issue | Location | Fix |
|-------|----------|-----|
| `ingest_message` referenced | Section 5.5.E | Replace with `notify_turn` |
| Milestones describe B17/B18 as M4/M5 | Section 8 | Align with actual build order |
| No reduction-to-practice evidence | Section 8 | Add: tests passing count, all milestones implemented, with dates |
| Missing Cowork Plugin as distribution mechanism | Section 5.5 | Add B2 plugin architecture as novel integration |
| `explore_graph` not flagged as a claim | Section 5.7 | Consider adding RLM-inspired directed traversal |
| No witness signatures | Throughout | Add signature/date blocks per journal entry |
| Spec sections don't match journal entries | Sections 5.3–5.5 | Reconcile; journal is more current |

---

## Timeline (Pro Se Path)

| When | What | Cost |
|------|------|------|
| This week | Create USPTO.gov account + verify identity | $0 |
| This week | Update Inventor's Notebook; export FIG. 1–7 as static images | $0 |
| This week | Run prior art search via Patent Public Search | $0 |
| This week | Download + fill out cover sheet PTO/SB/16 | $0 |
| Within 2 weeks | File PPA via Patent Center (Micro Entity) | **$64** |
| Same day as filing receipt | Publish GitHub, start PyPI/Smithery, add "Patent Pending" | $0 |
| Month 3–4 | **Apply to Patent Pro Bono Program** (long lead time) | $0 |
| Month 4–5 | **Contact law school clinics** (long onboarding) | $0 |
| Month 10 | Either pro bono program covers nonprovisional, or hire attorney | $0 or $5K–12K |
| Month 11 | Nonprovisional filed, claiming PPA priority date | USPTO fees: ~$320–800 |

---

## Files Referenced

- `InvertorsDocs/Side Quests - Inventor's Notebook (032406).md` — Primary written description for the PPA
- `InvertorsDocs/SideQuests-Patent-Figures.excalidraw` — Figure source (export as static images before filing)
- `InvertorsDocs/SideQuests-Patent-Figures.md` — Figure captions and descriptions
- `CLAUDE.md` — Full enabling disclosure (architecture, schema, algorithms — attach as appendix or incorporate into spec)
- USPTO Cover Sheet PTO/SB/16: https://www.uspto.gov/sites/default/files/documents/sb0016.pdf
- USPTO DOCX Spec Template: https://www.uspto.gov/sites/default/files/documents/DOCX_Template_2_0.docx
