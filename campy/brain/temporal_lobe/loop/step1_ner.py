"""Step 1 — Zoning / NER (ONNX, B387). Zero LLM cost.

B387 replaced spaCy (`en_core_web_md`, which pulls in ~225 MB of torch/thinc)
with `onnx_ner_engine.OnnxNerEngine` for named-entity recognition and
`shallow_parse` for the noun-chunk-equivalent fallback. See those two
modules' headers for the model choice / license rationale and the
noun-chunk-replacement design.

`extract_entities()` keeps its historical (doc, entities) return contract —
`doc` is now a `shallow_parse.ParsedText` instead of a spaCy `Doc`, consumed
by `step1b_relations.extract_relations()`.
"""

import re

from campy.brain.temporal_lobe.loop.onnx_ner_engine import get_engine
from campy.brain.temporal_lobe.loop.shallow_parse import (
    SKIP_CHUNKS,
    ParsedText,
    parse,
    shallow_chunks,
)

# Pronouns and stopwords to filter from noun chunk fallback — kept as a
# module-level alias for anything still importing it from here.
_SKIP_CHUNKS = SKIP_CHUNKS

# UUID pattern: 32+ hex chars optionally separated by hyphens
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
)
# Hex hash pattern: 32+ contiguous hex chars
_HEX_HASH_RE = re.compile(r'^[0-9a-f]{32,}$', re.I)

# Ordinal words — "first", "second", "1st", "2nd" etc.
# These get extracted as ORDINAL entities by spaCy but aren't concepts.
_ORDINAL_RE = re.compile(
    r'^(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth'
    r'|\d+(?:st|nd|rd|th))$', re.I
)

# Cardinal number words — "four", "twenty", "twenty-four", "two hundred" etc.
# These pass the float() check above (they're alphabetic) but a bare number
# word carries no standalone meaning (B300). Only matches the whole entity
# text — "four retries max" is a real phrase and must not be caught here.
_CARDINAL_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine"
    r"|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
    r"|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    r"|hundred|thousand|million|billion"
)
_CARDINAL_RE = re.compile(
    rf'^(?:{_CARDINAL_WORDS})(?:[\s-](?:{_CARDINAL_WORDS}))?$', re.I
)

# SideQuests system vocabulary — internal terms that leak from assistant
# responses via notify_turn. These are never real user concepts.
_SYSTEM_TERMS = {
    "mainquest", "sidequest", "sidequests", "brain", "brain daemon",
    "current_truth", "notify_turn", "branch_quest", "complete_quest",
    "diff_since", "explore_graph", "get_open_loops", "gated consolidation",
    "cocktail party", "confidence_low", "pathway_strength",
}


