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
    """Load routing table from Kùzu into module cache. Call at daemon startup.

    Supports multi-valued entries: gist:Agent maps to BOTH Person and Organization.
    Cache stores a list of {schema_org_type, properties} per gist class.
    """
    global _routing_cache
    _routing_cache.clear()
    result = db.execute(
        "MATCH (g:GistClass)-[:ROUTES_TO]->(s:SchemaOrgType) "
        "RETURN g.name, s.name, s.properties"
    )
    while result.has_next():
        row = result.get_next()
        gist_name, schema_name, properties = row[0], row[1], row[2]
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
