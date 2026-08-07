import sqlite3
import json
from typing import Dict, Any, Optional

class TicketingSystem:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._setup()
        
    def _setup(self):
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT,
                status TEXT,
                tier TEXT,
                description TEXT
            )
        ''')
        self.conn.commit()

    def create_ticket(self, customer_id: str, description: str, status: str = "open", tier: str = "standard") -> Dict[str, Any]:
        c = self.conn.cursor()
        c.execute('INSERT INTO tickets (customer_id, description, status, tier) VALUES (?, ?, ?, ?)', 
                  (customer_id, description, status, tier))
        self.conn.commit()
        return {"ticket_id": c.lastrowid, "status": "created"}

    def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        c = self.conn.cursor()
        c.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,))
        row = c.fetchone()
        if row:
            return dict(row)
        return {"error": "Ticket not found"}

    def update_ticket(self, ticket_id: int, status: Optional[str] = None, tier: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
        c = self.conn.cursor()
        updates = []
        params = []
        if status:
            updates.append("status = ?")
            params.append(status)
        if tier:
            updates.append("tier = ?")
            params.append(tier)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
            
        if not updates:
            return {"error": "No fields to update"}
            
        params.append(ticket_id)
        query = f"UPDATE tickets SET {', '.join(updates)} WHERE id = ?"
        c.execute(query, params)
        self.conn.commit()
        
        if c.rowcount == 0:
            return {"error": "Ticket not found"}
        return {"status": "updated", "ticket_id": ticket_id}

    def search_tickets(self, customer_id: str) -> Dict[str, Any]:
        c = self.conn.cursor()
        c.execute('SELECT * FROM tickets WHERE customer_id = ?', (customer_id,))
        rows = c.fetchall()
        return {"tickets": [dict(r) for r in rows]}
        
    def get_json_schema(self):
        return [
            {
                "name": "create_ticket",
                "description": "Creates a new support ticket",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "description": {"type": "string"},
                        "status": {"type": "string", "enum": ["open", "closed", "escalated", "on_hold"]},
                        "tier": {"type": "string", "enum": ["standard", "premium", "enterprise"]}
                    },
                    "required": ["customer_id", "description"]
                }
            },
            {
                "name": "get_ticket",
                "description": "Retrieves an existing ticket by its integer ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "integer"}
                    },
                    "required": ["ticket_id"]
                }
            },
            {
                "name": "update_ticket",
                "description": "Updates the status, tier, and/or description of a ticket",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "integer"},
                        "status": {"type": "string", "enum": ["open", "closed", "escalated", "on_hold"]},
                        "tier": {"type": "string", "enum": ["standard", "premium", "enterprise"]},
                        "description": {"type": "string", "description": "Full replacement text for the ticket description"}
                    },
                    "required": ["ticket_id"]
                }
            },
            {
                "name": "search_tickets",
                "description": "Searches for tickets belonging to a specific customer_id",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"}
                    },
                    "required": ["customer_id"]
                }
            }
        ]
        
    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "create_ticket":
            return self.create_ticket(**arguments)
        elif name == "get_ticket":
            return self.get_ticket(**arguments)
        elif name == "update_ticket":
            return self.update_ticket(**arguments)
        elif name == "search_tickets":
            return self.search_tickets(**arguments)
        raise ValueError(f"Unknown tool: {name}")
