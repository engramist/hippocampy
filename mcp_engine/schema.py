"""
mcp_engine/schema.py — Kùzu Schema Initialization

Run once at Brain Daemon startup (idempotent — uses IF NOT EXISTS throughout).
Creates all node/relationship tables, seeds ontology, bootstraps gist centroids.
"""

from __future__ import annotations
import re
from pathlib import Path

from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.graph import embeddings as emb

# ---------------------------------------------------------------------------
# Node table DDL
# ---------------------------------------------------------------------------

NODE_TABLES = {
    "Concept": """
        concept_id    STRING,
        text_raw      STRING,
        embedding     FLOAT[384],
        embedding_model STRING,
        embedding_dim INT64,
        gist_class    STRING,
        schema_org_type STRING,
        confidence    DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived      BOOLEAN,
        anomaly_type  STRING,
        flagged_for_review BOOLEAN,
        created_at    TIMESTAMP,
        last_accessed_at TIMESTAMP,
        PRIMARY KEY (concept_id)
    """,

    "Decision": """
        decision_id   STRING,
        text_raw      STRING,
        embedding     FLOAT[384],
        embedding_model STRING,
        embedding_dim INT64,
        confidence    DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived      BOOLEAN,
        anomaly_type  STRING,
        flagged_for_review BOOLEAN,
        created_at    TIMESTAMP,
        PRIMARY KEY (decision_id)
    """,

    "Constraint": """
        constraint_id STRING,
        text_raw      STRING,
        embedding     FLOAT[384],
        embedding_model STRING,
        embedding_dim INT64,
        confidence    DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived      BOOLEAN,
        anomaly_type  STRING,
        flagged_for_review BOOLEAN,
        created_at    TIMESTAMP,
        PRIMARY KEY (constraint_id)
    """,

    "Requirement": """
        requirement_id STRING,
        text_raw       STRING,
        embedding      FLOAT[384],
        embedding_model STRING,
        embedding_dim  INT64,
        confidence     DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived       BOOLEAN,
        anomaly_type   STRING,
        flagged_for_review BOOLEAN,
        created_at     TIMESTAMP,
        PRIMARY KEY (requirement_id)
    """,

    "ActionItem": """
        action_item_id STRING,
        text_raw       STRING,
        embedding      FLOAT[384],
        embedding_model STRING,
        embedding_dim  INT64,
        confidence     DOUBLE,
        confidence_low BOOLEAN,
        pathway_strength DOUBLE,
        archived       BOOLEAN,
        anomaly_type   STRING,
        flagged_for_review BOOLEAN,
        created_at     TIMESTAMP,
        PRIMARY KEY (action_item_id)
    """,

    "GlobalConstraint": """
        global_constraint_id STRING,
        text_raw             STRING,
        embedding            FLOAT[384],
        embedding_model      STRING,
        embedding_dim        INT64,
        confidence           DOUBLE,
        confidence_low       BOOLEAN,
        pathway_strength     DOUBLE,
        archived             BOOLEAN,
        anomaly_type         STRING,
        flagged_for_review   BOOLEAN,
        created_at           TIMESTAMP,
        PRIMARY KEY (global_constraint_id)
    """,

    "GlobalPreference": """
        global_preference_id STRING,
        text_raw             STRING,
        embedding            FLOAT[384],
        embedding_model      STRING,
        embedding_dim        INT64,
        confidence           DOUBLE,
        confidence_low       BOOLEAN,
        pathway_strength     DOUBLE,
        archived             BOOLEAN,
        anomaly_type         STRING,
        flagged_for_review   BOOLEAN,
        created_at           TIMESTAMP,
        PRIMARY KEY (global_preference_id)
    """,

    "MainQuest": """
        quest_id        STRING,
        name            STRING,
        status          STRING,
        completed_at    TIMESTAMP,
        purpose         STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        created_at      TIMESTAMP,
        last_active_at  TIMESTAMP,
        git_repo_root       STRING,
        purpose_embedding   FLOAT[384],
        routing_method      STRING,
        PRIMARY KEY (quest_id)
    """,

    "SideQuest": """
        quest_id        STRING,
        name            STRING,
        status          STRING,
        completed_at    TIMESTAMP,
        purpose         STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        created_at      TIMESTAMP,
        PRIMARY KEY (quest_id)
    """,

    "Document": """
        document_id      STRING,
        location_uri     STRING,
        content_hash     STRING,
        last_modified_at TIMESTAMP,
        mime_type        STRING,
        PRIMARY KEY (document_id)
    """,

    "Message": """
        message_id      STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        role            STRING,
        byte_start      INT64,
        byte_end        INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        anomaly_type    STRING,
        flagged_for_review BOOLEAN,
        created_at      TIMESTAMP,
        PRIMARY KEY (message_id)
    """,

    "DocumentExtract": """
        extract_id      STRING,
        text_raw        STRING,
        embedding       FLOAT[384],
        embedding_model STRING,
        embedding_dim   INT64,
        byte_start      INT64,
        byte_end        INT64,
        line_start      INT64,
        line_end        INT64,
        confidence      DOUBLE,
        confidence_low  BOOLEAN,
        pathway_strength DOUBLE,
        archived        BOOLEAN,
        anomaly_type    STRING,
        flagged_for_review BOOLEAN,
        created_at      TIMESTAMP,
        PRIMARY KEY (extract_id)
    """,

    "Session": """
        session_id           STRING,
        started_at           TIMESTAMP,
        last_active_at       TIMESTAMP,
        onboarded            BOOLEAN,
        purpose              STRING,
        routing_state        STRING,
        routing_confidence   DOUBLE,
        routing_method       STRING,
        token_estimate       INT64,
        token_limit          INT64,
        loaded_node_count    INT32,
        injection_count      INT64,
        dedup_tokens_saved   INT64,
        last_injection_at    TIMESTAMP,
        last_loop_summary    STRING,
        last_warm_frontier_at TIMESTAMP,
        PRIMARY KEY (session_id)
    """,

    "LLMProvider": """
        provider_id   STRING,
        provider_name STRING,
        model_name    STRING,
        is_local      BOOLEAN,
        context_window INT64,
        PRIMARY KEY (provider_id)
    """,

    "Workspace": """
        workspace_id STRING,
        path         STRING,
        os           STRING,
        hostname     STRING,
        PRIMARY KEY (workspace_id)
    """,

    "GistClass": """
        name     STRING,
        centroid FLOAT[384],
        PRIMARY KEY (name)
    """,

    "GistExample": """
        example_id  STRING,
        text        STRING,
        embedding   FLOAT[384],
        gist_class  STRING,
        source      STRING,
        created_at  TIMESTAMP,
        PRIMARY KEY (example_id)
    """,

    "SchemaOrgType": """
        name       STRING,
        properties STRING[],
        PRIMARY KEY (name)
    """,

    "Label": """
        label_id   STRING,
        text       STRING,
        embedding  FLOAT[384],
        language   STRING,
        label_type STRING,
        confidence DOUBLE,
        source     STRING,
        created_at TIMESTAMP,
        PRIMARY KEY (label_id)
    """,

    "MergeEvent": """
        merge_event_id       STRING,
        pre_pathway_strength DOUBLE,
        delta_pathway_strength DOUBLE,
        alias_added          STRING[],
        metadata_patch       STRING,
        created_at           TIMESTAMP,
        PRIMARY KEY (merge_event_id)
    """,

    # B11 — Lesson node (synthesized at quest completion, feeds analogical reasoning)
    "Lesson": """
        lesson_id        STRING,
        text_raw         STRING,
        embedding        FLOAT[384],
        embedding_model  STRING,
        embedding_dim    INT64,
        domain           STRING,
        lesson_type      STRING,
        confidence       DOUBLE,
        confidence_low   BOOLEAN,
        pathway_strength DOUBLE,
        archived         BOOLEAN,
        created_at       TIMESTAMP,
        PRIMARY KEY (lesson_id)
    """,

    # B66 — Plan/PlanStep (active agent planning graph)
    "Plan": """
        plan_id          STRING,
        goal             STRING,
        strategy         STRING,
        source           STRING,
        embedding        FLOAT[384],
        embedding_model  STRING,
        embedding_dim    INT64,
        step_count       INT64,
        valence          DOUBLE,
        valence_source   STRING,
        status           STRING,
        confidence       DOUBLE,
        confidence_low   BOOLEAN,
        pathway_strength DOUBLE,
        archived         BOOLEAN,
        created_at       TIMESTAMP,
        completed_at     TIMESTAMP,
        PRIMARY KEY (plan_id)
    """,

    "PlanStep": """
        step_id           STRING,
        step_number       INT64,
        description       STRING,
        embedding         FLOAT[384],
        embedding_model   STRING,
        embedding_dim     INT64,
        expected_outcome  STRING,
        actual_outcome    STRING,
        valence           DOUBLE,
        status            STRING,
        created_at        TIMESTAMP,
        completed_at      TIMESTAMP,
        PRIMARY KEY (step_id)
    """,

    # B88 — Hypothesis (ARC agent systematic exploration)
    "Hypothesis": """
        id               STRING,
        description      STRING,
        category         STRING,
        confidence       FLOAT,
        game_type        STRING,
        task_id          STRING,
        status           STRING,
        evidence_count   INT32,
        text_raw         STRING,
        embedding        FLOAT[384],
        created_at       TIMESTAMP,
        PRIMARY KEY (id)
    """,

    # B127 — DAG Task Graph (dependency-aware execution tracking)
    "TaskGraph": """
        graph_id        STRING,
        name            STRING,
        description     STRING,
        status          STRING,
        created_at      TIMESTAMP,
        completed_at    TIMESTAMP,
        PRIMARY KEY (graph_id)
    """,

    "TaskNode": """
        task_id         STRING,
        name            STRING,
        description     STRING,
        status          STRING,
        input_data      STRING,
        output_data     STRING,
        error_msg       STRING,
        created_at      TIMESTAMP,
        started_at      TIMESTAMP,
        completed_at    TIMESTAMP,
        PRIMARY KEY (task_id)
    """,
}

