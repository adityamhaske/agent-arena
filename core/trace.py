import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

@dataclass
class TraceEvent:
    event_id: str
    timestamp: str
    event_type: str
    payload: Dict[str, Any]
    parent_event_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class TraceLogger:
    def __init__(self, filepath: str):
        self.filepath = filepath
        # Clear or create file
        open(self.filepath, 'a').close()

    def log(self, event: TraceEvent):
        with open(self.filepath, 'a') as f:
            f.write(json.dumps(asdict(event)) + "\n")

    @classmethod
    def reconstruct_dag(cls, filepath: str) -> Dict[str, Any]:
        """Reconstruct the DAG based on parent_event_id."""
        events = []
        with open(filepath, 'r') as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
        
        # Build tree representation
        event_dict = {e['event_id']: e for e in events}
        # Add children array
        for e in event_dict.values():
            e['children'] = []
            
        root_events = []
        for e in events:
            parent_id = e.get('parent_event_id')
            if parent_id and parent_id in event_dict:
                event_dict[parent_id]['children'].append(e)
            else:
                root_events.append(e)
                
        return root_events
