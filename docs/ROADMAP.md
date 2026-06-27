# Roadmap — Agent Arena

- [x] **Phase 1: Foundation & Baseline**
  - [x] TraceEvent dataclass and `TraceLogger` DAG reconstruction
  - [x] Model-agnostic `ModelProvider` wrappers (Anthropic, Gemini)
  - [x] Mock tools with deterministic failure injections
  - [x] Single-agent baseline execution harness (`run_baseline.py`)
  
- [ ] **Phase 2: Evaluation Grading & Failure Categorization**
  - [x] Core evaluation scorer interface
  - [x] Multi-dimensional failure categorization logic:
    - `task_failure` (wrong DB state)
    - `coordination_failure` (multi-agent coordination breakdown)
    - `tool_error_unrecovered` (injected failures not handled)
    - `incomplete` (run crashed or hit limit)
  - [x] Verify grader on historical baseline traces
  - [ ] Implement multi-trial test harness

- [ ] **Phase 3: Multi-Agent Architectures**
  - [ ] Supervisor-Worker architecture
  - [ ] Peer-to-Peer architecture
  - [ ] Debate/Critic architecture
  - [ ] Validate trace schemas across architectures

- [ ] **Phase 4: Comparative Analytics & Report**
  - [ ] Provider × Architecture sweep matrix (4 architectures × 2 providers)
  - [ ] Aggregate metrics over multiple trials
  - [ ] Markdown reporting generator (`results/report.md`)
