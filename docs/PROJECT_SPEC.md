# Project Specification: Agent Arena

## The North Star
Agent Arena evaluates whether multi-agent coordination failures are structural (caused by information loss at architectural boundaries, such as handoffs, delegation, and summarizations) rather than capability-based (due to a model lacking reasoning skills). 

Instead of treating multi-agent frameworks as opaque black boxes, this harness forces all architectures to use a normalized trace format. This allows us to definitively separate task failures (where an agent made a bad logical decision despite having the right data) from coordination failures (where the architecture itself prevented the agent from seeing the data).

## Key Finding
On an information asymmetry trap task (where an agent needs a specific boolean flag to execute a policy, but a different agent holds the tool to fetch it):
- `peer_to_peer` failed 100% of the time (0/5 trials). A rigid, hard-coded JSON handoff schema between the two agents dropped the `credit_hold` field entirely.
- `supervisor_worker` failed probabilistically (29% of the time). Its success depended entirely on whether an intermediate CRM Worker agent happened to include the field when generating a natural-language summary for the supervisor. 

This proves that multi-agent decomposition can silently drop critical information at coordination boundaries, entirely independent of the underlying model capability.
