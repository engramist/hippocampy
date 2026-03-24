# gist Class Seed Examples

**Purpose:** Bootstrap centroids for the Step 2 System 1 hybrid classifier.
Each sentence is a labeled example used to compute the initial embedding centroid
for its gist class. System 2 (LLM) resolutions are appended here over time →
centroids improve → System 1 accuracy increases.

**Format:** Each example is a realistic sentence from a conversation. Examples span
multiple domains (software development, wellness coaching, marketing/ads, general
business) to produce domain-neutral centroids. Chosen to represent the semantic core of each class,
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
16. "Clients must complete an intake form before their first coaching session." (W)
17. "Never recommend specific supplements without checking for medication interactions." (W)
18. "All coaching sessions must include a liability waiver on file." (W)
19. "We cannot run alcohol ads targeting users under 25 on Meta." (M)
20. "Google Ads disapproves any landing page without a clear privacy policy." (M)
21. "YouTube requires disclosed sponsorships to use the paid promotion checkbox." (M)
22. "Ad spend must never exceed the approved monthly budget without written approval." (M)
23. "Email campaigns must include an unsubscribe link in every message — CAN-SPAM requires it." (M)
24. "All client contracts require a 30-day cancellation notice period." (B)
25. "Never share financial projections externally without the CFO's sign-off." (B)
26. "Invoices must be sent within 48 hours of service delivery." (B)
27. "We cannot use client testimonials in marketing without signed release forms." (B)
28. "Meal plans must be reviewed by a registered dietitian before distribution." (W)
29. "Never make income claims in ads — the FTC will flag it immediately." (M)
30. "All subcontractors must sign an NDA before accessing client data." (B)
31. "Rent must be paid by the first of every month to avoid late fees." (L)
32. "The warranty is void if the device is opened or repaired by an unauthorized technician." (L)
33. "Parking is not allowed on the street during street-sweeping hours." (L)
34. "Carry-on luggage must not exceed the airline's weight and size limits." (L)
35. "I am trying to keep my daily sugar intake under 25 grams." (L)
36. "Always lock the deadbolt before going to sleep at night." (L)
37. "The gym requires all members to wipe down equipment after use." (L)
38. "Pets are not allowed on the new living room furniture." (L)
39. "Do not run the dishwasher unless it is completely full." (L)
40. "The doctor advised no heavy lifting for two weeks after the minor surgery." (L)
41. "Library books must be returned within 21 days to avoid fines." (L)
42. "Do not water the indoor plants more than once a week." (L)
43. "The homeowner's association prohibits leaving trash cans out past Monday evening." (L)
44. "I need to restrict my screen time an hour before going to bed." (L)
45. "Never give out your social security number over an unsolicited phone call." (L)

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
16. "I'm launching a 6-week wellness reset program starting in April." (W)
17. "We need to schedule the quarterly health screenings for all coaching clients." (W)
18. "I plan to get my nutrition certification before taking on diet-focused clients." (W)
19. "Next week I'm going to research group coaching platforms for the online expansion." (W)
20. "We're launching the Black Friday ad campaign on Meta starting November 20th." (M)
21. "I need to set up Google Analytics 4 event tracking before the product launch." (M)
22. "We plan to A/B test two different YouTube thumbnail styles next month." (M)
23. "The email nurture sequence goes live after we finalize the landing page copy." (M)
24. "I'm going to renegotiate the office lease when it comes up in June." (B)
25. "We're hiring a part-time bookkeeper starting next quarter." (B)
26. "The annual strategy retreat is scheduled for the last week of January." (B)
27. "I plan to switch from Stripe to Square for in-person payment processing." (B)
28. "We're going to start posting three Reels per week to grow the Instagram following." (M)
29. "I need to complete my continuing education credits by end of year." (W)
30. "We'll submit the LLC formation paperwork before accepting new clients." (B)
31. "I have a routine dental cleaning scheduled for next Tuesday afternoon." (L)
32. "We are planning a weekend getaway to the mountains next month." (L)
33. "The car needs to go into the shop for an oil change on Friday morning." (L)
34. "I am hosting a dinner party for a few friends this Saturday." (L)
35. "The landlord is scheduled to inspect the apartment's smoke detectors tomorrow." (L)
36. "I plan to deep clean the kitchen appliances over the long weekend." (L)
37. "My annual physical exam is booked for the second week of November." (L)
38. "We are going to a community theater play tomorrow evening." (L)
39. "I'm taking the dog to the vet for his annual vaccinations next week." (L)
40. "I plan to finally organize the hall closet on Sunday afternoon." (L)
41. "The delivery window for the new mattress is scheduled between 1 PM and 4 PM." (L)
42. "I'm meeting a friend for lunch downtown on Wednesday." (L)
43. "We plan to renew our passports before they expire in six months." (L)
44. "The internet technician is coming out to upgrade the router on Thursday." (L)
45. "I am going to start training for a 5k run next Monday." (L)

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
21. "We use Mindbody to manage all coaching session bookings and client records." (W)
22. "The InBody scanner measures body composition for our wellness assessments." (W)
23. "Our meal planning templates live in a shared Google Drive folder." (W)
24. "The heart rate monitors sync with the coaching app via Bluetooth." (W)
25. "Meta Business Suite is where we manage all Facebook and Instagram ad campaigns." (M)
26. "Google Analytics 4 tracks all website traffic and conversion events." (M)
27. "We use Canva to create all the social media post graphics and ad creatives." (M)
28. "TubeBuddy helps us optimize YouTube video titles, tags, and thumbnails." (M)
29. "Mailchimp handles our email list segmentation and automated drip campaigns." (M)
30. "QuickBooks Online is our accounting system for invoicing and expense tracking." (B)
31. "The Square terminal processes all in-person credit card payments." (B)
32. "We store all client contracts in DocuSign for digital signatures." (B)
33. "Slack is our team communication tool for daily coordination." (B)
34. "The Zoom Pro account handles all virtual coaching sessions and webinars." (W)
35. "Google Search Console shows which keywords drive organic traffic to our site." (M)
36. "The spare house keys are kept in the ceramic bowl by the front door." (L)
37. "The title to the car is filed away in the fireproof safe." (L)
38. "The winter coats are stored in the vacuum-sealed bags under the bed." (L)
39. "My primary laptop is currently charging on the home office desk." (L)
40. "The slow cooker is perfect for making warm meals on busy weeknights." (L)
41. "The snow shovel is leaning against the wall in the back of the garage." (L)
42. "I keep my gym bag packed and waiting in the trunk of my car." (L)
43. "The new wireless router was installed right next to the television." (L)
44. "Our emergency preparedness kit is located on the bottom shelf of the pantry." (L)
45. "The vacuum cleaner filter needs to be replaced this month." (L)
46. "The recipe box on the counter holds all my favorite dinner instructions." (L)
47. "The reusable grocery bags are stuffed into the back pocket of the passenger seat." (L)
48. "The digital meat thermometer is in the drawer next to the oven." (L)
49. "My hiking boots are covered in mud from the trail this morning." (L)
50. "The smoke detector in the hallway needs a new nine-volt battery." (L)

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
16. "Client retention rate improved from 60% to 78% after adding monthly check-ins." (W)
17. "The average coaching program runs 12 weeks with sessions twice per week." (W)
18. "We aim for at least 8 hours of sleep per night as a baseline wellness goal." (W)
19. "Resting heart rate dropped an average of 7 bpm across the 90-day program." (W)
20. "Our Meta ad cost per lead dropped from $12 to $6.50 after the creative refresh." (M)
21. "YouTube videos under 8 minutes get 40% more completion rate than longer ones." (M)
22. "Google Analytics shows a 3.2% conversion rate on the landing page." (M)
23. "We're spending $2,000 per month on Meta ads across three campaigns." (M)
24. "Email open rates average 22% but the welcome sequence hits 45%." (M)
25. "Monthly revenue crossed $15,000 for the first time in October." (B)
26. "We need at least a 40% gross margin to sustain the current team size." (B)
27. "Client acquisition cost is running about $85 per new customer." (B)
28. "The office lease is $2,200 per month for the 800 square foot space." (B)
29. "We target a Net Promoter Score above 70 for all coaching programs." (W)
30. "Ad return on spend needs to stay above 3x or we pause the campaign." (M)
31. "The round-trip flight across the country cost exactly four hundred dollars." (L)
32. "I walked just over ten thousand steps during the neighborhood hike today." (L)
33. "The recipe calls for exactly one and a half cups of all-purpose flour." (L)
34. "It takes about forty-five minutes to drive to the airport with normal traffic." (L)
35. "The new bookshelf took roughly two hours to completely assemble." (L)
36. "I managed to lower my monthly electric bill by 15% this summer." (L)
37. "The temperature dropped by twenty degrees overnight." (L)
38. "The apartment requires a security deposit equal to one month of rent." (L)
39. "We need to buy at least two gallons of paint to finish the living room." (L)
40. "The grocery bill was unusually high this week, totaling almost $200." (L)
41. "My resting heart rate has dropped by five beats per minute since I started running." (L)
42. "The warranty on the new washing machine lasts for exactly five years." (L)
43. "I've read 50 pages of the new novel so far this week." (L)
44. "The speed limit on the residential street is 25 miles per hour." (L)
45. "It will take an estimated three weeks for the custom furniture to be delivered." (L)

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
19. "A wellness assessment is an initial evaluation of a client's health baselines." (W)
20. "Group coaching is a lower-cost tier where 6-8 clients share a weekly session." (W)
21. "An accountability partner is a peer assigned to help maintain habit consistency." (W)
22. "A retainer client pays monthly for ongoing access rather than per-session billing." (W)
23. "A lookalike audience is a Meta targeting option based on your existing customer list." (M)
24. "Top-of-funnel content is designed to attract new awareness, not close sales." (M)
25. "A conversion event in Google Analytics is any tracked user action that matters to the business." (M)
26. "Evergreen content is YouTube videos or blog posts that stay relevant long-term." (M)
27. "A lead magnet is a free resource offered in exchange for an email address." (M)
28. "An LLC is a limited liability company — the standard small business entity structure." (B)
29. "Recurring revenue is income from subscriptions or retainers, not one-time sales." (B)
30. "A 1099 contractor is a freelancer paid without tax withholding — different from W-2 employees." (B)
31. "Accounts receivable is money owed to us by clients who haven't paid yet." (B)
32. "A burnout protocol is a structured recovery plan when a client shows stress overload signs." (W)
33. "Cost per mille is the price per 1,000 ad impressions on a platform." (M)
34. "A deductible is the amount you pay out-of-pocket before insurance covers the rest." (L)
35. "Meal prep is the practice of cooking multiple days of food in one single batch." (L)
36. "A streaming service is a platform that delivers movies and shows over the internet." (L)
37. "Preventative maintenance includes routine tasks like changing air filters and checking tire pressure." (L)
38. "A generic brand is a store-label product that is usually cheaper than the name brand." (L)
39. "A utility bill is a recurring monthly charge for essential services like water or electricity." (L)
40. "Compound interest is the interest you earn on both your original money and the accumulated interest." (L)
41. "A warranty is a written guarantee promising to repair or replace an item if necessary." (L)
42. "A layover is a scheduled break between connecting flights during travel." (L)
43. "An emergency fund is a stash of money set aside specifically for unexpected financial surprises." (L)
44. "Batch cooking involves preparing large quantities of a single ingredient to use in different meals." (L)
45. "A security deposit is money given to a landlord to cover potential damage to a rental property." (L)
46. "A fixed-rate mortgage keeps the exact same interest rate for the entire life of the loan." (L)
47. "Organic produce is grown without the use of synthetic pesticides or fertilizers." (L)
48. "A lease agreement is a legal contract outlining the terms under which one party agrees to rent property." (L)

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
16. "My nutrition coach handles all the meal planning for our wellness clients." (W)
17. "The client success manager follows up with everyone after their first month." (W)
18. "Peloton provides the at-home fitness content our clients use between sessions." (W)
19. "Our registered dietitian reviews every meal plan before it goes to a client." (W)
20. "Meta's ad review team approves or rejects every campaign within 24 hours." (M)
21. "Our social media manager creates and schedules all Instagram and YouTube content." (M)
22. "Google's algorithm determines which search results drive organic traffic to our site." (M)
23. "The email marketing VA handles list cleanup and campaign scheduling in Mailchimp." (M)
24. "Our CPA files quarterly estimated taxes and handles year-end books." (B)
25. "The landlord requires 60 days notice before any lease modification." (B)
26. "Stripe handles all online payment processing and sends payouts to our bank." (B)
27. "The business attorney reviewed the client service agreement and liability waivers." (B)
28. "YouTube's recommendation engine drives about 60% of our channel's total views." (M)
29. "The virtual assistant manages all appointment scheduling and client intake forms." (W)
30. "Our bookkeeper reconciles transactions in QuickBooks every two weeks." (B)
31. "The landlord called to say they are repainting the exterior of the building next week." (L)
32. "The mechanic recommended replacing the brake pads before the winter season starts." (L)
33. "A customer service representative helped me process the return for the damaged package." (L)
34. "The neighbor across the street asked if I could water their plants while they are out of town." (L)
35. "The electrician fixed the faulty wiring in the kitchen ceiling fan." (L)
36. "A friend from college is flying into town and staying in the guest bedroom." (L)
37. "The flight attendant requested that all large carry-on bags be checked at the gate." (L)
38. "The veterinarian prescribed a mild antibiotic for the dog's ear infection." (L)
39. "The mail carrier left a package notice slip on the front door this afternoon." (L)
40. "My financial advisor suggested increasing my retirement contributions by two percent." (L)
41. "The plumber unclogged the master bathroom sink in under twenty minutes." (L)
42. "The dentist noted that I need to start flossing more consistently." (L)
43. "A local artist painted the new mural on the side of the community center." (L)
44. "The store manager approved the discount on the slightly scratched display model." (L)
45. "The exterminator comes out quarterly to spray for ants and spiders around the foundation." (L)

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
16. "Three clients completed the 12-week transformation program last Friday." (W)
17. "A client reported a food allergy reaction — we updated their profile immediately." (W)
18. "We launched the morning mindfulness challenge and 45 people signed up day one." (W)
19. "The wellness retreat in Sedona filled all 20 spots within 48 hours of announcement." (W)
20. "Our Meta ad account got flagged for a policy violation on the weight loss campaign." (M)
21. "YouTube notified us that our latest video was demonetized for reused content." (M)
22. "Google Analytics detected a 40% traffic spike after the blog post went viral." (M)
23. "The email campaign launched yesterday and already has a 38% open rate." (M)
24. "We lost power at the office during a client session and had to reschedule." (B)
25. "The quarterly tax payment was submitted two days before the deadline." (B)
26. "A new competitor opened a coaching studio three blocks from our location." (B)
27. "We signed the partnership agreement with the local gym for cross-referrals." (B)
28. "Instagram's algorithm change cut our organic reach by 30% overnight." (M)
29. "The client's blood pressure normalized after 8 weeks on the program." (W)
30. "We received our LLC approval from the state and can now open the business account." (B)
31. "The power went out for three hours during the heavy thunderstorm last night." (L)
32. "I successfully renewed my vehicle registration online this morning." (L)
33. "The refrigerator stopped keeping things cold, so all the food spoiled." (L)
34. "We got caught in a massive traffic jam on the highway for over an hour." (L)
35. "I finally finished putting together the 1000-piece puzzle on the dining table." (L)
36. "The package was delivered two days earlier than the tracking number originally estimated." (L)
37. "I accidentally dropped my phone and cracked the corner of the screen." (L)
38. "The community pool officially opened for the summer season yesterday afternoon." (L)
39. "We discovered a great new hiking trail just a few miles from the house." (L)
40. "I received my annual tax refund via direct deposit yesterday." (L)
41. "The fire alarm went off in the building because someone burned their dinner." (L)
42. "I spilled a cup of water on the rug and had to spot-clean it immediately." (L)
43. "The weather cleared up beautifully just in time for the outdoor concert." (L)
44. "I officially paid off the final balance of my student loans this morning." (L)
45. "A stray dog wandered into the yard, but we safely returned him to his owner." (L)

---

## Usage Notes

- These examples are embedded at M1 schema initialization to seed initial centroids.
- Each sentence is embedded individually; the centroid is the average of all embeddings in the class.
- When System 2 (LLM) resolves an ambiguous case, the resolved example is appended to this file and centroids are recalculated.
- Centroid recalculation is lightweight — a mean of existing embedding vectors, no retraining.
- Over time, System 2 resolution rate decreases as centroids improve.
