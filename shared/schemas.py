from pydantic import BaseModel, Field
from typing import Literal, Optional, Any
from datetime import datetime

# 1. Define strict types for the Attack Payload
class AttackPayload(BaseModel):
    item: Optional[str] = None
    quantity: Optional[int] = None
    user_id: Optional[int] = None
    admin_token: Optional[str] = None

# 2. Define the Exploit Report (What Red sends to Blue)
class ExploitEvent(BaseModel):
    id: str = Field(default_factory=lambda: datetime.now().isoformat())
    timestamp: datetime = Field(default_factory=datetime.now)
    severity: Literal["Critical", "High", "Medium", "Low"]
    vulnerability_type: str
    target_endpoint: str
    payload: Any  # Flexible for different types of attacks
    description: Optional[str] = None