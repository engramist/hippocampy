"""
Step 7.5 — Lesson Extraction (Opportunistic Learning)

Named IP Claims:
  - Selective Attention (Lessons): Indicator-based trigger for domain-specific insights.
  - Transfer Learning: Lesson nodes enable analogical reasoning across project boundaries.
"""

from __future__ import annotations
from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY
import re
import uuid
import logging
import asyncio
from datetime import datetime, timezone

from campy.brain.hippocampus.graph import embeddings as emb

_logger = logging.getLogger(__name__)

# Lesson indicator patterns (B11)
_LESSON_INDICATORS = [
    r"\bwe learned\b", r"\bnext time\b", r"\bfor future\b", r"\bavoid\b",
    r"\bbest practice\b", r"\bpattern is\b", r"\blesson learned\b",
    r"\bkey takeaway\b", r"\bin the future\b", r"\bimportant to note\b",
]

async def extract_lessons(message_id: str, text: str, db, llm_client,
                          config: dict, session_id: str = "unknown") -> list[str]:
    """
    Scan for lesson indicators in text. If found, use LLM to extract
    structured Lesson nodes.

    Returns list of stored lesson IDs (empty list if none were stored).
    """
    text_lower = text.lower()
    if not any(re.search(p, text_lower) for p in _LESSON_INDICATORS):
        return []

    if llm_client is None:
        _logger.debug("extract_lessons: No LLM client available for extraction")
        return []

    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    prompt = (
        "Identify any domain-specific lessons or best practices in this text.\n"
        "A lesson is a reusable insight that survived an attempt or edge case.\n\n"
        f"Text: {text}\n\n"
        "Return JSON list of objects:\n"
        '[{"text": "...", "domain": "...", "type": "mistake|edge-case|optimization|architecture-principle"}]\n'
        "If no lessons found, return []"
    )

    try:
        import json as _json
        messages = [{"role": "user", "content": prompt}]
        if hasattr(llm_client, "achat"):
            response_text = await llm_client.achat(messages)
        else:
            response_text = await asyncio.to_thread(llm_client.chat, messages)
        
        # Basic JSON extraction
        match = re.search(r"\[.*\]", response_text, re.DOTALL)
        if match:
            candidates = _json.loads(match.group(0))
        else:
            candidates = []
            
        if not isinstance(candidates, list):
            candidates = []

        stored_ids = []
        now = datetime.now(timezone.utc).isoformat()

        for cand in candidates:
            lesson_text = cand.get("text", "").strip()
            if not lesson_text:
                continue
                
            domain = cand.get("domain", "generic").strip()
            lesson_type = cand.get("type", "optimization").strip()
            
            # Embed and store
            vector = await asyncio.to_thread(emb.embed, lesson_text, embedding_model)
            lesson_id = str(uuid.uuid4())
            
            gw = GraphGateway(db, REGISTRY) if not isinstance(db, GraphGateway) else db
            await gw.run(
                "orchestrator.create_lesson",
                {
                    "lesson_id":       lesson_id,
                    "text_raw":        lesson_text,
                    "embedding":       vector,
                    "embedding_model": embedding_model,
                    "embedding_dim":   len(vector),
                    "domain":          domain,
                    "lesson_type":     lesson_type,
                    "created_at":      now,
                },
            )
            
            # Links
            # (Message)-[CONTAINS_LESSON]->(Lesson)
            await gw.run(
                "orchestrator.link_message_contains_lesson",
                {"mid": message_id, "lid": lesson_id},
            )
            
            # (Session)-[LEARNED]->(Lesson)
            if session_id != "unknown":
                await gw.run(
                    "orchestrator.link_session_learned_lesson",
                    {"sid": session_id, "lid": lesson_id},
                )
            
            stored_ids.append(lesson_id)

        return stored_ids

    except Exception as e:
        _logger.exception("extract_lessons failed: %s", e)
        return []