def _is_junk_entity(text: str) -> bool:
    """
    Reject entities that are terminal artifacts, not real concepts.
    Catches: box-drawing chars, raw UUIDs, formatting noise, whitespace-only.
    """
    stripped = text.strip()

    # Empty after strip
    if not stripped:
        return True

    # Too short to be meaningful (single char that isn't a letter)
    if len(stripped) == 1 and not stripped.isalpha():
        return True

    # Pure numbers / decimals (e.g. "0.92", "03", "18", "384")
    # These get extracted from JSON payloads in notify_turn content.
    try:
        float(stripped)
        return True
    except ValueError:
        pass

    # No alphanumeric characters at all (box-drawing: ╮ ─── │ etc.)
    if not any(c.isalnum() for c in stripped):
        return True

    # UUID or hex hash
    if _UUID_RE.match(stripped) or _HEX_HASH_RE.match(stripped):
        return True

    # Ordinal words — "first", "second", "1st", "2nd" etc.
    if _ORDINAL_RE.match(stripped):
        return True

    # Cardinal number words — "four", "twenty-four", "two hundred" etc.
    if _CARDINAL_RE.match(stripped):
        return True

    # SideQuests system vocabulary
    if stripped.lower() in _SYSTEM_TERMS:
        return True

    # Contains box-drawing or block element Unicode characters (terminal UI noise)
    if any('─' <= c <= '╿' or '▀' <= c <= '▟' for c in stripped):
        return True

    # Mostly non-alphanumeric (less than 50% alnum)
    alnum_ratio = sum(1 for c in stripped if c.isalnum()) / len(stripped)
    if alnum_ratio < 0.5:
        return True

    # Contains control characters or raw newlines (check before strip)
    if any(c in text for c in '\n\r\x00'):
        return True

    # B34 fix: markdown headings (### Open Loops, ## Decisions, etc.)
    if stripped.startswith('#'):
        return True

    # B34 fix: markdown bold markers leaking through (e.g. "Project Setup:**")
    if '**' in stripped:
        return True

    # B34 fix: prepositional fragments ("to persist summaries", "for the database")
    _PREP_STARTS = ('to ', 'for ', 'with ', 'from ', 'by ', 'in ', 'on ', 'at ', 'of ')
    if stripped.lower().startswith(_PREP_STARTS):
        return True

    # B34 fix: snake_case or camelCase code identifiers
    # snake_case: contains underscore between letters (e.g. "last_loop_summary")
    if '_' in stripped and re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', stripped):
        return True
    # camelCase: lowercase start followed by uppercase (e.g. "questId", "loopSummary")
    if re.match(r'^[a-z]+[A-Z]', stripped):
        return True

    # B34 fix: single generic words that aren't meaningful as standalone concepts
    _GENERIC_WORDS = {
        'constraints', 'decisions', 'requirements', 'session', 'sessions',
        'quests', 'routes', 'setup', 'config', 'status', 'data',
        'items', 'results', 'options', 'settings', 'parameters',
    }
    if stripped.lower() in _GENERIC_WORDS:
        return True

    # B34 fix: too short for a single word (< 3 chars, no spaces)
    if ' ' not in stripped and len(stripped) < 3:
        return True

    return False


def extract_entities(text: str, model_name: str | None = None) -> tuple[ParsedText, list]:
    """
    Run ONNX NER + shallow parse on text.
    Returns (parsed, entities) where entities is a list of dicts and `parsed`
    is a `shallow_parse.ParsedText` (B387 — replaces the spaCy `Doc` that
    used to be returned here; kept for Step 1b, which reuses it for
    governance-verb relation extraction — no double parse).

    `model_name` is accepted for backward compatibility with callers that
    still pass the (now-retired) spaCy model config value; it is ignored —
    the ONNX NER model is a single fixed choice (see onnx_ner_engine.py).

    Falls back to shallow-chunk extraction when NER finds few entities.
    The CoNLL-2003 tag set (PER/ORG/LOC/MISC) misses most software/tech
    terms (PostgreSQL, MySQL, React, etc.) since they aren't people, places,
    or organizations — shallow_chunks() catches them the same way spaCy's
    noun_chunks used to.
    """
    if not text.strip():
        return parse(text), []

    engine = get_engine()
    ner_spans = engine.predict(text)

    entities = [
        {
            "text":  span["text"],
            "label": span["label"],   # PERSON, ORG, GPE, MISC
            "start": span["start"],
            "end":   span["end"],
        }
        for span in ner_spans
        if not _is_junk_entity(span["text"])
    ]

    parsed = parse(text)

    # Chunk fallback: if NER found <=1 entity, supplement with shallow chunks.
    # Technical conversations mention tools/frameworks/concepts that the
    # CoNLL-2003 tag set doesn't recognize but candidate-phrase chunking
    # captures reliably.
    if len(entities) <= 1:
        ner_spans_set = {(e["start"], e["end"]) for e in entities}
        for start, end, chunk_text in shallow_chunks(parsed):
            # Skip pronouns and trivial stopwords
            if chunk_text.lower().strip() in _SKIP_CHUNKS:
                continue
            # Skip chunks already covered by NER
            if (start, end) in ner_spans_set:
                continue
            # Skip junk (terminal artifacts, UUIDs, formatting noise)
            if _is_junk_entity(chunk_text):
                continue

            entities.append({
                "text":  chunk_text,
                "label": "NOUN_CHUNK",
                "start": start,
                "end":   end,
            })

    return parsed, entities
