"""Step 1 — Zoning / NER (spaCy). Zero LLM cost."""

import re
import spacy

_nlp = None


def get_nlp(model_name: str = "en_core_web_md"):
    global _nlp
    if _nlp is None:
        _nlp = spacy.load(model_name)
    return _nlp


# Pronouns and stopwords to filter from noun chunk fallback
_SKIP_CHUNKS = {"we", "i", "you", "they", "he", "she", "it", "us", "them",
                "this", "that", "these", "those", "one", "ones"}

# UUID pattern: 32+ hex chars optionally separated by hyphens
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
)
# Hex hash pattern: 32+ contiguous hex chars
_HEX_HASH_RE = re.compile(r'^[0-9a-f]{32,}$', re.I)


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

    # Contains box-drawing or block element Unicode characters (terminal UI noise)
    if any('\u2500' <= c <= '\u257f' or '\u2580' <= c <= '\u259f' for c in stripped):
        return True

    # Mostly non-alphanumeric (less than 50% alnum)
    alnum_ratio = sum(1 for c in stripped if c.isalnum()) / len(stripped)
    if alnum_ratio < 0.5:
        return True

    # Contains control characters or raw newlines (check before strip)
    if any(c in text for c in '\n\r\x00'):
        return True

    return False


def extract_entities(text: str, model_name: str = "en_core_web_md") -> tuple:
    """
    Run spaCy NER + dependency parse on text.
    Returns (doc, entities) where entities is a list of dicts.
    doc is kept for Step 1b (dep parser reuses it — no double parse).

    Falls back to noun chunk extraction when NER finds few entities.
    spaCy NER misses most software/tech terms (PostgreSQL, MySQL, React, etc.)
    since they aren't people, places, or organizations. Noun chunks catch them.
    """
    nlp = get_nlp(model_name)
    doc = nlp(text)

    entities = [
        {
            "text":  ent.text,
            "label": ent.label_,   # PERSON, ORG, PRODUCT, GPE, DATE, CARDINAL, etc.
            "start": ent.start_char,
            "end":   ent.end_char,
        }
        for ent in doc.ents
        if not _is_junk_entity(ent.text)
    ]

    # Noun chunk fallback: if NER found <=1 entity, supplement with noun chunks.
    # Technical conversations mention tools/frameworks/concepts that spaCy NER
    # doesn't recognize but noun chunking captures reliably.
    if len(entities) <= 1:
        ner_spans = {(e["start"], e["end"]) for e in entities}
        for chunk in doc.noun_chunks:
            # Skip pronouns and trivial stopwords
            if chunk.text.lower().strip() in _SKIP_CHUNKS:
                continue
            # Skip chunks already covered by NER
            if (chunk.start_char, chunk.end_char) in ner_spans:
                continue
            # Skip junk (terminal artifacts, UUIDs, formatting noise)
            if _is_junk_entity(chunk.text):
                continue
            entities.append({
                "text":  chunk.text,
                "label": "NOUN_CHUNK",
                "start": chunk.start_char,
                "end":   chunk.end_char,
            })

    return doc, entities
