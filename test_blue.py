import time
import json
import redis
import requests

from blue_agent.patcher import BlueDefenseAgent

# Force a single mock exploit
print("Booting Agent...")
agent = BlueDefenseAgent()

print("Triggering mock analyze_threat...")
payload = {
    "action_id": 13,
    "endpoint": "/buy",
    "method": "POST",
    "payload": {"item": "flag", "quantity": -5},
    "status_code": 200,
    "reward": 1.0,
    "label": "Integer Underflow"
}
agent.analyze_threat(json.dumps(payload))
print("Finished!")
