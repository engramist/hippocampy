from __future__ import annotations

from campy.brain.hippocampus.schema import NODE_TABLES
from campy.brain.hippocampus.table_registry import get_registry, tables_with


def test_every_embedding_table_registered() -> None:
    registry = get_registry()
    for name, ddl in NODE_TABLES.items():
        has_embedding = "embedding     FLOAT" in ddl or "embedding      FLOAT" in ddl or "embedding       FLOAT" in ddl or "embedding FLOAT" in ddl
        if has_embedding:
            assert name in registry
            assert registry[name].has_embedding is True
            assert registry[name].vector_index == f"{name.lower()}_emb_idx"


def test_sweep_tables_match_legacy_literal() -> None:
    expected = [
        ("Concept", "concept_id", "concept", "concept_emb_idx"),
        ("GlobalConstraint", "global_constraint_id", "global_constraint", "globalconstraint_emb_idx"),
        ("GlobalPreference", "global_preference_id", "global_preference", "globalpreference_emb_idx"),
        ("Decision", "decision_id", "decision", "decision_emb_idx"),
        ("Constraint", "constraint_id", "constraint", "constraint_emb_idx"),
        ("Requirement", "requirement_id", "requirement", "requirement_emb_idx"),
        ("ActionItem", "action_item_id", "action_item", "actionitem_emb_idx"),
        ("Message", "message_id", "message", "message_emb_idx"),
        ("DocumentExtract", "extract_id", "document_extract", "documentextract_emb_idx"),
    ]
    actual = [
        (table.name, table.pk, table.name if table.name.islower() else None, table.vector_index)
        for table in []
    ]
    actual = []
    for table in tables_with("sweepable"):
        parts = []
        for char in table.name:
            if parts and char.isupper():
                parts.append("_")
            parts.append(char.lower())
        actual.append((table.name, table.pk, "".join(parts), table.vector_index))
    assert actual == expected


def test_explore_tables_match_legacy_literal() -> None:
    expected = [
        ("Concept", "concept_id"),
        ("Decision", "decision_id"),
        ("Constraint", "constraint_id"),
        ("Requirement", "requirement_id"),
        ("ActionItem", "action_item_id"),
        ("GlobalConstraint", "global_constraint_id"),
        ("GlobalPreference", "global_preference_id"),
        ("MainQuest", "quest_id"),
        ("SideQuest", "quest_id"),
        ("Message", "message_id"),
        ("Document", "document_id"),
        ("Lesson", "lesson_id"),
    ]
    actual = [(table.name, table.pk) for table in tables_with("traversable")]
    assert actual == expected


def test_warm_pk_map_matches_legacy_literal() -> None:
    expected = {
        "Concept": "concept_id",
        "Decision": "decision_id",
        "Constraint": "constraint_id",
        "Requirement": "requirement_id",
        "ActionItem": "action_item_id",
        "GlobalConstraint": "global_constraint_id",
        "GlobalPreference": "global_preference_id",
    }
    actual = {table.name: table.pk for table in tables_with("warmable")}
    assert actual == expected


def test_retrievable_matches_current_truth_literal() -> None:
    expected = [
        ("Concept", "concept_emb_idx", "concept_id"),
        ("Decision", "decision_emb_idx", "decision_id"),
        ("Constraint", "constraint_emb_idx", "constraint_id"),
        ("Requirement", "requirement_emb_idx", "requirement_id"),
        ("ActionItem", "actionitem_emb_idx", "action_item_id"),
        ("GlobalConstraint", "globalconstraint_emb_idx", "global_constraint_id"),
        ("GlobalPreference", "globalpreference_emb_idx", "global_preference_id"),
        ("Lesson", "lesson_emb_idx", "lesson_id"),
        ("Message", "message_emb_idx", "message_id"),
        ("DocumentExtract", "documentextract_emb_idx", "extract_id"),
    ]
    actual = [
        (table.name, table.vector_index, table.pk)
        for table in tables_with("retrievable")
    ]
    assert actual == expected


def test_pk_parsed_for_all_tables() -> None:
    registry = get_registry()
    assert set(registry) == set(NODE_TABLES)
    for name, table in registry.items():
        assert table.pk
        assert table.name == name