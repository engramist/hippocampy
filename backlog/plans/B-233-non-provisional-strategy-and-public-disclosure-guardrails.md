# Plan for B233 - Non-Provisional Strategy and Public Disclosure Guardrails

## Card Metadata

- **Card ID**: B233
- **Priority**: P0
- **Dependencies**: Filed PPA recorded in `InvertorsDocs/Canonical-Inventors-Notebook.md`

## Summary

Create engineering-facing release guardrails for the patent-pending period.

The PPA is filed, so public release can proceed after release hardening. However, non-provisional planning still matters. This card documents the priority facts, deadline, claim map, and disclosure boundaries so public packaging decisions do not depend on scattered notes.

## Technical Approach

### Step 1: Verify filing facts from canonical notebook

Read `InvertorsDocs/Canonical-Inventors-Notebook.md` and extract:

- application number
- confirmation number
- Patent Center number
- receipt timestamp
- priority date
- non-provisional deadline

Use those facts consistently. Do not invent legal conclusions.

Required facts:

```text
Application #64/017,066
Confirmation #7549
Patent Center #75018063
Priority date: March 25, 2026
Non-provisional deadline: March 25, 2027
```

### Step 2: Create non-provisional strategy doc

Create `docs/nonprovisional-strategy.md`.

Sections:

- Status and filing facts
- What patent pending means and does not mean
- Non-provisional deadline
- Claim map from architecture/inventor notes
- Implementation evidence to preserve
- Public release checklist
- Counsel-review packet
- Month-by-month timeline to March 25, 2027

Include a disclaimer: engineering planning doc, not legal advice.

### Step 3: Create public disclosure boundary doc

Create `docs/public-disclosure-boundary.md`.

Classify:

- runtime code
- installer code
- architecture docs
- tool catalog
- backlog cards/plans
- inventor docs
- patent prep docs
- ARC artifacts
- benchmark outputs
- diagrams
- seed examples
- routing/tuning parameters
- generated wiki output

Decision options:

```text
public | private | redact | counsel-review | package-exclude | historical-only
```

### Step 4: Update README patent-pending language

Add concise wording:

```text
SideQuests includes patent-pending memory architecture. A U.S. provisional application was filed March 25, 2026. No patent has been granted.
```

Avoid claiming a granted utility patent.

### Step 5: Update architecture if needed

Ensure `docs/ARCHITECTURE.md` references filed PPA and deadline, not pre-filing secrecy language.

### Step 6: Update backlog tracker

Add a small `Public Release Readiness` section to `backlog/masterBacklogTracker.md` with B230-B233.

### Step 7: Validation searches

Run searches for accidental overclaiming:

```bash
rg -n "patent granted|granted patent|utility patent granted" README.md docs InvertorsDocs || true
```

Run searches for required facts:

```bash
rg -n "64/017,066|7549|75018063|March 25, 2027|patent pending|non-provisional|nonprovisional" docs README.md InvertorsDocs/Canonical-Inventors-Notebook.md backlog/masterBacklogTracker.md
```

## Validation

Run exactly:

```bash
rg -n "64/017,066|7549|75018063|March 25, 2027|patent pending|non-provisional|nonprovisional" docs README.md InvertorsDocs/Canonical-Inventors-Notebook.md backlog/masterBacklogTracker.md
rg -n "patent granted|granted patent|utility patent granted" README.md docs InvertorsDocs || true
python - <<'PY'
from pathlib import Path
for path in ['docs/nonprovisional-strategy.md', 'docs/public-disclosure-boundary.md']:
    text = Path(path).read_text()
    assert 'March 25, 2027' in text
    assert '64/017,066' in text
print('non-provisional docs contain required filing facts')
PY
```

## Risks

- This is not legal advice; all claim and disclosure decisions should be reviewed by patent counsel before non-provisional filing.
- Publishing architecture details may be strategically acceptable after PPA but still not always optimal. Mark trade-secret/tuning choices explicitly.
- The public repo may not be the right home for every inventor/patent document; coordinate with B232 audit decisions.
