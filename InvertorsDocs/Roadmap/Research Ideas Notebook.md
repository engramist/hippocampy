# **📚 My Research & Publication Notebook**

**Primary Goal:** To develop, conduct, and write up research suitable for submission to a peer-reviewed academic journal.

**Target Timeline:** \[Insert Target Dates Here\]

## **📝 Criteria for a "Good" Peer-Reviewed Idea**

Before diving into a project, evaluate it against these questions:

1. **Is it original?** Does it add something new to the existing literature?  
2. **Is it feasible?** Do I have the resources, time, and sample size to actually test this?  
3. **Is it relevant?** Does it address a current gap or problem in a specific field?  
4. **Who is the audience?** What specific journals would care about this?

## **💡 Research Ideas Sandbox**

### **Idea 3: LLM Architectural Bias: The Over-Representation of "Mean" Training Data Solutions**

* **Research Question:** Do Large Language Models systematically bias software architecture recommendations toward statistically dominant solutions (e.g., relational databases) present in their training data, even when less represented paradigms (e.g., graph databases) offer objectively superior solutions for the user's specific constraints?  
* **Why it matters (Background):** As developers increasingly use LLMs for architectural design, there is a risk of technological stagnation. If LLMs merely output the "mean" of historical data, highly specialized or innovative tools will be ignored. Proving this bias exists highlights a critical limitation in AI-assisted software engineering and prompts the need for better "expert" prompting techniques.  
* **Literature Coverage & Gap Analysis:**  
  * **What's out there:** This is a bleeding-edge topic. Papers from 2025 (e.g., *Addressing Popularity Bias in Third-Party Library Recommendations Using LLMs*) are just starting to prove that LLMs suffer from "popularity bias" and the "long-tail effect" in code generation. Another recent paper warns of LLMs causing "cultural stagnation" and "evolutionary pressures" in software ecology.  
  * **The Gap:** While popularity bias is being proven in *code snippets* and *library recommendations* (like NPM packages), there is a distinct lack of empirical benchmarks regarding high-level *Systems Architecture* (e.g., Graph vs. Relational databases, Event-Driven vs. Monoliths). Establishing a benchmark for this specific bias would be a major contribution to Software Engineering literature.  
  * **Target Journals for Submission:**  
    * *IEEE Transactions on Software Engineering* (Top-tier software engineering)  
    * *ACM Transactions on Software Engineering and Methodology (TOSEM)* (Highly prestigious)  
    * *Empirical Software Engineering (EMSE)* (Perfect for a benchmark/empirical study)  
    * Conferences: *NeurIPS* or *ICSE* (International Conference on Software Engineering)  
* **Potential Methodology:** Design a rigorous benchmark of 10-20 software architecture prompts where a niche technology (like a Graph DB for highly interconnected social data) is definitively the optimal choice. Evaluate the zero-shot responses of major LLMs (GPT-4, Claude 3, Gemini) to quantify how often they default to popular but suboptimal solutions (like Relational DBs).  
* **Next Steps:** Draft 3-5 specific hypothetical engineering scenarios where a graph database is the clear winner, and run a quick pilot test against a few LLMs to see if the bias immediately shows up.

### **Idea 4: Breaking the "Memory Wall": Cognitive Efficiency vs. Token Bloat in Long-Running AI Agents & Autonomous Research**

* **Research Question:** Can externalizing long-term memory via a biomimetic, gated knowledge graph (the "Side Quests" architecture) successfully breach the agentic "Memory Wall" in both long-running software maintenance benchmarks and recursive autonomous research loops?  
* **Why it matters (Background):** AI is entering an era of "recursive self-improvement" where agents are deployed in autonomous loops to conduct research, run experiments, and write code overnight without human intervention. However, these agents hit a massive "Memory Wall." Relying solely on a context window leads to "token bloat" and amnesia. In an autonomous research loop, if the agent forgets that "Experiment A failed 50 iterations ago" because it fell out of context, it will regress and repeat past mistakes. Side Quests provides the permanent "Scientific Ledger" (tracking constraints, decisions, and deprecated hypotheses via graph edges) required to make autonomous loops sustainable.  
* **Literature Coverage & Gap Analysis:**  
  * **What's out there:** The industry is acutely aware of the Memory Wall right now. Recent benchmarks like SWE-CI (Alibaba) show 75% of frontier models break code during long-term maintenance. *LoCoBench* (late 2025\) was recently introduced to measure "Multi-Session Memory Retention" on massive 1M token contexts. Furthermore, cutting-edge papers from early 2026 (*MemoryArena* and *AMA-Bench*) specifically target interdependent, multi-session tasks. At the same time, tools like Andrej Karpathy's auto-research are proving that open-ended autonomous loops are the new frontier of agentic deployment.  
  * **The Gap:** While researchers are building benchmarks to *prove* agents fail at long-term memory, and practitioners are building autonomous loops, no one has bridged the two by integrating a domain-agnostic, gated Knowledge Graph as the persistent memory store for an autonomous researcher.  
  * **Target Journals for Submission:**  
    * *Journal of Artificial Intelligence Research (JAIR)* (Broad, high-impact AI research)  
    * *IEEE Software* (Great for practical developer workflows and architectural shifts)  
    * *Transactions on Machine Learning Research (TMLR)* (Fast-turnaround, values empirical benchmarking)  
    * *Proceedings of the VLDB Endowment (PVLDB)* (Excellent target if you heavily emphasize the Kùzu Graph DB and Graph-RAG mechanics)  
