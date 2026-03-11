"""
trainer.py — PPO training engine for the Red Agent swarm.

Contains:
- ``RolloutBuffer``: stores transitions with per-step ``agent_id``, computes
  GAE advantages and returns.
- ``PPOTrainer``: full training loop with agent rotation schedule, LSTM state
  management (reset on done), ICM intrinsic rewards, checkpointing, and
  multi-epoch mini-batch updates.
"""

import os
import time
from collections import deque
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from red_agent.environment import BankingAppEnv, OBS_DIM, NUM_ACTIONS
from red_agent.models import RedAgentSwarm, ICMModule


# ---------------------------------------------------------------------------
# Rollout buffer
# ---------------------------------------------------------------------------

class RolloutBuffer:
    """Fixed-size buffer that stores PPO rollout data and computes GAE.

    Each stored transition includes the ``agent_id`` that was active, so the
    PPO update can re-apply the correct action mask.

    Parameters
    ----------
    capacity : int
        Number of transition steps the buffer can hold.
    obs_dim : int
        Observation vector size.
    gamma : float
        Discount factor for GAE.
    gae_lambda : float
        Lambda for GAE.
    device : torch.device
        Device to place tensors on.
    """

    def __init__(
        self,
        capacity: int = 2048,
        obs_dim: int = OBS_DIM,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        device: torch.device = torch.device("cpu"),
    ) -> None:
        self.capacity = capacity
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.device = device

        # Pre-allocate numpy arrays (filled during collection, converted later)
        self.obs = np.zeros((capacity, obs_dim), dtype=np.float32)
        self.next_obs = np.zeros((capacity, obs_dim), dtype=np.float32)
        self.actions = np.zeros(capacity, dtype=np.int64)
        self.rewards = np.zeros(capacity, dtype=np.float32)
        self.values = np.zeros(capacity, dtype=np.float32)
        self.log_probs = np.zeros(capacity, dtype=np.float32)
        self.dones = np.zeros(capacity, dtype=np.float32)
        self.agent_ids = np.zeros(capacity, dtype=np.int64)

        # Computed after rollout
        self.advantages = np.zeros(capacity, dtype=np.float32)
        self.returns = np.zeros(capacity, dtype=np.float32)

        self.pos = 0
        self.full = False

    def add(
        self,
        obs: np.ndarray,
        action: int,
        reward: float,
        value: float,
        log_prob: float,
        done: bool,
        next_obs: np.ndarray,
        agent_id: int,
    ) -> None:
        """Store a single transition."""
        self.obs[self.pos] = obs
        self.actions[self.pos] = action
        self.rewards[self.pos] = reward
        self.values[self.pos] = value
        self.log_probs[self.pos] = log_prob
        self.dones[self.pos] = float(done)
        self.next_obs[self.pos] = next_obs
        self.agent_ids[self.pos] = agent_id

        self.pos += 1
        if self.pos >= self.capacity:
            self.full = True

    def compute_gae(self, last_value: float) -> None:
        """Compute Generalized Advantage Estimation.

        Parameters
        ----------
        last_value : float
            V(s_T) bootstrap value for the state after the last stored step.
        """
        n = self.pos
        last_gae = 0.0

        for t in reversed(range(n)):
            if t == n - 1:
                next_non_terminal = 1.0 - self.dones[t]
                next_value = last_value
            else:
                next_non_terminal = 1.0 - self.dones[t]
                next_value = self.values[t + 1]

            delta = (
                self.rewards[t]
                + self.gamma * next_value * next_non_terminal
                - self.values[t]
            )
            last_gae = delta + self.gamma * self.gae_lambda * next_non_terminal * last_gae
            self.advantages[t] = last_gae

        self.returns[:n] = self.advantages[:n] + self.values[:n]

    def get_batches(self, batch_size: int = 64):
        """Yield shuffled mini-batch indices for PPO update epochs.

        Yields
        ------
        indices : np.ndarray
            Array of indices for one mini-batch.
        """
        n = self.pos
        indices = np.arange(n)
        np.random.shuffle(indices)

        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            yield indices[start:end]

    def to_tensors(self):
        """Convert numpy arrays to device tensors (called once before update)."""
        n = self.pos
        return {
            "obs": torch.tensor(self.obs[:n], device=self.device),
            "next_obs": torch.tensor(self.next_obs[:n], device=self.device),
            "actions": torch.tensor(self.actions[:n], device=self.device),
            "rewards": torch.tensor(self.rewards[:n], device=self.device),
            "values": torch.tensor(self.values[:n], device=self.device),
            "log_probs": torch.tensor(self.log_probs[:n], device=self.device),
            "dones": torch.tensor(self.dones[:n], device=self.device),
            "agent_ids": torch.tensor(self.agent_ids[:n], device=self.device),
            "advantages": torch.tensor(self.advantages[:n], device=self.device),
            "returns": torch.tensor(self.returns[:n], device=self.device),
        }

    def reset(self) -> None:
        """Reset the buffer for the next rollout."""
        self.pos = 0
        self.full = False


