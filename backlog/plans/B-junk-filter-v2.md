# B-ISSUE-026: Junk Concepts Leaking — Stopwords, Ordinals, and System Terms

## Problem

Step 1 NER junk filter (`_is_junk_entity`) misses several classes of junk:
1. **Ordinals:** "first", "second", "third" — spaCy labels these as ORDINAL
2. **System terms:** "MainQuest", "SideQuest", "Brain", "current_truth" — SideQuests internal vocabulary leaking from assistant responses
3. **Generic noun chunks:** "all endpoints", "the only exception", "a global dependency" — noun chunk fallback captures phrases that are too generic to be concepts
4. **Common stopword entities:** single common words like "first" that aren't meaningful concepts

## Fix

### Part 1: Update `_is_junk_entity` in `step1_ner.py`

**File:** `mcp_engine/loop/step1_ner.py`

Add these checks to `_is_junk_entity`, BEFORE the `return False` at the end:

```python
    # Ordinal words — "first", "second", "1st", "2nd" etc.
    # These get extracted as ORDINAL entities by spaCy but aren't concepts.
    _ordinal_re = re.compile(
        r'^(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth'
        r'|\d+(?:st|nd|rd|th))$', re.I
    )
    if _ordinal_re.match(stripped):
        return True

    # SideQuests system vocabulary — internal terms that leak from assistant
    # responses via notify_turn. These are never real user concepts.
    _SYSTEM_TERMS = {
        "mainquest", "sidequest", "sidequests", "brain", "brain daemon",
        "current_truth", "notify_turn", "branch_quest", "complete_quest",
        "diff_since", "explore_graph", "get_open_loops", "gated consolidation",
        "cocktail party", "confidence_low", "pathway_strength",
    }
    if stripped.lower() in _SYSTEM_TERMS:
        return True
```

**Important:** Move the `_ordinal_re` compile and `_SYSTEM_TERMS` set to module level (outside the function) so they're only compiled/created once, not on every call. Place them after the existing `_UUID_RE` and `_HEX_HASH_RE` definitions near the top of the file.

### Part 2: Filter generic noun chunks in `extract_entities`

**File:** `mcp_engine/loop/step1_ner.py`

In the noun chunk fallback section (around line 99-115), add a filter for chunks that start with determiners or are too generic. Find this code block:

```python
            # Skip junk (terminal artifacts, UUIDs, formatting noise)
            if _is_junk_entity(chunk.text):
                continue
```

Add right after it:

```python
            # Skip noun chunks that start with determiners/quantifiers —
            # "all endpoints", "the only exception", "a global dependency"
            # are too generic to be concepts. Named entities from NER don't
            # have this problem because spaCy already filtered them.
            if chunk.root.dep_ in ("det", "nummod") or chunk.text.split()[0].lower() in (
                "a", "an", "the", "all", "some", "any", "no", "every",
                "this", "that", "these", "those", "each",
            ):
                continue
```

### Part 3: Update Tests

**File:** `tests/test_loop.py`

Find the existing junk filter tests (search for `test_step1_junk_filter` or `_is_junk_entity`). Add these tests near them:

```python
def test_step1_junk_filter_ordinals():
    """ISSUE-026: ordinal words should be filtered as junk."""
    from mcp_engine.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("first") is True
    assert _is_junk_entity("Second") is True
    assert _is_junk_entity("1st") is True
    assert _is_junk_entity("3rd") is True


def test_step1_junk_filter_system_terms():
    """ISSUE-026: SideQuests internal vocabulary should be filtered."""
    from mcp_engine.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("MainQuest") is True
    assert _is_junk_entity("SideQuest") is True
    assert _is_junk_entity("Brain") is True
    assert _is_junk_entity("current_truth") is True
    assert _is_junk_entity("notify_turn") is True
    # Real entities should still pass
    assert _is_junk_entity("PostgreSQL") is False
    assert _is_junk_entity("SQLAlchemy") is False
    assert _is_junk_entity("JWT") is False
```

### Part 4: Log the Issue

**File:** `runningIssueLog.md`

Append this entry at the end of the file:

```markdown
---

### ISSUE-026 · Junk concepts leaking — ordinals, system terms, generic noun chunks
**Symptom:** Concepts like "MainQuest", "first", "all endpoints", "the only exception", "a global dependency" stored in the graph. These are not meaningful user concepts — they're ordinals, SideQuests internal terms, or generic noun chunks.

**Root cause:** `_is_junk_entity()` filter didn't cover ordinals (spaCy ORDINAL label), SideQuests system vocabulary (leaked from assistant responses via notify_turn), or generic noun chunks starting with determiners.

**Fix:** Added ordinal regex, system terms set, and determiner-initial noun chunk filter to `step1_ner.py`.

**Files changed:** `mcp_engine/loop/step1_ner.py`, `tests/test_loop.py`, `runningIssueLog.md`
```

## Implementation Order

1. Read `mcp_engine/loop/step1_ner.py` to understand current structure
2. Add module-level constants (`_ORDINAL_RE`, `_SYSTEM_TERMS`) after existing regex definitions
3. Add ordinal and system term checks to `_is_junk_entity` before `return False`
4. Add determiner filter to noun chunk fallback section
5. Read `tests/test_loop.py` to find existing junk filter tests
6. Add new tests near existing junk filter tests
7. Append issue to `runningIssueLog.md`
8. Run: `python3 -m pytest tests/test_loop.py -v` — verify new tests pass
9. Run: `python3 -m pytest tests/ -v` — verify no regressions
