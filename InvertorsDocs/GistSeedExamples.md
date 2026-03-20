# gist Class Seed Examples

**Purpose:** Bootstrap centroids for the Step 2 System 1 hybrid classifier.
Each sentence is a labeled example used to compute the initial embedding centroid
for its gist class. System 2 (LLM) resolutions are appended here over time →
centroids improve → System 1 accuracy increases.

**Format:** Each example is a realistic sentence a developer or AI assistant might
say during a software project. Chosen to represent the semantic core of each class,
not edge cases.

---

## gist:Restriction
*Rules, limits, constraints, requirements, policies — things that govern behavior.*

1. "We must never store API keys or credentials in source code."
2. "All database writes must go through the backend service only — no direct client access."
3. "External packages require a security review before being added to the project."
4. "The memory daemon must bind to localhost only, never 0.0.0.0."
5. "File paths must be canonicalized using realpath() before any read or write operation."
6. "Only .db and .log file extensions may be written by the daemon."
7. "Authentication is required for all API endpoints without exception."
8. "No direct database access is permitted from the frontend layer."
9. "All user inputs must be validated and sanitized before processing."
10. "Tests must pass on CI before any merge to the main branch."
11. "The MCP transport must use stdio only — no listening TCP ports."
12. "Memory Control Panel must bind to 127.0.0.1, never exposed externally."
13. "Symlink traversal and path escape attempts must be blocked at the daemon level."
14. "All LLM API keys must be loaded from environment variables, not config files."
15. "Cross-origin requests to the local web server are not permitted."

---

## gist:PlannedEvent
*Intended future actions, scheduled work, next steps, goals to accomplish.*

1. "We plan to add the Codex adapter in milestone 8."
2. "The next step is to implement the Kùzu schema initialization."
3. "We're going to refactor the authentication module in the next sprint."
4. "The deployment to production is scheduled for Friday."
5. "We need to migrate the database before the public release."
6. "I'm going to add unit tests for the retrieval module this week."
7. "We should implement error handling before completing M2."
8. "The UI redesign is planned for after the core engine is stable."
9. "We'll add cross-quest analogical reasoning in a later phase."
10. "The OpenClaw integration is deferred until Phase 1."
11. "We intend to auto-detect SideQuest branching via topic divergence in the future."
12. "The background confidence re-scoring sweep will run on daemon idle cycles."
13. "We're planning a provisional patent filing before publishing the routing table."
14. "The onboarding skill will be written before M2 wiring is complete."
15. "We will add Windows named pipe support before the public release."

---

## gist:PhysicalThing
*Tangible objects, software artifacts, systems, files, tools, infrastructure.*

1. "We're using Kùzu as the embedded graph and vector database."
2. "The Brain Daemon is a Python background process owning exclusive DB access."
3. "Claude Code is the primary AI development assistant for this project."
4. "The Unix domain socket is the IPC channel between adapter and daemon."
5. "We store embeddings as FLOAT32 arrays inside Kùzu."
6. "The sidequests.toml file holds the LLM provider configuration."
7. "Ollama serves local LLM inference on the Apple Silicon Mac."
8. "The FastAPI server handles all Memory Control Panel HTTP requests."
9. "spaCy is the NLP library used for Named Entity Recognition in Step 1."
10. "sentence-transformers produces the embedding vectors for all artifact nodes."
11. "The .mcp.json file registers the SideQuest adapter with Claude Code."
12. "The MergeEvent node stores delta pointers for deterministic rollback."
13. "The claude_desktop_config.json file configures MCP for Claude desktop."
14. "The GistClass and SchemaOrgType nodes form the ontology routing table in the graph."
15. "The adapter is a thin STDIO proxy with no business logic of its own."
16. "We decided to use SQLAlchemy as the ORM for its migration support."
17. "We chose PostgreSQL over SQLite for the production database."
18. "The team selected FastAPI as the web framework for the REST API."
19. "We're using Redis as the caching layer instead of Memcached."
20. "The project runs on Docker containers deployed to AWS ECS."

---

## gist:Magnitude
*Numbers, measures, quantities, thresholds, percentages, durations, sizes.*

