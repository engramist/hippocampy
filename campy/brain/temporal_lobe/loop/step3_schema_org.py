"""
Step 3 — schema.org Sub-graph Routing

Named IP Claim: Shape-First Principle.
Routing table lives in the graph — queried at runtime, not hardcoded.
"""

# Agent disambiguation: spaCy label determines Person vs Organization
# Values must match the suffix used in _FALLBACK_ROUTING keys ("Agent_Person", "Agent_Org")
_AGENT_SPACY_MAP = {
    "PERSON": "Person",
    "ORG":    "Org",
}

# Fallback hardcoded routing (used when Kùzu not yet available in tests)
_FALLBACK_ROUTING = {
    "Restriction":   ("Demand",            ["eligibleCustomerType", "availability", "validFrom", "validThrough", "businessFunction", "description"]),
    "PlannedEvent":  ("Action",            ["agent", "object", "target", "actionStatus", "startTime", "endTime", "result", "instrument"]),
    "PhysicalThing": ("Product",           ["name", "identifier", "description", "version", "inLanguage", "isAccessoryOrSparePartFor"]),
    "Magnitude":     ("QuantitativeValue", ["value", "unitCode", "unitText", "minValue", "maxValue", "valueReference"]),
    "Category":      ("DefinedTerm",       ["name", "description", "termCode", "inDefinedTermSet", "sameAs"]),
    "Agent_Person":  ("Person",            ["name", "jobTitle", "description", "email", "knowsAbout"]),
    "Agent_Org":     ("Organization",      ["name", "description", "member", "parentOrganization", "contactPoint"]),
    "Event":         ("Event",             ["name", "startDate", "endDate", "eventStatus", "location", "organizer", "description"]),
}

# Read-through cache over KuzuDB: populated at daemon startup from the graph in
# load_routing_table() (lookup (g:GistClass)-[:ROUTES_TO]->(s:SchemaOrgType)). The
# graph remains the source of truth; this is a cache, not a shadow store.
_routing_cache: dict[str, dict] = {}  # nosemgrep: campy-shadow-store-dict


from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY


def load_routing_table(db) -> None:
    """Load routing table from Kùzu into module cache. Call at daemon startup.

    Supports multi-valued entries: gist:Agent maps to BOTH Person and Organization.
    Cache stores a list of {schema_org_type, properties} per gist class.
    """
    global _routing_cache
    _routing_cache.clear()
    gw = GraphGateway(db, REGISTRY) if not isinstance(db, GraphGateway) else db
    rows = gw.run_sync("orchestrator.get_schema_org_routing", {})
    for row in rows:
        gist_name = row.get("g.name") if hasattr(row, "get") else row[0]
        schema_name = row.get("s.name") if hasattr(row, "get") else row[1]
        properties = row.get("s.properties") if hasattr(row, "get") else row[2]
        entry = {"schema_org_type": schema_name, "properties": properties or []}
        if gist_name not in _routing_cache:
            _routing_cache[gist_name] = []
        _routing_cache[gist_name].append(entry)


def route_to_schema_org(gist_class: str, spacy_label: str = None) -> dict:
    """
    Return {schema_org_type, properties} for a gist class.
    Uses cached routing table; falls back to hardcoded map if cache empty.
    For gist:Agent, uses spacy_label (PERSON/ORG) to disambiguate.
    """
    # Agent disambiguation — pick Person vs Organization based on spaCy label
    if gist_class == "Agent":
        target_schema = _AGENT_SPACY_MAP.get(spacy_label, "Organization")

        # Try live cache first (may have multiple entries for Agent)
        if gist_class in _routing_cache:
            for entry in _routing_cache[gist_class]:
                if entry["schema_org_type"] == target_schema:
                    return entry

        # Fallback to hardcoded
        fallback_key = f"Agent_{target_schema}"
        if fallback_key in _FALLBACK_ROUTING:
            sn, props = _FALLBACK_ROUTING[fallback_key]
            return {"schema_org_type": sn, "properties": props}

    # Non-Agent: try live cache first (take first entry from list)
    if gist_class in _routing_cache:
        entries = _routing_cache[gist_class]
        if entries:
            return entries[0]

    # Fallback to hardcoded
    if gist_class in _FALLBACK_ROUTING:
        schema_name, properties = _FALLBACK_ROUTING[gist_class]
        return {"schema_org_type": schema_name, "properties": properties}

    return {"schema_org_type": "Thing", "properties": ["name", "description"]}
