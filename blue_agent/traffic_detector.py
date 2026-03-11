import time
import json
import redis
from collections import deque
from typing import Dict, List
from shared.config import settings, get_logger

logger = get_logger("TRAFFIC_DETECTOR")

class TrafficDetector:
    """
    Traffic-Based Anomaly Detector for the Blue Agent.
    Replaces static source-code analysis with behavioral heuristic detection.
    
    Monitors recent HTTP requests via Redis. Flags anomalous behavior 
    such as high error rates, uniform endpoint probing (recon), or
    known malicious payload signatures.
    """
    def __init__(self, redis_url: str = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", window_size: int = 50):
        self.r = redis.from_url(redis_url, decode_responses=True)
        self.window_size = window_size
        self.recent_events_by_endpoint: Dict[str, deque] = {}

    def analyze_event(self, event_json: str) -> bool:
        """
        Reads an event, updates connection history, and returns True if
        the traffic pattern is classified as malicious.
        """
        try:
            event = json.loads(event_json)
            endpoint = event.get("endpoint", "unknown")
            status = event.get("status_code", 0)
            payload = event.get("payload", {})
            method = event.get("method", "GET")
            
            if endpoint not in self.recent_events_by_endpoint:
                self.recent_events_by_endpoint[endpoint] = deque(maxlen=self.window_size)
                
            self.recent_events_by_endpoint[endpoint].append({
                "time": time.time(),
                "status": status,
                "payload_size": len(str(payload)) if payload else 0,
                "method": method
            })
            
            if self._is_anomalous(endpoint, payload):
                logger.warning(f"🚨 Traffic Anomaly Detected on {method} {endpoint}!")
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Traffic parsing error: {e}")
            return False

    def _is_anomalous(self, endpoint: str, payload: Dict) -> bool:
        """Simple heuristic-based anomaly thresholds."""
        history = self.recent_events_by_endpoint[endpoint]
        
        # 1. Payload signature heuristic
        payload_str = str(payload).lower()
        if any(sig in payload_str for sig in ["--", "1=1", "drop ", "select ", "../../", "http://"]):
            return True
            
        # 2. Burst rate heuristic (5 requests in 1 second)
        if len(history) >= 5:
            if history[-1]["time"] - history[-5]["time"] < 1.0:
                return True
                
        # 3. High failure rate heuristic (Many 400s or 500s)
        if len(history) >= 10:
            failures = sum(1 for h in history if h["status"] >= 400 or h["status"] == 0)
            if failures / len(history) > 0.8:
                return True

        return False
        
if __name__ == "__main__":
    d = TrafficDetector()
    print("Traffic Detector initialized.")