1. "Confidence above 90% triggers automatic full-confidence storage."
2. "The context window for llama3.1:8b is 128k tokens."
3. "Vector similarity threshold for System 1 acceptance is 0.85."
4. "The gray zone for contradiction arbitration spans 0.75 to 0.92 similarity."
5. "The noise floor is set at 60% confidence — below this, no structural node is created."
6. "We retrieve the top 10 results from current_truth by default."
7. "The pathway strength decay formula uses log(1 + 1/days_since_last_access)."
8. "The always-on system prompt fragment is approximately 40 tokens."
9. "We target under 200ms latency per full consolidation cycle."
10. "Seed examples number approximately 15 per gist class, 7 classes total."
11. "The background sweep runs every 5 minutes during daemon idle periods."
12. "Confidence re-scoring looks 1 to 2 hops out from an updated node."
13. "The minimum embedding dimension for sentence-transformers is 384 floats."
14. "Session onboarding injects the full prompt once, then switches to the 40-token fragment."
15. "Auto-archive threshold is below 60% confidence after re-scoring."

---

## gist:Category
*Labels, types, classifications, definitions, taxonomies, roles.*

1. "A MainQuest is a high-level project goal anchored to a git repository and branch."
2. "SideQuests are sub-branches or tangents spawned from a MainQuest."
3. "A Decision is a resolved architectural choice made during a quest session."
4. "GlobalConstraints are workspace-level rules that apply across all quests."
5. "Active Mode adapters are LLM integrations that support full MCP tool calls."
6. "Passive Mode adapters observe and inject context without tool support."
7. "confidence_low nodes are tentative knowledge pending graph-driven re-scoring."
8. "A MergeEvent is an audit record of a pathway update with delta pointers."
9. "System 1 is fast pattern recognition via embedding similarity — no LLM cost."
10. "System 2 is deliberate LLM-based reasoning triggered when System 1 is uncertain."
11. "A soft-lock in the old model was a blocking gate; now it is a confidence_low flag."
12. "DocumentExtract nodes are semantically chunked paragraphs derived from a Document."
13. "A GlobalPreference is a workspace-level user preference applied across quests."
14. "The gist ontology provides upper-level universal classes for concept classification."
15. "schema.org sub-graphs provide domain-specific property shapes for each gist class."
16. "We defined the project as a microservices architecture rather than a monolith."
17. "The API versioning strategy is URL-based: /v1/, /v2/."
18. "We categorized this as a P0 critical bug, not a feature request."

---

## gist:Agent
*People, teams, organizations, systems, or processes acting with intent.*

1. "DJ is the lead developer and primary user of the SideQuest system."
2. "Claude Code is handling the architecture and implementation sessions."
3. "The Brain Daemon owns exclusive write access to the Kùzu database."
4. "The security team is responsible for reviewing all external dependency additions."
5. "Anthropic develops and maintains the Claude model family."
6. "The MCP adapter acts as a transparent proxy between the LLM and the Brain Daemon."
7. "Ollama serves local LLM inference without sending data to external servers."
8. "The setup CLI registers adapters with each target LLM on the user's machine."
9. "The background sweep task runs inside the Brain Daemon on idle cycles."
10. "The Memory Control Panel is a FastAPI server serving the local web UI."
11. "Explosion AI maintains spaCy and Prodigy."
12. "The sentence-transformers library is maintained by the Hugging Face community."
13. "Google released and open-sourced the Gemini CLI in mid-2025."
14. "The Brain Daemon re-scores confidence_low nodes autonomously without human input."
15. "OpenAI operates the ChatGPT desktop app with native MCP support."

---

## gist:Event
*Things that happened, are happening, or were triggered — occurrences and state changes.*

1. "The architecture session on March 7 resolved the OpenClaw dependency question."
2. "The schema was initialized with all node types and relationships at M1."
3. "A contradiction was detected between two Constraint nodes on the same topic."
4. "The Codex adapter connected to the Brain Daemon for the first time."
5. "A MergeEvent was created when the pathway strength was updated."
6. "The confidence re-scoring pass promoted three nodes above the 90% threshold."
7. "The onboarding prompt was injected into a new Claude Code session."
8. "Step 6 arbitration resolved a gray-zone similarity conflict between two decisions."
9. "The background sweep archived two nodes that dropped below 60% confidence."
10. "A new SideQuest was manually branched using the branch_quest tool."
11. "The MainQuest was auto-created from the git repo root hash and current branch."
12. "A Document node was created when the markdown file was ingested via Open Brain."
13. "The system prompt fragment was updated after the quest context changed."
14. "The LLMProvider node was created on first connection from a new model."
15. "The pathway strength decayed for a node not accessed in 14 days."

---

## Usage Notes

- These examples are embedded at M1 schema initialization to seed initial centroids.
- Each sentence is embedded individually; the centroid is the average of all embeddings in the class.
- When System 2 (LLM) resolves an ambiguous case, the resolved example is appended to this file and centroids are recalculated.
- Centroid recalculation is lightweight — a mean of existing embedding vectors, no retraining.
- Over time, System 2 resolution rate decreases as centroids improve.
