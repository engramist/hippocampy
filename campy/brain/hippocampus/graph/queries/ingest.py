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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
              ?e a campy:DocumentExtract ;
                campy:extract_id ?extract_id ;
                campy:text_raw ?text_raw ;
                campy:embedding ?embedding ;
                campy:embedding_model ?embedding_model ;
                campy:embedding_dim ?embedding_dim ;
                campy:byte_start ?byte_start ;
                campy:byte_end ?byte_end ;
                campy:line_start ?line_start ;
                campy:line_end ?line_end ;
                campy:confidence "1.0"^^xsd:double ;
                campy:confidence_low false ;
                campy:pathway_strength "1.0"^^xsd:double ;
                campy:archived false ;
                campy:created_at ?created_at .
            }
            WHERE {
              BIND(IRI(CONCAT("https://campy.dev/data/DocumentExtract/", ENCODE_FOR_URI(STR(?extract_id)))) AS ?e)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
              ?e campy:DERIVED_FROM ?d .
            }
            WHERE {
              ?e a campy:DocumentExtract ; campy:extract_id ?eid .
              ?d a campy:Document ; campy:document_id ?did .
            }
        """,
    ),
    NamedQuery(
        name="ingest.get_document_content_hash",
        cypher="""
        MATCH (d:Document {document_id: $did}) RETURN d.content_hash
        """,
        params=("did",),
        mutating=False,
        description="Get content hash of existing Document node",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?content_hash
            WHERE {
              ?d a campy:Document ;
                 campy:document_id ?did .
              OPTIONAL { ?d campy:content_hash ?content_hash }
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
                ?d campy:content_hash ?old_hash .
                ?d campy:last_modified_at ?old_mod .
            }
            INSERT {
                ?target_d a campy:Document ;
                   campy:document_id ?document_id ;
                   campy:content_hash ?content_hash ;
                   campy:last_modified_at ?now ;
                   campy:location_uri ?loc ;
                   campy:mime_type ?mime .
            }
            WHERE {
                OPTIONAL {
                    ?d a campy:Document ;
                       campy:document_id ?document_id .
                    OPTIONAL { ?d campy:content_hash ?old_hash }
                    OPTIONAL { ?d campy:last_modified_at ?old_mod }
                    OPTIONAL { ?d campy:location_uri ?old_loc }
                    OPTIONAL { ?d campy:mime_type ?old_mime }
                }
                BIND(COALESCE(?d, IRI(CONCAT("https://campy.dev/data/Document/", ENCODE_FOR_URI(STR(?document_id))))) AS ?target_d)
                BIND(COALESCE(?old_loc, ?location_uri) AS ?loc)
                BIND(COALESCE(?old_mime, ?mime_type) AS ?mime)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
                ?e campy:archived ?old_archived .
            }
            INSERT {
                ?e campy:archived true .
            }
            WHERE {
                ?e a campy:DocumentExtract ;
                   campy:DERIVED_FROM ?d .
                ?d a campy:Document ;
                   campy:document_id ?did .
                OPTIONAL { ?e campy:archived ?old_archived }
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            SELECT ?dataset_id ?content_hash ?storage_uri ?row_count ?column_count ?description
            WHERE {
                ?d a campy:Dataset ;
                   campy:source_key ?sk ;
                   campy:dataset_id ?dataset_id ;
                   campy:created_at ?created_at .
                OPTIONAL { ?d campy:archived ?archived }
                FILTER(!BOUND(?archived) || ?archived = false)
                OPTIONAL { ?d campy:content_hash ?content_hash }
                OPTIONAL { ?d campy:storage_uri ?storage_uri }
                OPTIONAL { ?d campy:row_count ?row_count }
                OPTIONAL { ?d campy:column_count ?column_count }
                OPTIONAL { ?d campy:description ?description }
            }
            ORDER BY DESC(?created_at)
            LIMIT 1
        """,
    ),
    NamedQuery(
        name="ingest.archive_dataset",
        cypher="""
        MATCH (d:Dataset {dataset_id: $did}) SET d.archived = true
        """,
        params=("did",),
        mutating=True,
        description="Archive a superseded Dataset node",
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            DELETE {
                ?d campy:archived ?old_archived .
            }
            INSERT {
                ?d campy:archived true .
            }
            WHERE {
                ?d a campy:Dataset ;
                   campy:dataset_id ?did .
                OPTIONAL { ?d campy:archived ?old_archived }
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT {
                ?c a campy:Concept ;
                    campy:concept_id ?concept_id ;
                    campy:text_raw ?text_raw ;
                    campy:embedding ?embedding ;
                    campy:embedding_model ?embedding_model ;
                    campy:embedding_dim ?embedding_dim ;
                    campy:gist_class "" ;
                    campy:schema_org_type "" ;
                    campy:confidence "0.75"^^xsd:double ;
                    campy:confidence_low false ;
                    campy:pathway_strength "0.55"^^xsd:double ;
                    campy:archived false ;
                    campy:created_at ?now ;
                    campy:last_accessed_at ?now .
            }
            WHERE {
                BIND(IRI(CONCAT("https://campy.dev/data/Concept/", ENCODE_FOR_URI(STR(?concept_id)))) AS ?c)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
                ?c campy:DESCRIBED_BY_DATASET ?d .
                << ?c campy:DESCRIBED_BY_DATASET ?d >> campy:occurrence ?occ .
                ?occ a campy:Occurrence ;
                     campy:extraction_method "llm" ;
                     campy:created_at ?now .
            }
            WHERE {
                ?c a campy:Concept ; campy:concept_id ?cid .
                ?d a campy:Dataset ; campy:dataset_id ?did .
                BIND(IRI(CONCAT("https://campy.dev/data/occurrence/", ENCODE_FOR_URI(STR(?cid)), "_described_by_", ENCODE_FOR_URI(STR(?did)), "_", ENCODE_FOR_URI(STR(?now)))) AS ?occ)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
                ?d a campy:Dataset ;
                    campy:dataset_id ?dataset_id ;
                    campy:name ?name ;
                    campy:description ?description ;
                    campy:embedding ?embedding ;
                    campy:embedding_model ?embedding_model ;
                    campy:embedding_dim ?embedding_dim ;
                    campy:storage_uri ?storage_uri ;
                    campy:schema_json ?schema_json ;
                    campy:row_count ?row_count ;
                    campy:column_count ?column_count ;
                    campy:source_format ?source_format ;
                    campy:content_hash ?content_hash ;
                    campy:source_key ?source_key ;
                    campy:confidence ?confidence ;
                    campy:confidence_low ?confidence_low ;
                    campy:pathway_strength ?pathway_strength ;
                    campy:archived ?archived ;
                    campy:created_at ?created_at ;
                    campy:last_accessed_at ?last_accessed_at .
            }
            WHERE {
                BIND(IRI(CONCAT("https://campy.dev/data/Dataset/", ENCODE_FOR_URI(STR(?dataset_id)))) AS ?d)
            }
        """,
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
        sparql="""
            PREFIX campy: <https://campy.dev/ns#>

            INSERT {
                ?d campy:DATASET_BELONGS_TO_QUEST ?q .
            }
            WHERE {
                ?d a campy:Dataset ; campy:dataset_id ?did .
                ?q a campy:MainQuest ; campy:quest_id ?qid .
            }
        """,
    ),
]
