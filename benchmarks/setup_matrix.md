# SideQuest Brain — Benchmark Setup Matrix

This matrix defines the environmental requirements for local benchmark execution.

| Benchmark | Python Version | Docker Required | Disk Space (Est) | GPU Recommended | Env Vars Required |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **SWE-CI** | 3.11+ | Yes | 50 GB | No | `GITHUB_TOKEN` |
| **LoCoBench** | 3.10+ | No | 10 GB | Yes | `OPENAI_API_KEY` or `OLLAMA_BASE` |
| **AMA-Bench** | 3.11+ | No | 5 GB | Yes | `HUGGING_FACE_HUB_TOKEN` |
| **MemoryArena** | 3.11+ | Yes | 15 GB | No | `BRAIN_SOCK_PATH` |
| **AutoResearch** | 3.11+ | No | 1 GB | No | `SIM_SEED` |

## Detail Notes

### SWE-CI
- **Docker:** Required for repository sandboxing and commit span checkout.
- **Disk:** Large due to cloning multiple full repositories with history.

### LoCoBench
- **GPU:** Recommended for local 1M context models (e.g., Llama 3.1 70B via Ollama).
- **Scale:** Performance degrades significantly without local GPU acceleration for long-context reasoning.

### AMA-Bench
- **Data:** Datasets are hosted on Hugging Face; `huggingface-cli login` recommended.

### MemoryArena
- **Docker:** Used for web/shopping environments.
- **Brain Integration:** Requires a running `brain_daemon.py` on the specified Unix socket.

### AutoResearch (B52)
- **Isolation:** Must use `git worktree` or temporary directory. Do not run in project root.
- **Harness:** Python-based `benchmarks/autoresearch/harness.py`.
