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

# Module-level cache populated at startup
_routing_cache: dict[str, dict] = {}


def load_routing_table(db) -> None:
    """Load routing table from Kùzu into module cache. Call at daemon startup."""
    global _routing_cache
    result = db.execute(
        "MATCH (g:GistClass)-[:ROUTES_TO]->(s:SchemaOrgType) "
        "RETURN g.name, s.name, s.properties"
    )
    while result.has_next():
        row = result.get_next()
        gist_name, schema_name, properties = row[0], row[1], row[2]
        _routing_cache[gist_name] = _routing_cache.get(gist_name, [])
        _routing_cache[gist_name] = {"schema_org_type": schema_name,
                                      "properties": properties or []}


def route_to_schema_org(gist_class: str, spacy_label: str = None) -> dict:
    """
    Return {schema_org_type, properties} for a gist class.
    Uses cached routing table; falls back to hardcoded map if cache empty.
    For gist:Agent, uses spacy_label (PERSON/ORG) to disambiguate.
    """
    if gist_class == "Agent":
        schema_name = _AGENT_SPACY_MAP.get(spacy_label, "Organization")
        fallback_key = f"Agent_{schema_name}"
        if fallback_key in _FALLBACK_ROUTING:
            sn, props = _FALLBACK_ROUTING[fallback_key]
            return {"schema_org_type": sn, "properties": props}

    # Try live cache first
    if gist_class in _routing_cache:
        return _routing_cache[gist_class]

    # Fallback to hardcoded
    if gist_class in _FALLBACK_ROUTING:
        schema_name, properties = _FALLBACK_ROUTING[gist_class]
        return {"schema_org_type": schema_name, "properties": properties}

    return {"schema_org_type": "Thing", "properties": ["name", "description"]}
