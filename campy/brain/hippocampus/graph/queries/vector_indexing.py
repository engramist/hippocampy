"""B454: vector/FTS indexing for `sparql=` node-create queries.

`sparql=` creates route straight to `OxigraphClient.execute_write()` and bypass
`OxigraphClient.write_node()` -- the only place that populates the sqlite-vec
vector store and its FTS5 text index. B418 re-attached indexing for exactly one
query (`lessons.create_lesson`); every other node-create kept silently skipping
it, so since the SPARQL cutover new Concepts / Decisions / Constraints /
Messages were unreachable by similarity or lexical search (measured live: 5 of
400 Concepts and 0 of 82 Decisions had an embedding).

This table is the single source of truth: `(table, pk_param, emb_param,
text_param)` per query name. `apply_vector_index_specs` attaches a
`VectorIndexSpec` to each; `tests/test_b454_vector_indexing.py` fails if a new
embedding-carrying node-create appears without an entry (or an explicit
exemption).
"""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import QueryRegistry, VectorIndexSpec
from campy.brain.hippocampus.graph.oxigraph_client import NODE_PRIMARY_KEYS

# query name -> (table, pk_param, emb_param, text_param | None)
_SPECS: dict[str, tuple[str, str, str, str | None]] = {
    "lessons.create_plan":                     ("Plan", "plan_id", "embedding", None),
    "lessons.create_plan_step":                ("PlanStep", "step_id", "embedding", None),
    "lessons.create_plan_outcome_lesson":      ("Lesson", "lesson_id", "embedding", "text_raw"),
    "lessons.create_quest_synthesis_lesson":   ("Lesson", "lesson_id", "embedding", "text_raw"),
    "capability.create_fact_entity":           ("FactEntity", "entity_id", "embedding", None),
    "quests.create_main_quest":                ("MainQuest", "quest_id", "embedding", "name"),
    "quests.create_side_quest":                ("SideQuest", "quest_id", "embedding", "text_raw"),
    "sweep.create_retrospective_plan":         ("Plan", "plan_id", "embedding", None),
    "sweep.create_plan_step":                  ("PlanStep", "step_id", "embedding", None),
    "sweep.create_synthesized_lesson":         ("Lesson", "lid", "embedding", "text_raw"),
    "sweep.patterns_create_procedure":         ("Procedure", "pid", "embedding", None),
    "orchestrator.create_concept":             ("Concept", "concept_id", "embedding", "text_raw"),
    "orchestrator.create_minimal_concept":     ("Concept", "concept_id", "embedding", "text_raw"),
    "orchestrator.create_gist_example":        ("GistExample", "example_id", "embedding", None),
    "orchestrator.create_lesson":              ("Lesson", "lesson_id", "embedding", "text_raw"),
    "orchestrator.create_artifact_decision":   ("Decision", "artifact_id", "embedding", "text_raw"),
    "orchestrator.create_artifact_constraint": ("Constraint", "artifact_id", "embedding", "text_raw"),
    "orchestrator.create_artifact_requirement": ("Requirement", "artifact_id", "embedding", "text_raw"),
    "orchestrator.create_artifact_actionitem": ("ActionItem", "artifact_id", "embedding", "text_raw"),
    "capture.create_message":                  ("Message", "message_id", "embedding", "text_raw"),
    "ingest.create_document_extract":          ("DocumentExtract", "extract_id", "embedding", "text_raw"),
    "ingest.create_fact_concept":              ("Concept", "concept_id", "embedding", "text_raw"),
    "ingest.create_dataset_node":              ("Dataset", "dataset_id", "embedding", None),
    "basal_ganglia.synthesis_create_procedure":  ("Procedure", "pid", "embedding", None),
    "basal_ganglia.frustration_create_procedure": ("Procedure", "pid", "embedding", None),
    "temporal_lobe.dict_create_concept":       ("Concept", "cid", "emb", "text"),
    "temporal_lobe.dict_create_pref_label":    ("Label", "lid", "emb", "txt"),
    "temporal_lobe.dict_create_alt_label":     ("Label", "lid", "emb", "txt"),
}

VECTOR_INDEX_SPECS: dict[str, VectorIndexSpec] = {
    name: VectorIndexSpec(
        table=table, pk_col=NODE_PRIMARY_KEYS[table], pk_param=pk_param,
        emb_param=emb_param, text_param=text_param,
    )
    for name, (table, pk_param, emb_param, text_param) in _SPECS.items()
}

# Node-creates that carry an embedding param but must NOT be indexed here.
# Each entry needs a reason; the conformance test rejects an empty one.
EXEMPT: dict[str, str] = {}


def apply_vector_index_specs(registry: QueryRegistry) -> None:
    for name, spec in VECTOR_INDEX_SPECS.items():
        registry.attach_vector_index(name, spec)
