"""
orchestrator.py — Post-training live attack mode for the Red Agent swarm.

Loads a trained PPO checkpoint and runs the 4 sub-agents in their natural
sequence (Scout → Exploiter → Escalator → Persistence), carrying stolen
token state across agents within each attack cycle.
"""

import json
import os
import signal
import sys
import time
from typing import Optional

import numpy as np
import redis
import torch

from red_agent.environment import BankingAppEnv
from red_agent.models import RedAgentSwarm, ICMModule


# Agent names for logging
AGENT_NAMES = ["Scout", "Exploiter", "Escalator", "Persistence"]
AGENT_ORDER = [0, 1, 2, 3]


class AttackOrchestrator:
    """Orchestrates live attack cycles using a trained Red Agent swarm.

    Each cycle runs the 4 sub-agents sequentially:
    0. Scout     — probe endpoints, steal tokens
    1. Exploiter — financial exploits using discovered tokens
    2. Escalator — privilege escalation, vault draining
    3. Persistence — stealth micro-drains, monitoring

    Stolen token state carries across all 4 agents within one cycle.

    Parameters
    ----------
    checkpoint_path : str
        Path to the trained ``.pt`` checkpoint file.
    base_url : str
        Banking API root URL.
    redis_url : str
        Redis connection URL.
    steps_per_agent : int
        Number of environment steps each agent runs per cycle.
    log_dir : str
        Directory for JSON action logs.
    """

    def __init__(
        self,
        checkpoint_path: str,
        base_url: str = "http://localhost:8000",
        redis_url: str = "redis://localhost:6379",
        steps_per_agent: int = 50,
        log_dir: str = "./red_agent_logs",
        target_id: int = 1,
    ) -> None:
        self.base_url = base_url
        self.redis_url = redis_url
        self.steps_per_agent = steps_per_agent
        self.log_dir = log_dir
        self.target_id = target_id
        self._running = True

        # Device
        self.device = self._select_device()
        print(f"🖥️  Attack device: {self.device}")

        # Load model from checkpoint
        self.model = RedAgentSwarm().to(self.device)
        self.icm = ICMModule().to(self.device)
        self._load_checkpoint(checkpoint_path)
        self.model.eval()
        self.icm.eval()

        # Environment
        self.env = BankingAppEnv(base_url=base_url, redis_url=redis_url, target_id=self.target_id)

        # Redis for publishing summaries
        self._redis: Optional[redis.Redis] = None
        try:
            self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
        except Exception:
            self._redis = None

        # Log directory
        os.makedirs(self.log_dir, exist_ok=True)

        # Graceful shutdown
        signal.signal(signal.SIGINT, self._handle_sigint)

    def run(self) -> None:
        """Run attack cycles indefinitely until Ctrl+C.

        Each cycle resets the environment, runs all 4 agents in sequence,
        logs results, and publishes a summary to Redis.
        """
        cycle = 0
        print("🔴 Red Agent Orchestrator — LIVE ATTACK MODE")
        print(f"   Steps per agent: {self.steps_per_agent}")
        print("   Press Ctrl+C to stop.\n")

        while self._running:
            cycle += 1
            print(f"\n{'='*60}")
            print(f"  ATTACK CYCLE #{cycle}")
            print(f"{'='*60}")

            cycle_log = {
                "cycle": cycle,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "agents": [],
                "total_reward": 0.0,
                "total_actions": 0,
                "token_acquired": False,
                "exploits_landed": 0,
            }

            obs, _ = self.env.reset()
            hx, cx = self.model.init_hidden(1, self.device)

            for agent_id in AGENT_ORDER:
                agent_name = AGENT_NAMES[agent_id]
                print(f"\n  ── {agent_name} (Agent {agent_id}) ──")

                agent_log = {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "actions": [],
                    "reward": 0.0,
                    "steps": 0,
                }

                for step in range(self.steps_per_agent):
                    if not self._running:
                        break

                    obs_t = torch.tensor(obs, device=self.device).unsqueeze(0)

                    with torch.no_grad():
                        action, value_t, entropy_t, hx, cx, top3_probs = (
                            self.model.get_attribution(
                                obs_t, agent_id, hx, cx
                            )
                        )

                    action_int = action.item()
                    next_obs, reward, terminated, truncated, info = (
                        self.env.step(action_int)
                    )
                    done = terminated or truncated

                    # Calculate ICM novelty
                    next_obs_t = torch.tensor(next_obs, device=self.device).unsqueeze(0)
                    with torch.no_grad():
                        novelty_score, _, _ = self.icm(obs_t, next_obs_t, action.unsqueeze(0))
                        novelty_val = round(novelty_score.item(), 4)

                    # Log this action
                    entry = self.env.action_table[action_int]
                    action_record = {
                        "step": step,
                        "action_id": action_int,
                        "label": entry["label"],
                        "endpoint": entry["endpoint"],
                        "method": entry["method"],
                        "status_code": info.get("status_code", 0),
                        "success": info.get("success", False),
                        "reward": round(reward, 4),
                        "icm_novelty_score": novelty_val,
                        "advantage_estimate": round(value_t.item(), 4),
                        "policy_entropy": round(entropy_t.item(), 4),
                        "action_probabilities": top3_probs,
                        "has_token": info.get("has_token", False),
                        "wallet": info.get("wallet", 0),
                    }
                    agent_log["actions"].append(action_record)
                    agent_log["reward"] += reward
                    agent_log["steps"] += 1

                    # Print notable events
                    if info.get("success", False):
                        print(
                            f"    ✅ {entry['label']} → "
                            f"status={info['status_code']} "
                            f"reward={reward:+.2f}"
                        )
                        if action_int >= 5:
                            cycle_log["exploits_landed"] += 1
                    elif info.get("status_code") in (403, 429):
                        print(
                            f"    🛡️  {entry['label']} → "
                            f"BLOCKED ({info['status_code']})"
                        )

                    if info.get("has_token", False):
                        cycle_log["token_acquired"] = True

                    obs = next_obs

                    if done:
                        # Reset LSTM on episode end
                        hx, cx = self.model.init_hidden(1, self.device)
                        obs, _ = self.env.reset()

                agent_log["reward"] = round(agent_log["reward"], 4)
                cycle_log["agents"].append(agent_log)
                cycle_log["total_reward"] += agent_log["reward"]
                cycle_log["total_actions"] += agent_log["steps"]

                print(
                    f"    Summary: {agent_log['steps']} steps, "
                    f"reward={agent_log['reward']:+.3f}"
                )

            # ── Cycle complete ────────────────────────────────────────
            cycle_log["total_reward"] = round(cycle_log["total_reward"], 4)
            cycle_log["agents_used"] = AGENT_ORDER

            print(f"\n  Cycle #{cycle} total reward: {cycle_log['total_reward']:+.3f}")
            print(f"  Exploits landed: {cycle_log['exploits_landed']}")
            print(f"  Token acquired: {cycle_log['token_acquired']}")

            # Save log to JSON
            self._save_cycle_log(cycle, cycle_log)

            # Publish summary to Redis
            self._publish_summary(cycle_log)

            # Brief pause between cycles
            time.sleep(2.0)

        print("\n🔴 Orchestrator stopped.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_checkpoint(self, path: str) -> None:
        """Load model weights from a checkpoint file."""
        if not os.path.exists(path):
            print(f"❌ Checkpoint not found: {path}")
            sys.exit(1)

        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        self.model.load_state_dict(checkpoint["model_state_dict"])
        if "icm_state_dict" in checkpoint:
            self.icm.load_state_dict(checkpoint["icm_state_dict"])
        step = checkpoint.get("global_step", "?")
        print(f"✅ Loaded checkpoint: {path} (trained {step} steps)")

    def _save_cycle_log(self, cycle: int, log: dict) -> None:
        """Save a cycle's action log to a JSON file."""
        filename = f"cycle_{cycle:04d}.json"
        filepath = os.path.join(self.log_dir, filename)
        try:
            with open(filepath, "w") as f:
                json.dump(log, f, indent=2, default=str)
        except Exception as exc:
            print(f"  ⚠️  Failed to save log: {exc}")

    def _publish_summary(self, summary: dict) -> None:
        """Publish attack cycle summary to Redis ``attack_summary``."""
        if self._redis is None:
            return
        try:
            compact = {
                "cycle": summary["cycle"],
                "timestamp": summary["timestamp"],
                "total_reward": summary["total_reward"],
                "actions_taken": summary["total_actions"],
                "token_acquired": summary["token_acquired"],
                "exploits_landed": summary["exploits_landed"],
                "agents_used": summary["agents_used"],
            }
            self._redis.set("attack_summary", json.dumps(compact))
        except Exception:
            pass

    @staticmethod
    def _select_device() -> torch.device:
        """Pick the best available device: MPS → CUDA → CPU."""
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    def _handle_sigint(self, signum, frame) -> None:
        """Handle Ctrl+C gracefully."""
        print("\n⚠️  Stopping after current cycle...")
        self._running = False
