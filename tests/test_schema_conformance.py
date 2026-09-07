"""
tests/test_schema_conformance.py — Tests for B406 Schema Conformance Guard.

Verifies:
1. get_all_table_properties() derives all node/rel properties including migrations.
2. scan_all_violations() detects all six confirmed bugs from B406.
3. Valid schema properties produce zero false positives.
4. Baseline file is in sync with the codebase.
"""

from __future__ import annotations



from campy.brain.hippocampus.schema import (
    CONTENT_HASH_TABLES,
    NODE_TABLES,
    PROVENANCE_TABLES,
    get_all_table_properties,
    get_relationship_types,
)
from scripts.check_schema_conformance import (
    BASELINE_PATH,
    clean_cypher,
    load_baseline,
    scan_all_violations,
    scan_query_violations,
)


def test_get_all_table_properties_coverage() -> None:
    """Ensure all 57 node tables and 110 relationship tables are resolved."""
    props = get_all_table_properties()

    # All NODE_TABLES must be present
    for node_table in NODE_TABLES:
        assert node_table in props, f"Missing node table: {node_table}"
        assert len(props[node_table]) > 0, f"Empty properties for node table: {node_table}"

    # All unique relationship types must be present
    rel_types = set(get_relationship_types())
    for rel_type in rel_types:
        assert rel_type in props, f"Missing rel table: {rel_type}"

    # Verify comprehension-generated migrations
    for t in PROVENANCE_TABLES:
        assert "authority" in props[t], f"{t} missing 'authority' from B313 comprehension"
        assert "source_version" in props[t], f"{t} missing 'source_version' from B312 comprehension"
        assert "observed_at" in props[t], f"{t} missing 'observed_at' from B312 comprehension"

    # Verify content_hash is present on CONTENT_HASH_TABLES but not on Tier 2 Arc* tables
    for t in CONTENT_HASH_TABLES:
        assert "content_hash" in props[t], f"{t} missing 'content_hash' from B320 comprehension"

    assert "content_hash" not in props["ArcMechanic"]
    assert "content_hash" not in props["ArcActionPattern"]

    # Verify HAS_ALT_LABEL has no properties in schema
    assert props["HAS_ALT_LABEL"] == set(), "HAS_ALT_LABEL must have no declared properties"

    # Verify Concept has last_accessed_at, but Decision does not
    assert "last_accessed_at" in props["Concept"]
    assert "last_accessed_at" not in props["Decision"]


def test_six_confirmed_bugs_detected() -> None:
    """Verify that all six confirmed bugs cited in B406 are detected."""
    schema_props = get_all_table_properties()
    violations = scan_all_violations(schema_props)
    v_map = {(v.query, v.table, v.property): v for v in violations}

    # 1. sweep.py: GlobalConstraint.constraint_id (valid: global_constraint_id)
    assert (
        "sweep.unwind_archive_globalconstraint",
        "GlobalConstraint",
        "constraint_id",
    ) in v_map, "Failed to detect GlobalConstraint.constraint_id in sweep.unwind_archive_globalconstraint"

    # 2. sweep.py: GlobalPreference.pref_id (valid: global_preference_id)
    assert (
        "sweep.get_active_pathway_globalpreference",
        "GlobalPreference",
        "pref_id",
    ) in v_map, "Failed to detect GlobalPreference.pref_id in sweep.get_active_pathway_globalpreference"

    # 3. sweep.py: Requirement.req_id (valid: requirement_id)
    assert (
        "sweep.get_active_pathway_requirement",
        "Requirement",
        "req_id",
    ) in v_map, "Failed to detect Requirement.req_id in sweep.get_active_pathway_requirement"

    # 4. quests.py: HAS_ALT_LABEL.created_at (valid: edge has no properties)
    assert (
        "quests.link_concept_has_alt_label",
        "HAS_ALT_LABEL",
        "created_at",
    ) in v_map, "Failed to detect HAS_ALT_LABEL.created_at in quests.link_concept_has_alt_label"

    # 5. retrieval.py: Message.content (valid: text_raw)
    assert (
        "retrieval.get_originating_message_concept",
        "Message",
        "content",
    ) in v_map, "Failed to detect Message.content in retrieval.get_originating_message_concept"

    # 6. thalamus.py: Concept.prefLabel / Concept.altLabel
    assert (
        "thalamus.file_bridge_concepts",
        "Concept",
        "prefLabel",
    ) in v_map, "Failed to detect Concept.prefLabel in thalamus.file_bridge_concepts"
    assert (
        "thalamus.file_bridge_concepts",
        "Concept",
        "altLabel",
    ) in v_map, "Failed to detect Concept.altLabel in thalamus.file_bridge_concepts"


