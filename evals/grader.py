import json
import sqlite3
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

@dataclass
class GradeResult:
    passed: bool
    score: float  # 0.0 to 1.0
    failure_category: Optional[str] = None  # task_failure, coordination_failure, tool_error_unrecovered, incomplete
    reason: str = ""
    metrics: Dict[str, Any] = None

def load_trace_events(trace_file: str) -> List[Dict[str, Any]]:
    events = []
    with open(trace_file, "r") as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    return events