# ---------------------------------------------------------------------------
# Relationship table DDL
# ---------------------------------------------------------------------------

REL_TABLES = [
    # Quest structure
    "CREATE REL TABLE IF NOT EXISTS BELONGS_TO (FROM SideQuest TO MainQuest)",
    "CREATE REL TABLE IF NOT EXISTS ANCHORED_TO (FROM MainQuest TO Workspace)",
    # Document provenance
    "CREATE REL TABLE IF NOT EXISTS DERIVED_FROM (FROM DocumentExtract TO Document)",
    "CREATE REL TABLE IF NOT EXISTS ESTABLISHED (FROM Message TO Decision, FROM Message TO Constraint, FROM DocumentExtract TO Decision, FROM DocumentExtract TO Constraint)",
    # Audit trail
    "CREATE REL TABLE IF NOT EXISTS DEPRECATED_BY (FROM Concept TO Concept, FROM Decision TO Decision, FROM Constraint TO Constraint)",
    "CREATE REL TABLE IF NOT EXISTS TRIGGERED (FROM Message TO MergeEvent)",
    "CREATE REL TABLE IF NOT EXISTS UPDATES_PATHWAY (FROM MergeEvent TO Concept)",
    # Session provenance
    "CREATE REL TABLE IF NOT EXISTS USED (FROM Session TO LLMProvider)",
    "CREATE REL TABLE IF NOT EXISTS IN_WORKSPACE (FROM Session TO Workspace)",
    "CREATE REL TABLE IF NOT EXISTS WORKING_ON (FROM Session TO MainQuest, FROM Session TO SideQuest)",
    "CREATE REL TABLE IF NOT EXISTS SENT_IN (FROM Message TO Session)",
    "CREATE REL TABLE IF NOT EXISTS ESTABLISHED_IN (FROM Decision TO Session, FROM Constraint TO Session, FROM Requirement TO Session, FROM ActionItem TO Session)",
    # Ontology routing (core IP — Shape-First Principle)
    "CREATE REL TABLE IF NOT EXISTS ROUTES_TO (FROM GistClass TO SchemaOrgType)",
    # SKOS labels
    "CREATE REL TABLE IF NOT EXISTS HAS_PREF_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS HAS_ALT_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS HAS_HIDDEN_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS LOADED (FROM Session TO Concept, FROM Session TO Decision, FROM Session TO Constraint, FROM Session TO Requirement, FROM Session TO ActionItem, FROM Session TO GlobalConstraint, FROM Session TO GlobalPreference, injected_at TIMESTAMP, token_estimate INT32, source STRING, load_hits INT32)",
    "CREATE REL TABLE IF NOT EXISTS WARM_NODE (FROM Session TO Concept, FROM Session TO Decision, FROM Session TO Constraint, FROM Session TO Requirement, FROM Session TO ActionItem, FROM Session TO GlobalConstraint, FROM Session TO GlobalPreference, activation_score DOUBLE, activated_at TIMESTAMP)",
    # Concept promotion
    "CREATE REL TABLE IF NOT EXISTS REIFIED_AS (FROM Concept TO Decision, FROM Concept TO Constraint, FROM Concept TO Requirement, FROM Concept TO ActionItem)",
    # Hebbian implicit layer
    "CREATE REL TABLE IF NOT EXISTS CO_OCCURS_WITH (FROM Concept TO Concept, count INT64, strength DOUBLE)",
    # Named semantic relationships — all Concept→Concept (Shape-First Principle IP)
    "CREATE REL TABLE IF NOT EXISTS REQUIRES     (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS ENABLES      (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS REPLACES     (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS CONTRADICTS  (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS PART_OF      (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS CHOSEN_OVER  (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS   (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS EXTENDS      (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    "CREATE REL TABLE IF NOT EXISTS ALTERNATIVE_TO (FROM Concept TO Concept, confidence DOUBLE, inferred_by STRING, inferred_at TIMESTAMP)",
    # B12 — Anomaly detection
    "CREATE REL TABLE IF NOT EXISTS ANOMALY_DETECTED (FROM Concept TO GlobalConstraint, FROM Concept TO GlobalPreference, FROM Decision TO GlobalConstraint, FROM Constraint TO GlobalConstraint, FROM Requirement TO GlobalConstraint, FROM ActionItem TO GlobalConstraint, FROM Message TO GlobalConstraint, FROM DocumentExtract TO GlobalConstraint, type STRING, confidence DOUBLE, detected_at TIMESTAMP)",
    # B11 — Lesson
    "CREATE REL TABLE IF NOT EXISTS PRODUCED_LESSON (FROM MainQuest TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS LEARNED (FROM Session TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS APPLIES_TO (FROM Lesson TO Concept, FROM Lesson TO Decision, FROM Lesson TO Requirement)",
    "CREATE REL TABLE IF NOT EXISTS RELATED_TO (FROM Lesson TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS CONTAINS_LESSON (FROM Message TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS REROUTED_FROM (FROM Session TO MainQuest, rerouted_at TIMESTAMP, reason STRING)",
    # B66/B69 — active planning + outcome propagation
    "CREATE REL TABLE IF NOT EXISTS PLANNED_IN (FROM Plan TO Session)",
    "CREATE REL TABLE IF NOT EXISTS TARGETS (FROM Plan TO MainQuest, FROM Plan TO SideQuest)",
    "CREATE REL TABLE IF NOT EXISTS STEP_OF (FROM PlanStep TO Plan)",
    "CREATE REL TABLE IF NOT EXISTS NEXT_STEP (FROM PlanStep TO PlanStep)",
    "CREATE REL TABLE IF NOT EXISTS ACTS_ON (FROM PlanStep TO Concept)",
    "CREATE REL TABLE IF NOT EXISTS PRODUCED_PLAN_LESSON (FROM Plan TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS OUTCOME_SIGNAL (FROM PlanStep TO Concept, valence DOUBLE, plan_id STRING, observed_at TIMESTAMP)",
    # B88 — Hypothesis engine
    "CREATE REL TABLE IF NOT EXISTS HYPOTHESIZED_IN (FROM Hypothesis TO Session)",
    "CREATE REL TABLE IF NOT EXISTS CONFIRMS (FROM Concept TO Hypothesis, weight FLOAT)",
    "CREATE REL TABLE IF NOT EXISTS CONTRADICTS (FROM Concept TO Hypothesis, weight FLOAT)",
    "CREATE REL TABLE IF NOT EXISTS GENERALIZES (FROM Hypothesis TO Hypothesis)",
    "CREATE REL TABLE IF NOT EXISTS PRODUCED_HYPOTHESIS (FROM Plan TO Hypothesis)",
    # B127 — DAG task graph
    "CREATE REL TABLE IF NOT EXISTS TASK_OF (FROM TaskNode TO TaskGraph)",
    "CREATE REL TABLE IF NOT EXISTS DEPENDS_ON (FROM TaskNode TO TaskNode)",
]

