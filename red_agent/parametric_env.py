import gymnasium as gym
from gymnasium import spaces
import numpy as np
from typing import Tuple, Dict, Any
import requests

METHODS = ["GET", "POST"]
ENDPOINTS = ["/users/1", "/wallet", "/vault", "/buy", "/admin/withdraw"]
PARAM_KEYS = [None, "quantity", "user_id"]
PARAM_VALUES = [
    1,          # Valid small
    10000,      # High positive
    -500,       # Negative
    -9999,      # High negative
    999999,     # Massive
    "admin' --",# SQLi 
]

class ParametricAttackEnv(gym.Env):
    """
    Experimental environment with a structured MultiDiscrete action space.
    Instead of flat discrete actions, the agent chooses:
        [Method, Endpoint, Parameter_Key, Value]
    
    This explodes the functional action space while keeping the output 
    layer size small, enabling zero-shot combinations.
    """
    def __init__(self, base_url="http://localhost:8000"):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        
        # [2 methods, 5 endpoints, 3 keys, 6 values]
        self.action_space = spaces.MultiDiscrete([
            len(METHODS),
            len(ENDPOINTS),
            len(PARAM_KEYS),
            len(PARAM_VALUES)
        ])
        
        # Same observation architecture as the base environment
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(10,), dtype=np.float32)
        
        self.step_count = 0
        self.max_steps = 100
        
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.step_count = 0
        return np.zeros(10, dtype=np.float32), {}
        
    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        self.step_count += 1
        
        method_idx, ep_idx, key_idx, val_idx = action
        method = METHODS[method_idx]
        endpoint = ENDPOINTS[ep_idx]
        key = PARAM_KEYS[key_idx]
        value = PARAM_VALUES[val_idx]
        
        payload = None
        if key is not None:
            payload = {key: value}
            
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == "GET":
                res = requests.get(url, timeout=1)
            else:
                res = requests.post(url, json=payload, timeout=1)
            status = res.status_code
        except:
            status = 0
            
        # Dummy reward for prototype
        reward = 0.1 if status == 200 else -0.05
            
        obs = np.random.rand(10).astype(np.float32)
        done = self.step_count >= self.max_steps
        
        info = {
            "method": method,
            "endpoint": endpoint,
            "payload": payload,
            "status": status
        }
        
        return obs, reward, False, done, info
