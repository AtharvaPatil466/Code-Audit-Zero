"""
models.py — Neural network architectures for the Red Agent swarm.

Contains:
- ``RedAgentSwarm``: shared LSTM feature extractor + 4 agent heads with
  action masking, each producing policy logits and a scalar value estimate.
- ``ICMModule``: Intrinsic Curiosity Module that produces exploration bonuses
  for visiting novel (state, action) pairs.
"""

from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical

NUM_ACTIONS = 20
OBS_DIM = 10
HIDDEN_DIM = 128
HEAD_DIM = 64
ENCODER_DIM = 64

# Action ranges owned by each sub-agent
AGENT_ACTION_RANGES: list[Tuple[int, int]] = [
    (0, 5),    # Agent 0 — Scout       (actions 0–4)
    (5, 10),   # Agent 1 — Exploiter   (actions 5–9)
    (10, 15),  # Agent 2 — Escalator   (actions 10–14)
    (15, 20),  # Agent 3 — Persistence (actions 15–19)
]


class AgentHead(nn.Module):
    """A single sub-agent's policy + value head.

    Receives the shared LSTM hidden output and produces:
    - Policy logits over all 20 actions (masked externally).
    - Scalar state-value estimate.
    """

    def __init__(self, input_dim: int = HIDDEN_DIM) -> None:
        super().__init__()
        # Policy network
        self.policy_fc1 = nn.Linear(input_dim, HEAD_DIM)
        self.policy_fc2 = nn.Linear(HEAD_DIM, NUM_ACTIONS)

        # Value network
        self.value_fc1 = nn.Linear(input_dim, HEAD_DIM)
        self.value_fc2 = nn.Linear(HEAD_DIM, 1)

    def forward(self, features: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Return raw policy logits ``(B, 20)`` and value ``(B, 1)``."""
        policy = F.relu(self.policy_fc1(features))
        logits = self.policy_fc2(policy)

        value = F.relu(self.value_fc1(features))
        value = self.value_fc2(value)

        return logits, value


class RedAgentSwarm(nn.Module):
    """Multi-agent PPO model with shared LSTM backbone and 4 agent heads.

    Architecture
    ------------
    Shared feature extractor:
        ``Linear(20, 128) → ReLU → Linear(128, 128) → ReLU → LSTMCell(128, 128)``

    Each of the 4 agent heads receives the LSTM hidden state and produces
    policy logits (masked to valid action range) and a value estimate.

    LSTM hidden/cell states ``(hx, cx)`` are passed as **explicit** arguments
    and returned as outputs so the caller can zero them on episode boundaries.

    Parameters
    ----------
    obs_dim : int
        Observation dimension (default 20).
    hidden_dim : int
        LSTM / feature hidden dimension (default 128).
    """

    def __init__(
        self,
        obs_dim: int = OBS_DIM,
        hidden_dim: int = HIDDEN_DIM,
    ) -> None:
        super().__init__()

        self.hidden_dim = hidden_dim

        # Shared feature extractor
        self.fc1 = nn.Linear(obs_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.lstm = nn.LSTMCell(hidden_dim, hidden_dim)

        # 4 agent heads
        self.heads = nn.ModuleList([AgentHead(hidden_dim) for _ in range(4)])

        # Orthogonal initialisation (PPO best practice)
        self._init_weights()

    def _init_weights(self) -> None:
        """Apply orthogonal init to linear layers and zero biases."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.orthogonal_(module.weight, gain=1.0)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def _extract_features(
        self,
        obs: torch.Tensor,
        hx: torch.Tensor,
        cx: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Run observation through shared layers + LSTMCell.

        Parameters
        ----------
        obs : Tensor (B, obs_dim)
        hx, cx : Tensor (B, hidden_dim)

        Returns
        -------
        features, new_hx, new_cx
        """
        x = F.relu(self.fc1(obs))
        x = F.relu(self.fc2(x))
        new_hx, new_cx = self.lstm(x, (hx, cx))
        return new_hx, new_hx, new_cx  # features = new hidden state

    @staticmethod
    def _apply_action_mask(logits: torch.Tensor, agent_id: int) -> torch.Tensor:
        """Mask logits so only the agent's valid action range is selectable.

        Out-of-range actions are set to ``-1e8`` before softmax.
        """
        lo, hi = AGENT_ACTION_RANGES[agent_id]
        mask = torch.full_like(logits, -1e8)
        mask[:, lo:hi] = 0.0
        return logits + mask

    def get_action_and_value(
        self,
        obs: torch.Tensor,
        agent_id: int,
        hx: torch.Tensor,
        cx: torch.Tensor,
        action: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor,
               torch.Tensor, torch.Tensor]:
        """Forward pass for a specific sub-agent.

        Parameters
        ----------
        obs : Tensor (B, obs_dim)
        agent_id : int  (0-3)
        hx, cx : Tensor (B, hidden_dim)  — LSTM hidden/cell state
        action : Tensor (B,), optional
            If provided, evaluate log-prob and entropy of this action
            (used during PPO update).  If ``None``, sample a new action.

        Returns
        -------
        action : Tensor (B,)
        log_prob : Tensor (B,)
        entropy : Tensor (B,)
        value : Tensor (B, 1)
        new_hx : Tensor (B, hidden_dim)
        new_cx : Tensor (B, hidden_dim)
        """
        features, new_hx, new_cx = self._extract_features(obs, hx, cx)

        raw_logits, value = self.heads[agent_id](features)
        masked_logits = self._apply_action_mask(raw_logits, agent_id)
        dist = Categorical(logits=masked_logits)

        if action is None:
            action = dist.sample()

        log_prob = dist.log_prob(action)
        entropy = dist.entropy()

        return action, log_prob, entropy, value, new_hx, new_cx

    def get_value(
        self,
        obs: torch.Tensor,
        agent_id: int,
        hx: torch.Tensor,
        cx: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Return only the value estimate (used for bootstrapping).

        Returns
        -------
        value : Tensor (B, 1)
        new_hx, new_cx : Tensor (B, hidden_dim)
        """
        features, new_hx, new_cx = self._extract_features(obs, hx, cx)
        _, value = self.heads[agent_id](features)
        return value, new_hx, new_cx

    def get_attribution(
        self,
        obs: torch.Tensor,
        agent_id: int,
        hx: torch.Tensor,
        cx: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, list]:
        """Return action, value, entropy, and top-3 probabilities for attribution logging."""
        features, new_hx, new_cx = self._extract_features(obs, hx, cx)

        raw_logits, value = self.heads[agent_id](features)
        masked_logits = self._apply_action_mask(raw_logits, agent_id)
        dist = Categorical(logits=masked_logits)
        action = dist.sample()
        entropy = dist.entropy()
        
        # Calculate top-3 probabilities
        probs = torch.nn.functional.softmax(masked_logits, dim=-1)
        top_probs, top_indices = torch.topk(probs, 3, dim=-1)
        top3 = []
        for p, idx in zip(top_probs[0].tolist(), top_indices[0].tolist()):
            top3.append({"action": idx, "prob": round(p, 4)})

        return action, value, entropy, new_hx, new_cx, top3

    def init_hidden(
        self, batch_size: int = 1, device: Optional[torch.device] = None
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Return zeroed LSTM hidden/cell states."""
        dev = device or next(self.parameters()).device
        hx = torch.zeros(batch_size, self.hidden_dim, device=dev)
        cx = torch.zeros(batch_size, self.hidden_dim, device=dev)
        return hx, cx


class ICMModule(nn.Module):
    """Intrinsic Curiosity Module (ICM).

    Produces an intrinsic exploration reward proportional to the prediction
    error on the *next* encoded state, encouraging the agent to explore
    novel (state, action) transitions instead of replaying known exploits.

    Architecture
    ------------
    - **State encoder**: ``Linear(20, 64) → ReLU``
    - **Forward model**: encoded state (64) + one-hot action (20) → predicted
      next encoded state (64).  Loss = MSE vs actual.
    - **Inverse model**: encoded state (64) + encoded next state (64) →
      predicted action (20).  Loss = cross-entropy.

    Intrinsic reward = ``0.5 × MSE(predicted_next, actual_next)``.
    """

    def __init__(
        self,
        obs_dim: int = OBS_DIM,
        num_actions: int = NUM_ACTIONS,
        encoder_dim: int = ENCODER_DIM,
    ) -> None:
        super().__init__()

        self.num_actions = num_actions
        self.encoder_dim = encoder_dim

        # State encoder (shared for current and next state)
        self.encoder = nn.Sequential(
            nn.Linear(obs_dim, encoder_dim),
            nn.ReLU(),
        )

        # Forward model: encoded_state + one-hot action → predicted encoded next state
        self.forward_model = nn.Sequential(
            nn.Linear(encoder_dim + num_actions, encoder_dim),
            nn.ReLU(),
            nn.Linear(encoder_dim, encoder_dim),
        )

        # Inverse model: encoded_state + encoded_next_state → predicted action
        self.inverse_model = nn.Sequential(
            nn.Linear(encoder_dim * 2, encoder_dim),
            nn.ReLU(),
            nn.Linear(encoder_dim, num_actions),
        )

    def forward(
        self,
        obs: torch.Tensor,
        next_obs: torch.Tensor,
        actions: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Compute ICM losses and intrinsic reward.

        Parameters
        ----------
        obs : Tensor (B, obs_dim)
        next_obs : Tensor (B, obs_dim)
        actions : Tensor (B,)  — integer action ids

        Returns
        -------
        intrinsic_reward : Tensor (B,)
            ``0.5 × per-sample MSE`` of forward prediction error.
        forward_loss : Tensor (scalar)
            Mean forward model MSE loss.
        inverse_loss : Tensor (scalar)
            Mean inverse model cross-entropy loss.
        """
        # Encode states
        encoded_state = self.encoder(obs)                # (B, 64)
        encoded_next = self.encoder(next_obs)            # (B, 64)

        # One-hot encode actions
        action_onehot = F.one_hot(
            actions.long(), num_classes=self.num_actions
        ).float()  # (B, 20)

        # Forward model: predict next encoded state
        forward_input = torch.cat([encoded_state, action_onehot], dim=-1)
        predicted_next = self.forward_model(forward_input)  # (B, 64)

        # Intrinsic reward = 0.5 × per-sample MSE
        forward_error = (predicted_next - encoded_next.detach()).pow(2)
        intrinsic_reward = 0.5 * forward_error.mean(dim=-1)  # (B,)

        # Forward loss (for training the forward model)
        forward_loss = F.mse_loss(predicted_next, encoded_next.detach())

        # Inverse model: predict action from (state, next_state)
        inverse_input = torch.cat([encoded_state, encoded_next], dim=-1)
        predicted_action_logits = self.inverse_model(inverse_input)
        inverse_loss = F.cross_entropy(predicted_action_logits, actions.long())

        return intrinsic_reward, forward_loss, inverse_loss