def get_relationship_types() -> list[str]:
    """Parse REL_TABLES to extract all relationship table names."""
    rels = []
    for ddl in REL_TABLES:
        # Match 'CREATE REL TABLE IF NOT EXISTS NAME' or 'CREATE REL TABLE NAME'
        match = re.search(r"CREATE REL TABLE (?:IF NOT EXISTS )?(\w+)", ddl)
        if match:
            rels.append(match.group(1))
    return rels


# ---------------------------------------------------------------------------
# Ontology seed data (gist → schema.org routing table — core IP)
# ---------------------------------------------------------------------------

ROUTING_TABLE = [
    ("Restriction",   "Demand",             ["eligibleCustomerType", "availability", "validFrom", "validThrough", "businessFunction", "description"]),
    ("PlannedEvent",  "Action",             ["agent", "object", "target", "actionStatus", "startTime", "endTime", "result", "instrument"]),
    ("PhysicalThing", "Product",            ["name", "identifier", "description", "version", "inLanguage", "isAccessoryOrSparePartFor"]),
    ("Magnitude",     "QuantitativeValue",  ["value", "unitCode", "unitText", "minValue", "maxValue", "valueReference"]),
    ("Category",      "DefinedTerm",        ["name", "description", "termCode", "inDefinedTermSet", "sameAs"]),
    ("Agent",         "Person",             ["name", "jobTitle", "description", "email", "knowsAbout"]),
    ("Agent",         "Organization",       ["name", "description", "member", "parentOrganization", "contactPoint"]),
    ("Event",         "Event",              ["name", "startDate", "endDate", "eventStatus", "location", "organizer", "description"]),
]