def test_zero_false_positives_on_valid_properties() -> None:
    """Confirm valid fields from DDL and migrations produce zero violations."""
    schema_props = get_all_table_properties()

    # Synthetic queries accessing valid comprehension and migration properties
    valid_queries = [
        (
            "test.concept_provenance",
            "MATCH (c:Concept) WHERE c.authority = 'earned' AND c.content_hash = '123' "
            "RETURN c.concept_id, c.last_accessed_at, c.source, c.source_version",
        ),
        (
            "test.procedure_trigger",
            "MATCH (p:Procedure) RETURN p.trigger_pattern, p.trigger_hook_type, "
            "p.trigger_tool, p.trigger_project_scope, p.maturity_stage",
        ),
        (
            "test.workspace_continuity",
            "MATCH (w:Workspace) WHERE w.active = true RETURN w.branch_name, w.workspace_id",
        ),
        (
            "test.session_app_id",
            "MATCH (s:Session) RETURN s.external_app_id, s.external_session_id, s.loaded_node_count",
        ),
        (
            "test.dataset_source_key",
            "MATCH (d:Dataset) RETURN d.source_key, d.storage_uri",
        ),
        (
            "test.warm_node_rel",
            "MATCH (s:Session)-[r:WARM_NODE]->(c:Concept) RETURN r.activation_score, r.activated_at",
        ),
    ]

    for qname, cypher in valid_queries:
        violations = scan_query_violations(qname, cypher, schema_props)
        assert violations == [], f"Expected zero violations for valid query {qname}, got: {violations}"


def test_clean_cypher() -> None:
    """Verify comment stripping and string literal masking."""
    cypher = """
    // Line comment
    /* Block comment
       across lines */
    MATCH (c:Concept {concept_id: $cid})
    WHERE c.text_raw = "literal \\"string\\"" AND c.source = 'another \'string\''
    RETURN c.concept_id
    """
    cleaned = clean_cypher(cypher)
    assert "// Line comment" not in cleaned
    assert "Block comment" not in cleaned
    assert "literal" not in cleaned
    assert "another" not in cleaned
    assert "MATCH (c:Concept {concept_id: $cid})" in cleaned


def test_baseline_file_in_sync() -> None:
    """Verify checked-in baseline file matches scanner output."""
    assert BASELINE_PATH.exists(), "schema_conformance_baseline.json does not exist"
    baseline = load_baseline(BASELINE_PATH)
    schema_props = get_all_table_properties()
    violations = scan_all_violations(schema_props)

    baseline_keys = {(v["query"], v["table"], v["property"]) for v in baseline.get("violations", [])}
    current_keys = {(v.query, v.table, v.property) for v in violations}

    new_violations = current_keys - baseline_keys
    assert not new_violations, f"Found unrecorded violations: {new_violations}"

    missing_violations = baseline_keys - current_keys
    assert not missing_violations, (
        f"Baseline contains {len(missing_violations)} resolved violations! "
        f"Run 'python3 scripts/check_schema_conformance.py --update' to lower the baseline."
    )

    assert len(violations) == baseline.get("total_violations")
