"""
tests/patent_claims/test_claim_2_shape_first.py — Patent Claim 2 Verification.

Patent Claim 2:
"A method for ontological grounding before semantic extraction, wherein an incoming
concept entity is routed to a structured ontological class (GistClass) prior to property
population, bounding downstream semantic extraction to schema-compliant attributes."

Observable Mechanism Assertions:
- Verification of `route_to_schema_org` using real graph routing table.
- Bounding of permissible properties based on ontological classification (e.g. Demand, Action, Product).
- Deterministic disambiguation of polymorphic classes (e.g. Agent -> Person vs Organization)
  using natural entity context.
- Zero mocks; pure execution on live Kùzu graph.
"""

from __future__ import annotations

import pytest

from campy.brain.temporal_lobe.loop.step3_schema_org import (
    load_routing_table,
    route_to_schema_org,
)


def test_claim_2_shape_first_bounds_schema_properties(patent_db):
    """Verify Claim 2: Gist class assignment bounds schema.org type and properties."""
    # Ensure graph routing table is loaded from live database
    load_routing_table(patent_db)

    # 1. Restriction bounds to schema:Demand
    restriction_route = route_to_schema_org("Restriction")
    assert restriction_route["schema_org_type"] == "Demand"
    props = restriction_route["properties"]
    assert isinstance(props, list)
    assert len(props) > 0
    # Properties must bound downstream semantic extraction to valid schema fields
    assert "availability" in props or "eligibleCustomerType" in props or "description" in props

    # 2. PlannedEvent bounds to schema:Action
    planned_route = route_to_schema_org("PlannedEvent")
    assert planned_route["schema_org_type"] == "Action"
    assert "agent" in planned_route["properties"] or "target" in planned_route["properties"]

    # 3. PhysicalThing bounds to schema:Product
    product_route = route_to_schema_org("PhysicalThing")
    assert product_route["schema_org_type"] == "Product"
    assert "name" in product_route["properties"] or "description" in product_route["properties"]

    # 4. Magnitude bounds to schema:QuantitativeValue
    mag_route = route_to_schema_org("Magnitude")
    assert mag_route["schema_org_type"] == "QuantitativeValue"
    assert "value" in mag_route["properties"]


def test_claim_2_polymorphic_agent_disambiguation(patent_db):
    """Verify Claim 2: Polymorphic Agent class disambiguates to Person or Organization."""
    load_routing_table(patent_db)

    # Disambiguation via PERSON label
    person_route = route_to_schema_org("Agent", spacy_label="PERSON")
    assert person_route["schema_org_type"] == "Person"
    assert "jobTitle" in person_route["properties"] or "name" in person_route["properties"]

    # Disambiguation via ORG label
    org_route = route_to_schema_org("Agent", spacy_label="ORG")
    assert org_route["schema_org_type"] == "Organization"
    assert "member" in org_route["properties"] or "parentOrganization" in org_route["properties"]