# ---------------------------------------------------------------------------
# Centroid bootstrap — parse GistSeedExamples.md
# ---------------------------------------------------------------------------

def _parse_seed_examples(seed_path: str) -> dict[str, list[str]]:
    """
    Parse GistSeedExamples.md → {gist_class_name: [sentence, ...]}
    Sections are identified by '## gist:ClassName' headers.
    Examples are numbered lines: '1. "sentence text"'
    """
    text = Path(seed_path).read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current_class = None

    for line in text.splitlines():
        header_match = re.match(r"^## gist:(\w+)", line)
        if header_match:
            current_class = header_match.group(1)
            sections[current_class] = []
            continue

        if current_class:
            example_match = re.match(r'^\d+\.\s+"(.+)"', line)
            if example_match:
                sections[current_class].append(example_match.group(1))

    return sections


def _bootstrap_centroids(db: KuzuClient, seed_path: str,
                          embedding_model: str) -> None:
    """
    Embed all seed examples, compute mean per class, store as GistClass.centroid.
    Idempotent: skips classes whose centroid is already populated (Kùzu 0.11.3
    cannot SET an indexed vector property in-place; we DETACH DELETE + re-CREATE,
    which also removes ROUTES_TO edges — those are re-seeded on next startup via
    the MERGE in step 3 of init_schema).
    """
    print("Bootstrapping gist class centroids from seed examples...")
    examples = _parse_seed_examples(seed_path)

    for class_name, sentences in examples.items():
        if not sentences:
            print(f"  WARNING: No seed examples found for gist:{class_name}")
            continue

        vectors = emb.embed_batch(sentences, model_name=embedding_model)
        centroid = emb.mean_pool(vectors)
        # L1 fix: mean-pooling normalized vectors does NOT yield a normalized
        # vector. L2-normalize the centroid so cosine similarity scores are
        # accurate and System 1 thresholds (0.85) behave as intended.
        norm = sum(v * v for v in centroid) ** 0.5
        if norm > 0:
            centroid = [v / norm for v in centroid]

        # Kùzu 0.11.3: cannot SET a vector property in-place when it's indexed.
        # DETACH DELETE removes ROUTES_TO edges — re-seed them immediately after.
        db.execute("MATCH (g:GistClass {name: $name}) DETACH DELETE g", {"name": class_name})
        db.execute(
            "CREATE (:GistClass {name: $name, centroid: $centroid})",
            {"name": class_name, "centroid": centroid}
        )
        # Re-seed ROUTES_TO edges for this class (DETACH DELETE removed them).
        for g_name, s_name, _props in ROUTING_TABLE:
            if g_name == class_name:
                db.execute(
                    "MATCH (g:GistClass {name: $g}), (s:SchemaOrgType {name: $s}) "
                    "MERGE (g)-[:ROUTES_TO]->(s)",
                    {"g": g_name, "s": s_name}
                )
        print(f"  gist:{class_name} — {len(sentences)} examples, centroid computed")

    print("Centroid bootstrap complete.")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def init_schema(db: KuzuClient, seed_examples_path: str,
                embedding_model: str) -> None:
    """
    Initialize Kùzu schema. Idempotent — safe to call on every daemon startup.

    SC1 note: schema init uses db.execute() (sync, bypasses asyncio write lock)
    because it runs synchronously during startup before the event loop is
    serving requests. The asyncio lock guards concurrent writes between live
    coroutines — schema init is single-threaded and runs first. This is safe
    as long as init_schema() is always called before BrainDaemon.start() hands
    off to asyncio. Do not call init_schema() after the event loop starts.

    Steps:
      1. Validate embedding dimension
      2. Create all node tables (IF NOT EXISTS)
      3. Create all relationship tables (IF NOT EXISTS)
      4. Seed GistClass + SchemaOrgType nodes + ROUTES_TO edges
      5. Bootstrap GistClass centroids from seed examples
      6. Create HNSW vector indexes
    """
    print("Initializing schema...")

    # B76: Dimension validation
    test_vec = emb.embed("dimension validation test", model_name=embedding_model)
    expected_dim = 384  # matches FLOAT[384] in schema
    if len(test_vec) != expected_dim:
        raise ValueError(
            f"Embedding model produces {len(test_vec)} dimensions "
            f"but schema expects {expected_dim}. "
            f"Check config embedding_model setting."
        )
    print(f"  Embedding validation: {expected_dim} dimensions verified.")

    # 1. Node tables
    for table_name, fields in NODE_TABLES.items():
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table_name} ({fields})")
        print(f"  Node table: {table_name}")

    # 1b. Schema migrations — add columns that may be missing from older DBs
    _MIGRATIONS = [
        # (table, column, type) — ALTER TABLE ADD COLUMN IF NOT EXISTS
        ("MainQuest", "git_repo_root",     "STRING"),
        ("MainQuest", "purpose_embedding", "FLOAT[384]"),
        ("MainQuest", "routing_method",    "STRING"),
        ("MainQuest", "last_active_at",    "TIMESTAMP"),
        ("Session",   "routing_state",     "STRING"),
        ("Session",   "routing_confidence", "DOUBLE"),
        ("Session",   "routing_method",    "STRING"),
        ("Session",   "token_estimate",    "INT64"),
        ("Session",   "token_limit",       "INT64"),
        ("Session",   "loaded_node_count", "INT64"),
        # last_injection_at and last_loop_summary added in B18 working_memory
        ("Session",   "last_injection_at", "TIMESTAMP"),
        ("Session",   "last_loop_summary", "STRING"),
        ("Session",   "last_warm_frontier_at", "TIMESTAMP"),
        # B12 — anomaly detection columns
        ("Concept",   "anomaly_type",      "STRING"),
        ("Concept",   "flagged_for_review", "BOOLEAN"),
        ("Decision",  "anomaly_type",      "STRING"),
        ("Decision",  "flagged_for_review", "BOOLEAN"),
        ("Constraint", "anomaly_type",     "STRING"),
        ("Constraint", "flagged_for_review", "BOOLEAN"),
        ("Requirement", "anomaly_type",    "STRING"),
        ("Requirement", "flagged_for_review", "BOOLEAN"),
        ("ActionItem", "anomaly_type",     "STRING"),
        ("ActionItem", "flagged_for_review", "BOOLEAN"),
        ("GlobalConstraint", "anomaly_type", "STRING"),
        ("GlobalConstraint", "flagged_for_review", "BOOLEAN"),
        ("GlobalPreference", "anomaly_type", "STRING"),
        ("GlobalPreference", "flagged_for_review", "BOOLEAN"),
        ("Message",   "anomaly_type",      "STRING"),
        ("Message",   "flagged_for_review", "BOOLEAN"),
        ("DocumentExtract", "anomaly_type", "STRING"),
        ("DocumentExtract", "flagged_for_review", "BOOLEAN"),

        # B64: Ensure 'archived' column exists for all relevant tables
        ("Concept",         "archived", "BOOLEAN"),
        ("Decision",        "archived", "BOOLEAN"),
        ("Constraint",      "archived", "BOOLEAN"),
        ("Requirement",     "archived", "BOOLEAN"),
        ("ActionItem",      "archived", "BOOLEAN"),
        ("GlobalConstraint", "archived", "BOOLEAN"),
        ("GlobalPreference", "archived", "BOOLEAN"),
        ("MainQuest",       "archived", "BOOLEAN"),
        ("SideQuest",       "archived", "BOOLEAN"),
        ("Message",         "archived", "BOOLEAN"),
        ("DocumentExtract", "archived", "BOOLEAN"),
        ("Label",           "archived", "BOOLEAN"),
        ("Plan",            "source", "STRING"),
        # Back-compat for older DBs created before expanded Lesson schema
        ("Lesson",          "domain", "STRING"),
        ("Lesson",          "lesson_type", "STRING"),
        ("Lesson",          "confidence", "DOUBLE"),
        ("Lesson",          "confidence_low", "BOOLEAN"),
        ("Lesson",          "pathway_strength", "DOUBLE"),
        ("Lesson",          "archived", "BOOLEAN"),
    ]
    def _column_exists(table: str, col: str) -> bool:
        """Check whether a column already exists via table_info, avoiding
        ambiguous exception-based detection (B35 fix)."""
        try:
            r = db.execute(f"CALL table_info('{table}') RETURN *")
            while r.has_next():
                row = r.get_next()
                # row[1] is the column name
                if str(row[1]).lower() == col.lower():
                    return True
        except Exception:
            pass
        return False

    for table, col, col_type in _MIGRATIONS:
        if _column_exists(table, col):
            continue  # Already present — skip silently
        try:
            db.execute(f"ALTER TABLE {table} ADD {col} {col_type}")
            print(f"  Migration: added {table}.{col} ({col_type})")
        except Exception as e:
            # Rare race: another process added the column between the check and
            # the ALTER (safe to ignore).  Any other error is a real problem.
            if "already" in str(e).lower() or "property" in str(e).lower():
                pass
            else:
                print(f"  Migration warning: {table}.{col}: {e}")

    # 1c. Relationship table migrations — handle tables that need FROM clause expansion.
    # Kùzu 0.11.3 doesn't support ALTER REL TABLE. We drop + recreate tables that
    # have expanded FROM clauses. Only safe when no existing edges use the old types.
    _REL_MIGRATIONS = [
        # B43: ESTABLISHED_IN expanded to include Requirement and ActionItem.
        # Old definition only had Decision + Constraint. No ESTABLISHED_IN edges
        # were ever written in the old schema (edge code added in this commit),
        # so DETACH DELETE is safe.
        {
            "table": "ESTABLISHED_IN",
            "probe":  "MATCH ()-[e:ESTABLISHED_IN]->() RETURN count(e) AS cnt",
            "new_ddl": "CREATE REL TABLE ESTABLISHED_IN "
                        "(FROM Decision TO Session, FROM Constraint TO Session, "
                        "FROM Requirement TO Session, FROM ActionItem TO Session)",
        },
    ]
    for rmig in _REL_MIGRATIONS:
        try:
            # Check if existing table has the full definition by probing a
            # Requirement→Session ESTABLISHED_IN edge (this will error if the
            # FROM type isn't registered).
            db.execute(
                "MATCH (a:Requirement)-[:ESTABLISHED_IN]->(s:Session) "
                "RETURN count(a) LIMIT 1"
            )
            # If it didn't raise — table already has Requirement. No migration needed.
        except Exception:
            # Table either doesn't exist or is missing Requirement as a FROM type.
            # Drop and recreate (safe: no ESTABLISHED_IN edges ever existed before B43).
            try:
                existing = db.execute(rmig["probe"])
                edge_count = existing.get_next()[0] if existing.has_next() else 0
                if edge_count == 0:
                    db.execute(f"DROP TABLE {rmig['table']}")
                    db.execute(rmig["new_ddl"])
                    print(f"  Rel migration: {rmig['table']} — expanded FROM types")
                else:
                    print(f"  Rel migration: {rmig['table']} — skipped ({edge_count} edges exist, manual migration needed)")
            except Exception as drop_err:
                # Table doesn't exist yet — DDL in step 2 will create it
                print(f"  Rel migration: {rmig['table']} — will be created fresh: {drop_err}")

    # 2. Relationship tables
    for ddl in REL_TABLES:
        db.execute(ddl)

    print("  Relationship tables created.")

    # 3. Seed ontology (GistClass + SchemaOrgType + ROUTES_TO)
    gist_classes_seen = set()
    schema_types_seen = set()

    for gist_name, schema_name, properties in ROUTING_TABLE:
        if gist_name not in gist_classes_seen:
            db.execute(
                "MERGE (g:GistClass {name: $name})",
                {"name": gist_name}
            )
            gist_classes_seen.add(gist_name)

        if schema_name not in schema_types_seen:
            # SC2 fix: MERGE on name only, then SET properties, to avoid
            # duplicate nodes if the properties list changes between versions.
            db.execute(
                "MERGE (s:SchemaOrgType {name: $name}) "
                "SET s.properties = $props",
                {"name": schema_name, "props": properties}
            )
            schema_types_seen.add(schema_name)

        db.execute(
            "MATCH (g:GistClass {name: $g}), (s:SchemaOrgType {name: $s}) "
            "MERGE (g)-[:ROUTES_TO]->(s)",
            {"g": gist_name, "s": schema_name}
        )

    print(f"  Ontology seeded: {len(gist_classes_seen)} gist classes, "
          f"{len(schema_types_seen)} schema.org types.")

    # 4. Bootstrap centroids
    _bootstrap_centroids(db, seed_examples_path, embedding_model)

    # 5. HNSW vector indexes (one per node table with embeddings)
    embedding_tables = [
        "Concept", "Decision", "Constraint", "Requirement", "ActionItem",
        "GlobalConstraint", "GlobalPreference", "MainQuest", "SideQuest",
        "Message", "DocumentExtract", "Label",
        "Lesson",  # B11
        "Plan",    # B66
        "PlanStep",  # B66
        "Hypothesis",  # B88
    ]
    for table in embedding_tables:
        index_name = f"{table.lower()}_emb_idx"
        try:
            db.create_vector_index(table, "embedding", index_name)
            print(f"  HNSW index: {index_name}")
        except Exception as e:
            # Index may already exist on subsequent startups
            if "already exists" not in str(e).lower():
                raise

    # GistClass centroid index (for centroid similarity lookups in Step 2)
    try:
        db.create_vector_index("GistClass", "centroid", "gistclass_centroid_idx")
        print("  HNSW index: gistclass_centroid_idx")
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise

    print("Schema initialization complete.")
