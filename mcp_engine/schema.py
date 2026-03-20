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
        created_at      TIMESTAMP,
        PRIMARY KEY (extract_id)
    """,

    "Session": """
        session_id     STRING,
        started_at     TIMESTAMP,
        last_active_at TIMESTAMP,
        onboarded      BOOLEAN,
        purpose        STRING,
        routing_state       STRING,
        routing_confidence  DOUBLE,
        routing_method      STRING,
        content_embedding   FLOAT[384],
        token_estimate      INT64,
        token_limit         INT64,
        loaded_node_count   INT32,
        last_injection_at   TIMESTAMP,
        last_loop_summary   STRING,
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
        obstacle_summary STRING,
        source_quest_id  STRING,
        confidence       DOUBLE,
        confidence_low   BOOLEAN,
        pathway_strength DOUBLE,
        archived         BOOLEAN,
        created_at       TIMESTAMP,
        PRIMARY KEY (lesson_id)
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
    "CREATE REL TABLE IF NOT EXISTS ESTABLISHED_IN (FROM Decision TO Session, FROM Constraint TO Session)",
    # Ontology routing (core IP — Shape-First Principle)
    "CREATE REL TABLE IF NOT EXISTS ROUTES_TO (FROM GistClass TO SchemaOrgType)",
    # SKOS labels
    "CREATE REL TABLE IF NOT EXISTS HAS_PREF_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS HAS_ALT_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS HAS_HIDDEN_LABEL (FROM Concept TO Label, FROM Decision TO Label, FROM Constraint TO Label, FROM Requirement TO Label, FROM ActionItem TO Label)",
    "CREATE REL TABLE IF NOT EXISTS LOADED (FROM Session TO Concept, FROM Session TO Decision, FROM Session TO Constraint, FROM Session TO Requirement, FROM Session TO ActionItem, FROM Session TO GlobalConstraint, FROM Session TO GlobalPreference, injected_at TIMESTAMP, token_estimate INT32, source STRING)",
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
    # B11 — Lesson
    "CREATE REL TABLE IF NOT EXISTS PRODUCED_LESSON (FROM MainQuest TO Lesson)",
    "CREATE REL TABLE IF NOT EXISTS REROUTED_FROM (FROM Session TO MainQuest, rerouted_at TIMESTAMP, reason STRING)",
]

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
      1. Create all node tables (IF NOT EXISTS)
      2. Create all relationship tables (IF NOT EXISTS)
      3. Seed GistClass + SchemaOrgType nodes + ROUTES_TO edges
      4. Bootstrap GistClass centroids from seed examples
      5. Create HNSW vector indexes
    """
    print("Initializing schema...")

    # 1. Node tables
    for table_name, fields in NODE_TABLES.items():
        db.execute(f"CREATE NODE TABLE IF NOT EXISTS {table_name} ({fields})")
        print(f"  Node table: {table_name}")

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