* **Potential Methodology: The Long-Term Benchmark Challenge**  
  * Use established benchmarks designed specifically for long-running context, specifically:  
    1. **SWE-CI Benchmark (Alibaba):** Test Side Quests against a raw agent over an average of 71 consecutive codebase updates to see if Side Quests prevents compounding technical debt.  
    2. **Autonomous Research Simulation (e.g., auto-research hook):** Run an overnight agentic loop tasked with optimizing a training script or codebase.  
       * *Metric to track:* **Hypothesis Regression Rate** \- How often does the baseline agent repeat a failed experiment vs. the Side Quests agent, which can query its graph to see that a specific architecture decision was explicitly \[DEPRECATED\_BY\] a previous run.  
    3. **LoCoBench / AMA-Bench Simulations:** Run Side Quests through multi-session interdependent tasks to prove that the "Cocktail Party Effect" interception and graph-RAG outperform basic vector database retrieval.  
  * **Core Metrics:** Compare (1) Total token cost/spend, (2) Maintenance task success rate, and (3) Hypothesis Regression Rate in autonomous loops.  
* **Next Steps:** Review the LoCoBench and MemoryArena paper methodologies. Look at the architecture of Karpathy's auto-research GitHub repo to see how easily the Side Quests Brain Daemon could be hooked in as its memory layer.

## **📚 Literature Review Tracker**

*Use this section to drop links, DOIs, and notes from papers you read.*

* **Citation:** Nate B. Jones (2026). *Your AI Agent Fails 97.5% of Real Work. The Fix Isn't Coding.* (YouTube).  
  * **Key Finding:** Introduces the concept of the "Memory Wall"—agents excel at tasks but fail at jobs because they lack evolving context.  
  * **How it helps my idea:** Provides the perfect framing for why standard context windows fail in enterprise settings.  
* **Citation:** Matthew Berman (2026). *Hard Takeoff has started* (YouTube).  
  * **Key Finding:** Documents the transition into the "recursive self-improvement" phase of AI, where agents conduct continuous, autonomous research loops (using tools like OpenAI, Anthropic's agent SDK, and auto-research).  
  * **How it helps my idea:** Validates the immediate need for a system like Side Quests. If AI is going to run continuous overnight research loops, it needs an externalized graph to track its hypothesis history and prevent regression.  
* **Citation:** Andrej Karpathy (2026). *auto-research* (GitHub Repository).  
  * **Key Finding:** An open-source harness that allows an agent to work in an autonomous loop on a git feature branch, accumulating commits as it finds better settings.  
  * **How it helps my idea:** This is the perfect real-world codebase to inject Side Quests into to prove your methodology.  
* **Citation:** Alibaba Research Team (Expected \~2025/2026). *SWE-CI (Software Evolution Continuous Integration) Benchmark*.  
  * **Key Finding:** A benchmark testing agents across 100 codebases over 233 days and 71 consecutive updates. Found 75% of frontier models break previously working features during maintenance.  
  * **How it helps my idea:** This is the perfect stress-test environment for the Side Quests constraint ledger.  
* **Citation:** Scale AI & Center for AI Safety (Expected \~2025/2026). *The Remote Labor Index*.  
  * **Key Finding:** Tested frontier agents on 240 real Upwork freelance projects, resulting in a 97.5% failure rate.  
  * **How it helps my idea:** Proves that relying purely on the LLM's raw context reasoning is fundamentally broken for complex, real-world work.  
* **Citation:** *LoCoBench: A Benchmark for Long-Context Large Language Models in Complex Software Engineering* (ArXiv, Sept 2025).  
  * **Key Finding:** Introduces 8,000 scenarios testing context from 10k to 1M tokens. Specifically tracks "Multi-Session Memory Retention" (MMR) and architectural coherence across files.  
  * **How it helps my idea:** Provides a ready-made, highly structured framework to specifically test the token-bloat vs. memory efficiency hypothesis.  
* **Citation:** He et al., *MemoryArena: Benchmarking Agent Memory in Interdependent Multi-Session Agentic Tasks* (ArXiv, Feb 2026\) / Zhao et al., *AMA-Bench: Evaluating Long-Horizon Memory for Agentic Applications* (ArXiv, Feb 2026).  
  * **Key Finding:** Existing evaluations test memorization in isolation. These new benchmarks test interdependent tasks where agents must learn from past actions. *Crucially, they highlight that standard similarity-based retrieval (basic vector RAG) fails due to lack of causality.*  
  * **How it helps my idea:** This is the "smoking gun" that proves Side Quests' decision to use a Relational Knowledge Graph (Kùzu) rather than just a basic vector database is exactly what the academic and enterprise communities are desperately looking for right now.