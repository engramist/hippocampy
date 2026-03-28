# B-memory-improvements Triage Table

| finding_id | finding_title | severity | disposition | linked_cards | evidence | notes |
|---|---|---|---|---|---|---|
| 1 | Upgrade to Streamable HTTP | CRITICAL | resolved | B36 | B36.md, web/server.py | Upgraded 2025-03-26 (MCP spec); verified in B36. |
| 2 | Two Tools Not Registered (Restart Daemon) | HIGH | resolved | B28, B35 | B28.md, B35.md | Underlying schema and registration bugs fixed in B28/B35. |
| 3 | Recall Returns Wrong Results (Recency) | MEDIUM | mapped | B31 | B31.md | B31 is ready for execution. |
| 4 | Duplicate Concepts in Graph | MEDIUM | resolved | B33 | B33.md | Fixed 2026-03-22 in B33. |
| 5 | Junk Concepts Still Leaking | LOW-MEDIUM | mapped | B34 | B34.md | B34 is ready for execution. |
| 6 | Zero Edges in Graph | MEDIUM | resolved | B32 | B32.md | Fixed 2026-03-22 in B32. |
| 7 | Keep Legacy SSE Endpoint | LOW | resolved | B36 | B36.md | B36 Action Item 3 covers legacy fallback. |
| 8 | Consolidation Loop Doesn't Run for New Sessions Without Git Context | MEDIUM | mapped | B63 | N/A | Need to handle non-git sessions in hippocampus. |
| 9 | Message Count Shows 0 Despite Successful Stores | LOW | mapped | B64 | N/A | stats endpoint investigation needed. |
| 10 | OpenClaw Extension Missing Tools | LOW | mapped | B65, B61 | B65.md (new), B61.md | B65 adds registration, B61 adds surfacing (allowlist). |
