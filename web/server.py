"""
web/server.py — Memory Control Panel (M7)

FastAPI server bound strictly to 127.0.0.1 — never 0.0.0.0.
No authentication needed (local-only access).

M7 features:
  - Graph visualization (D3.js or Cytoscape.js)
  - confidence_low nodes queue (soft-lock confirmation UI)
  - MergeEvent rollback UI (delta display + one-click revert)
  - Quest purpose confirm/edit
  - Constraint Ledger export (Markdown + JSON)
  - CO_OCCURS_WITH → named edge manual promotion

M7 scope: implement.
"""
# TODO M7: implement FastAPI server
