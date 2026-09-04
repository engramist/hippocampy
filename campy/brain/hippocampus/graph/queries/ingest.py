"""
campy/brain/hippocampus/graph/queries/ingest.py — Document and sensory ingestion queries.
"""

from campy.brain.hippocampus.graph.gateway import NamedQuery

INGEST_QUERIES = [
    NamedQuery(
        name="ingest.create_document_extract",
        cypher="""
        CREATE (e:DocumentExtract {
            extract_id:      $extract_id,
            text_raw:        $text_raw,
            embedding:       $embedding,
            embedding_model: $embedding_model,
            embedding_dim:   $embedding_dim,
            byte_start:      $byte_start,
            byte_end:        $byte_end,
            line_start:      $line_start,
            line_end:        $line_end,
            confidence:      1.0,
            confidence_low:  false,
            pathway_strength: 1.0,
            archived:        false,
            created_at:      timestamp($created_at)
        })
        """,
        params=(
            "extract_id", "text_raw", "embedding", "embedding_model", "embedding_dim",
            "byte_start", "byte_end", "line_start", "line_end", "created_at",
        ),
        mutating=True,
        description="Create DocumentExtract node",
    ),
    NamedQuery(
        name="ingest.link_extract_derived_from_document",
        cypher="""
        MATCH (e:DocumentExtract {extract_id: $eid}),
              (d:Document {document_id: $did})
        CREATE (e)-[:DERIVED_FROM]->(d)
        """,
        params=("eid", "did"),
        mutating=True,
        description="Link DocumentExtract to Document with DERIVED_FROM",
    ),
    NamedQuery(
        name="ingest.get_document_content_hash",
        cypher="""
        MATCH (d:Document {document_id: $did}) RETURN d.content_hash
        """,
        params=("did",),
        mutating=False,
        description="Get content hash of existing Document node",
    ),
    NamedQuery(
        name="ingest.upsert_document",
        cypher="""
        MERGE (d:Document {document_id: $document_id})
        ON CREATE SET d.location_uri     = $location_uri,
                      d.content_hash     = $content_hash,
                      d.last_modified_at = timestamp($now),
                      d.mime_type        = $mime_type
        ON MATCH SET  d.content_hash     = $content_hash,
                      d.last_modified_at = timestamp($now)
        """,
        params=("document_id", "location_uri", "content_hash", "now", "mime_type"),
        mutating=True,
        description="Merge Document node with updated metadata",
    ),
    NamedQuery(
        name="ingest.archive_old_extracts_for_document",
        cypher="""
        MATCH (e:DocumentExtract)-[:DERIVED_FROM]->(d:Document {document_id: $did})
        SET e.archived = true
        """,
        params=("did",),
        mutating=True,
        description="Archive existing DocumentExtract nodes for re-ingested Document",
    ),
    NamedQuery(
        name="ingest.find_active_dataset",
        cypher="""
        MATCH (d:Dataset {source_key: $sk}) WHERE d.archived = false
        RETURN d.dataset_id, d.content_hash, d.storage_uri, d.row_count,
               d.column_count, d.description
        ORDER BY d.created_at DESC LIMIT 1
        """,
        params=("sk",),
        mutating=False,
        description="Return active Dataset for a given source key",
    ),
    NamedQuery(
        name="ingest.archive_dataset",
        cypher="""
        MATCH (d:Dataset {dataset_id: $did}) SET d.archived = true
        """,
        params=("did",),
        mutating=True,
        description="Archive a superseded Dataset node",
    ),
    NamedQuery(
        name="ingest.create_fact_concept",
        cypher="""
        CREATE (c:Concept {
            concept_id:       $concept_id,
            text_raw:         $text_raw,
            embedding:        $embedding,
            embedding_model:  $embedding_model,
            embedding_dim:    $embedding_dim,
            gist_class:       '',
            schema_org_type:  '',
            confidence:       0.75,
            confidence_low:   false,
            pathway_strength: 0.55,
            archived:         false,
            created_at:       timestamp($now),
            last_accessed_at: timestamp($now)
        })
        """,
        params=("concept_id", "text_raw", "embedding", "embedding_model", "embedding_dim", "now"),
        mutating=True,
        description="Create fact Concept extracted from tabular dataset",
    ),
    NamedQuery(
        name="ingest.link_concept_dataset",
        cypher="""
        MATCH (c:Concept {concept_id: $cid}), (d:Dataset {dataset_id: $did})
        CREATE (c)-[:DESCRIBED_BY_DATASET {extraction_method: 'llm', created_at: timestamp($now)}]->(d)
        """,
        params=("cid", "did", "now"),
        mutating=True,
        description="Link concept to dataset via DESCRIBED_BY_DATASET",
    ),
    NamedQuery(
        name="ingest.create_dataset_node",
        cypher="""
        CREATE (d:Dataset {
            dataset_id:       $dataset_id,
            name:             $name,
            description:      $description,
            embedding:        $embedding,
            embedding_model:  $embedding_model,
            embedding_dim:    $embedding_dim,
            storage_uri:      $storage_uri,
            schema_json:      $schema_json,
            row_count:        $row_count,
            column_count:     $column_count,
            source_format:    $source_format,
            content_hash:     $content_hash,
            source_key:       $source_key,
            confidence:       $confidence,
            confidence_low:   $confidence_low,
            pathway_strength: $pathway_strength,
            archived:         $archived,
            created_at:       timestamp($created_at),
            last_accessed_at: timestamp($last_accessed_at)
        })
        """,
        params=(
            "dataset_id", "name", "description", "embedding", "embedding_model",
            "embedding_dim", "storage_uri", "schema_json", "row_count", "column_count",
            "source_format", "content_hash", "source_key", "confidence", "confidence_low",
            "pathway_strength", "archived", "created_at", "last_accessed_at",
        ),
        mutating=True,
        description="Create Dataset node",
    ),
    NamedQuery(
        name="ingest.link_dataset_belongs_to_quest",
        cypher="""
        MATCH (d:Dataset {dataset_id: $did})
        MATCH (q:MainQuest {quest_id: $qid})
        CREATE (d)-[:DATASET_BELONGS_TO_QUEST]->(q)
        """,
        params=("did", "qid"),
        mutating=True,
        description="Link dataset to quest via DATASET_BELONGS_TO_QUEST",
    ),
]