# ---------------------------------------------------------------------------
# PPO Trainer
# ---------------------------------------------------------------------------

# Default rotation schedule if curriculum is disabled
ROTATION_SCHEDULE = [0, 1, 0, 2, 1, 3, 0, 1, 2, 3]


def _select_device() -> torch.device:
    """Pick the best available device: MPS → CUDA → CPU."""
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


class PPOTrainer:
    """Full PPO trainer for the Red Agent swarm.

    Manages the training loop: rollout collection with LSTM state threading
    and agent rotation, GAE computation, multi-epoch clipped PPO updates,
    ICM intrinsic reward injection, and periodic checkpointing.

    Parameters
    ----------
    base_url : str
        Banking API root URL.
    redis_url : str
        Redis connection URL.
    total_steps : int
        Total environment steps to train for.
    checkpoint_dir : str
        Directory for saving checkpoints.
    resume : bool
        If ``True``, load the latest checkpoint and continue.
    rollout_length : int
        Steps per rollout before PPO update (default 2048).
    ppo_epochs : int
        Number of epochs per PPO update (default 4).
    batch_size : int
        Mini-batch size (default 64).
    lr : float
        Adam learning rate (default 3e-4).
    gamma : float
        GAE discount factor (default 0.99).
    gae_lambda : float
        GAE lambda (default 0.95).
    clip_eps : float
        PPO clip epsilon (default 0.2).
    value_coeff : float
        Value loss coefficient (default 0.5).
    entropy_coeff : float
        Entropy bonus coefficient (default 0.01).
    icm_coeff : float
        ICM loss coefficient (default 0.1).
    max_grad_norm : float
        Gradient clipping norm (default 0.5).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        redis_url: str = "redis://localhost:6379",
        total_steps: int = 500_000,
        checkpoint_dir: str = "./red_agent_checkpoints",
        resume: bool = False,
        rollout_length: int = 2048,
        ppo_epochs: int = 4,
        batch_size: int = 64,
        lr: float = 3e-4,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_eps: float = 0.2,
        value_coeff: float = 0.5,
        entropy_coeff: float = 0.01,
        icm_coeff: float = 0.1,
        max_grad_norm: float = 0.5,
        curriculum: bool = True,
        target_id: int = 1,
    ) -> None:
        self.total_steps = total_steps
        self.checkpoint_dir = checkpoint_dir
        self.rollout_length = rollout_length
        self.ppo_epochs = ppo_epochs
        self.batch_size = batch_size
        self.clip_eps = clip_eps
        self.value_coeff = value_coeff
        self.entropy_coeff = entropy_coeff
        self.icm_coeff = icm_coeff
        self.max_grad_norm = max_grad_norm
        self.curriculum = curriculum
        self.target_id = target_id

        # Device
        self.device = _select_device()
        print(f"🖥️  Device: {self.device}")

        # Environment
        self.env = BankingAppEnv(
            base_url=base_url,
            redis_url=redis_url,
            target_id=target_id,
        )

        # Models
        self.model = RedAgentSwarm().to(self.device)
        self.icm = ICMModule().to(self.device)

        # Single optimizer for both model + ICM
        self.optimizer = optim.Adam(
            list(self.model.parameters()) + list(self.icm.parameters()),
            lr=lr,
        )

        # Rollout buffer
        self.buffer = RolloutBuffer(
            capacity=rollout_length,
            gamma=gamma,
            gae_lambda=gae_lambda,
            device=self.device,
        )

        # Training state
        self.global_step = 0
        self.schedule_idx = 0
        self.episode_rewards: deque = deque(maxlen=100)
        self._current_ep_reward = 0.0
        self._episodes_done = 0

        # LSTM hidden state (single env, batch=1)
        self.hx, self.cx = self.model.init_hidden(1, self.device)

        # Checkpoint directory
        os.makedirs(self.checkpoint_dir, exist_ok=True)

        # Resume from checkpoint
        if resume:
            self._load_checkpoint()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _get_current_schedule(self) -> list[int]:
        """Return the active agent rotation schedule based on curriculum progress."""
        if not self.curriculum:
            return ROTATION_SCHEDULE

        progress = self.global_step / max(self.total_steps, 1)

        # Phase 1 (0-33%): Scaffold - only Scout
        if progress < 0.33:
            return [0]
            
        # Phase 2 (33-66%): Exploit - Scout + Exploiter
        elif progress < 0.66:
            return [0, 1, 0, 1]
            
        # Phase 3 (66%+): Full Swarm - All 4 Agents
        else:
            return ROTATION_SCHEDULE

    def train(self) -> None:
        """Run the full PPO training loop until ``total_steps``."""
        print(
            f"🚀 Starting PPO training | target={self.total_steps} steps "
            f"| rollout={self.rollout_length} | device={self.device} "
            f"| curriculum={self.curriculum}"
        )

        obs, _ = self.env.reset()
        last_phase = -1

        while self.global_step < self.total_steps:
            # Curriculum logging
            current_schedule = self._get_current_schedule()
            current_phase = hash(tuple(current_schedule))
            if current_phase != last_phase:
                print(f"🎓 Curriculum Update: Active Agents → {sorted(list(set(current_schedule)))}")
                last_phase = current_phase

            # ── Collect rollout ───────────────────────────────────────
            self.buffer.reset()
            rollout_start = time.time()

            for _ in range(self.rollout_length):
                agent_id = current_schedule[
                    self.schedule_idx % len(current_schedule)
                ]

                obs_t = torch.tensor(obs, device=self.device).unsqueeze(0)

                with torch.no_grad():
                    action, log_prob, _, value, new_hx, new_cx = (
                        self.model.get_action_and_value(
                            obs_t, agent_id, self.hx, self.cx
                        )
                    )

                action_int = action.item()
                log_prob_f = log_prob.item()
                value_f = value.item()

                next_obs, reward, terminated, truncated, info = self.env.step(
                    action_int
                )

                # ICM intrinsic reward
                with torch.no_grad():
                    next_obs_t = torch.tensor(
                        next_obs, device=self.device
                    ).unsqueeze(0)
                    intrinsic, _, _ = self.icm(
                        obs_t, next_obs_t, action
                    )
                    reward += intrinsic.item()

                done = terminated or truncated

                self.buffer.add(
                    obs=obs,
                    action=action_int,
                    reward=reward,
                    value=value_f,
                    log_prob=log_prob_f,
                    done=done,
                    next_obs=next_obs,
                    agent_id=agent_id,
                )

                self._current_ep_reward += reward
                self.global_step += 1
                self.schedule_idx += 1

                # LSTM state management
                if done:
                    # Reset LSTM on episode boundary
                    self.hx, self.cx = self.model.init_hidden(1, self.device)
                    obs, _ = self.env.reset()
                    self.episode_rewards.append(self._current_ep_reward)
                    self._current_ep_reward = 0.0
                    self._episodes_done += 1
                else:
                    self.hx = new_hx.detach()
                    self.cx = new_cx.detach()
                    obs = next_obs

                # Periodic checkpoint
                if self.global_step % 10_000 == 0 and self.global_step > 0:
                    self._save_checkpoint("red_agent_latest.pt")

            # ── Compute GAE ───────────────────────────────────────────
            with torch.no_grad():
                last_obs_t = torch.tensor(obs, device=self.device).unsqueeze(0)
                last_agent = current_schedule[
                    self.schedule_idx % len(current_schedule)
                ]
                last_val, _, _ = self.model.get_value(
                    last_obs_t, last_agent, self.hx, self.cx
                )
                self.buffer.compute_gae(last_val.item())

            # ── PPO update ────────────────────────────────────────────
            loss_info = self._ppo_update()
            rollout_time = time.time() - rollout_start

            # ── Logging ───────────────────────────────────────────────
            avg_reward = (
                np.mean(self.episode_rewards) if self.episode_rewards else 0.0
            )
            print(
                f"[Step {self.global_step:>8d}/{self.total_steps}] "
                f"ep_done={self._episodes_done} | "
                f"avg_reward={avg_reward:+.3f} | "
                f"policy_loss={loss_info['policy_loss']:.4f} | "
                f"value_loss={loss_info['value_loss']:.4f} | "
                f"entropy={loss_info['entropy']:.4f} | "
                f"icm_fwd={loss_info['icm_forward']:.4f} | "
                f"time={rollout_time:.1f}s"
            )

        # Final checkpoint
        self._save_checkpoint("red_agent_final.pt")
        self._save_checkpoint("red_agent_latest.pt")
        print("✅ Training complete.")

    # ------------------------------------------------------------------
    # PPO update
    # ------------------------------------------------------------------

    def _ppo_update(self) -> dict:
        """Run multi-epoch clipped PPO update over the rollout buffer.

        Returns
        -------
        dict
            Averaged loss components for logging.
        """
        data = self.buffer.to_tensors()

        # Normalise advantages
        adv = data["advantages"]
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)

        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        total_icm_fwd = 0.0
        total_icm_inv = 0.0
        n_updates = 0

        for _ in range(self.ppo_epochs):
            for batch_idx in self.buffer.get_batches(self.batch_size):
                b_obs = data["obs"][batch_idx]
                b_next_obs = data["next_obs"][batch_idx]
                b_actions = data["actions"][batch_idx]
                b_old_log_probs = data["log_probs"][batch_idx]
                b_advantages = adv[batch_idx]
                b_returns = data["returns"][batch_idx]
                b_agent_ids = data["agent_ids"][batch_idx]

                # ── Per-sample forward pass (needed because agent_id varies) ─
                new_log_probs = []
                new_entropies = []
                new_values = []

                # Use fresh LSTM state for each mini-batch (no cross-batch leaking)
                mb_hx, mb_cx = self.model.init_hidden(1, self.device)

                for i in range(len(batch_idx)):
                    obs_i = b_obs[i].unsqueeze(0)
                    act_i = b_actions[i].unsqueeze(0)
                    aid_i = b_agent_ids[i].item()

                    _, lp, ent, val, mb_hx, mb_cx = (
                        self.model.get_action_and_value(
                            obs_i, aid_i, mb_hx, mb_cx, action=act_i,
                        )
                    )
                    new_log_probs.append(lp)
                    new_entropies.append(ent)
                    new_values.append(val.squeeze(-1))

                new_log_probs = torch.cat(new_log_probs)
                new_entropies = torch.cat(new_entropies)
                new_values = torch.cat(new_values)

                # ── Clipped surrogate loss ─
                ratio = (new_log_probs - b_old_log_probs).exp()
                surr1 = ratio * b_advantages
                surr2 = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps) * b_advantages
                policy_loss = -torch.min(surr1, surr2).mean()

                # ── Value loss ─
                value_loss = F.mse_loss(new_values, b_returns)

                # ── Entropy bonus ─
                entropy_bonus = new_entropies.mean()

                # ── ICM losses ─
                intrinsic, icm_fwd_loss, icm_inv_loss = self.icm(
                    b_obs, b_next_obs, b_actions
                )

                # ── Total loss ─
                loss = (
                    policy_loss
                    + self.value_coeff * value_loss
                    - self.entropy_coeff * entropy_bonus
                    + self.icm_coeff * (icm_fwd_loss + icm_inv_loss)
                )

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(
                    list(self.model.parameters()) + list(self.icm.parameters()),
                    self.max_grad_norm,
                )
                self.optimizer.step()

                total_policy_loss += policy_loss.item()
                total_value_loss += value_loss.item()
                total_entropy += entropy_bonus.item()
                total_icm_fwd += icm_fwd_loss.item()
                total_icm_inv += icm_inv_loss.item()
                n_updates += 1

        n = max(n_updates, 1)
        return {
            "policy_loss": total_policy_loss / n,
            "value_loss": total_value_loss / n,
            "entropy": total_entropy / n,
            "icm_forward": total_icm_fwd / n,
            "icm_inverse": total_icm_inv / n,
        }

    # ------------------------------------------------------------------
    # Checkpointing
    # ------------------------------------------------------------------

    def _save_checkpoint(self, filename: str) -> None:
        """Save training state to a checkpoint file.

        Checkpoint contents: model weights, ICM weights, optimizer state,
        global step count, rotation schedule index.
        """
        path = os.path.join(self.checkpoint_dir, filename)
        checkpoint = {
            "model_state_dict": self.model.state_dict(),
            "icm_state_dict": self.icm.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "global_step": self.global_step,
            "schedule_idx": self.schedule_idx,
            "episodes_done": self._episodes_done,
        }
        torch.save(checkpoint, path)
        print(f"💾 Checkpoint saved → {path} (step {self.global_step})")

    def _load_checkpoint(self) -> None:
        """Load the latest checkpoint and restore training state."""
        path = os.path.join(self.checkpoint_dir, "red_agent_latest.pt")
        if not os.path.exists(path):
            print(f"⚠️  No checkpoint found at {path}, starting fresh.")
            return

        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.icm.load_state_dict(checkpoint["icm_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self.global_step = checkpoint["global_step"]
        self.schedule_idx = checkpoint.get("schedule_idx", 0)
        self._episodes_done = checkpoint.get("episodes_done", 0)
        print(
            f"✅ Resumed from checkpoint: step {self.global_step}, "
            f"schedule_idx {self.schedule_idx}"
        )


