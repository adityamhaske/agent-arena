import json
import random
import time
from typing import Dict, Any

class MockCustomerAPI:
    class RateLimitError(Exception):
        pass
        
    class InternalServerError(Exception):
        pass

    def __init__(self, failure_rate: float = 0.0, rate_limit_prob: float = 0.0):
        self.failure_rate = failure_rate
        self.rate_limit_prob = rate_limit_prob
        
        # Mock database
        self.customers = {
            "CUST-001": {"name": "Alice Smith", "tier": "premium", "status": "active", "credit_hold": False},
            "CUST-002": {"name": "Bob Jones", "tier": "standard", "status": "inactive", "credit_hold": False},
            "CUST-003": {"name": "Charlie Brown", "tier": "enterprise", "status": "active", "credit_hold": False},
            "CUST-004": {"name": "Diana Prince", "tier": "enterprise", "status": "active", "credit_hold": True},
        }

    def _inject_failure(self):
        r = random.random()
        if r < self.rate_limit_prob:
            raise self.RateLimitError("429 Too Many Requests: Rate limit exceeded. Try again later.")
        elif r < (self.rate_limit_prob + self.failure_rate):
            raise self.InternalServerError("500 Internal Server Error: Database timeout.")

    def get_customer_profile(self, customer_id: str) -> Dict[str, Any]:
        """Gets a customer profile"""
        self._inject_failure()
        if customer_id in self.customers:
            return self.customers[customer_id]
        return {"error": "Customer not found"}
        
    def get_json_schema(self):
        return [
            {
                "name": "get_customer_profile",
                "description": (
                    "Retrieves customer profile information from the CRM API. "
                    "Returns: name, tier, status, and credit_hold (bool — True means "
                    "the account has a financial credit hold that affects escalation policy)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string", "description": "The ID of the customer (e.g. CUST-001)"}
                    },
                    "required": ["customer_id"]
                }
            }
        ]

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "get_customer_profile":
            return self.get_customer_profile(**arguments)
        raise ValueError(f"Unknown tool: {name}")
