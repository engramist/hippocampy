"""
campy/brain/hippocampus/graph/queries/backup.py — B319 named-query slice.

`campy/cli/backup.py`'s `backup verify` step 4 ("run one real recall query
against the restored graph and assert it returns results") needs a query
whose Cypher lives somewhere the B314 ratchet (`scripts/check_cypher_ratchet.py`)
does not count against `campy/cli/backup.py` — this module is that place
(the whole `graph/queries/` directory is allowlisted; that's where migrated
Cypher is supposed to live).

The query is a small, table-name-agnostic lexical smoke test: does the
restored graph contain *any* live (non-archived) earned-fact row across the
three most common Tier 1 fact-bearing tables? It is deliberately not a full
recall/ranking pipeline (`current_truth` et al.) — verify's job is "prove
the restored database is genuinely queryable and holds real content," not
re-run retrieval ranking against a throwaway database.
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import NamedQuery

BACKUP_QUERIES: tuple[NamedQuery, ...] = (
    NamedQuery(
        name="backup.recall_sample",
        cypher="""
            MATCH (n:Concept)
            WHERE n.archived = false OR n.archived IS NULL
            RETURN 'Concept' AS table_name, n.concept_id AS node_id, n.text_raw AS text_raw
            UNION ALL
            MATCH (n:Decision)
            WHERE n.archived = false OR n.archived IS NULL
            RETURN 'Decision' AS table_name, n.decision_id AS node_id, n.text_raw AS text_raw
            UNION ALL
            MATCH (n:Lesson)
            WHERE n.archived = false OR n.archived IS NULL
            RETURN 'Lesson' AS table_name, n.lesson_id AS node_id, n.text_raw AS text_raw
            LIMIT 5
            """,
        params=(),
        mutating=False,
        description=(
            "backup verify's post-restore smoke test: any live Concept/Decision/Lesson "
            "row, proving the restored database is queryable and holds real content."
        ),
    ),
)
