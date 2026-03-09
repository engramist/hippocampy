"""
Step 3 — schema.org Sub-graph Routing

Named IP Claim: Shape-First Principle — classify ontological type before semantic work.

Routes each gist class to the relevant schema.org property subset only.
Routing table lives in the graph as (GistClass)-[ROUTES_TO]->(SchemaOrgType) edges,
seeded at M1 schema init. Step 3 queries these nodes at runtime — no hardcoded routing.

Routing table (locked):
  gist:Restriction   → schema:Demand
  gist:PlannedEvent  → schema:Action
  gist:PhysicalThing → schema:Product
  gist:Magnitude     → schema:QuantitativeValue
  gist:Category      → schema:DefinedTerm
  gist:Agent (person) → schema:Person      (uses Step 1 spaCy PERSON label)
  gist:Agent (org)    → schema:Organization (uses Step 1 spaCy ORG label)
  gist:Event         → schema:Event

Agent disambiguation: spaCy entity label from Step 1 determines Person vs Organization.
Zero extra LLM cost — reuses Step 1 output.

Output: schema_org_type string + property subset list, passed to Step 3b and Step 4.

M3 scope: implement this step (queries routing table from Kùzu via kuzu_client).
"""


def route_to_schema_org(gist_class: str, spacy_label: str = None) -> dict:
    """
    Look up the schema.org type for a gist class.
    spacy_label used for Agent disambiguation (PERSON vs ORG).
    Returns {schema_org_type, properties: [...]}.
    """
    # TODO M3: query (GistClass {name: gist_class})-[ROUTES_TO]->(SchemaOrgType)
    # from Kùzu via kuzu_client
    pass
