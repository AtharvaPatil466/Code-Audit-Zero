import torch
import torch.nn as nn
from torch.distributions import Categorical
from typing import Tuple, List, Optional
from red_agent.models import OBS_DIM, HIDDEN_DIM, HEAD_DIM

class ParametricAgentHead(nn.Module):
    """
    Agent head structured for MultiDiscrete action spaces.
    Instead of a single N-way classification, this outputs K separate 
    classifications for each component of the structured action 
    (Method, Endpoint, Key, Value).
    """
    def __init__(self, action_dims: List[int], head_dim: int = HEAD_DIM) -> None:
        super().__init__()
        self.action_dims = action_dims
        
        self.policy_heads = nn.ModuleList([
            nn.Linear(head_dim, dim) for dim in action_dims
        ])
        self.value_head = nn.Linear(head_dim, 1)

    def forward(self, features: torch.Tensor) -> Tuple[List[torch.Tensor], torch.Tensor]:
        logits = [head(features) for head in self.policy_heads]
        value = self.value_head(features)
        return logits, value


class ParametricSwarm(nn.Module):
    """
    Swarm architecture updated to support structured actions.
    """
    def __init__(
        self,
        action_dims: List[int],
        obs_dim: int = OBS_DIM,
        hidden_dim: int = HIDDEN_DIM,
        head_dim: int = HEAD_DIM,
    ) -> None:
        super().__init__()
        self.action_dims = action_dims
        self.hidden_dim = hidden_dim

        self.fc1 = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
        )

        self.lstm = nn.LSTMCell(input_size=hidden_dim, hidden_size=hidden_dim)

        self.fc2 = nn.Sequential(
            nn.Linear(hidden_dim, head_dim),
            nn.ReLU(),
            nn.LayerNorm(head_dim),
        )

        # 4 Agents, each with multi-discrete parametric heads
        self.heads = nn.ModuleList([
            ParametricAgentHead(action_dims, head_dim) for _ in range(4)
        ])

    def get_action_and_value(
        self,
        obs: torch.Tensor,
        agent_id: int,
        hx: torch.Tensor,
        cx: torch.Tensor,
        action: Optional[torch.Tensor] = None,
    ):
        """Returns tuple of multi-discrete actions, total log_prob, total entropy, and value."""
        x = self.fc1(obs)
        hx, cx = self.lstm(x, (hx, cx))
        features = self.fc2(hx)

        logits_list, value = self.heads[agent_id](features)
        
        dists = [Categorical(logits=l) for l in logits_list]
        
        if action is None:
            action = torch.stack([dist.sample() for dist in dists], dim=-1)

        # Sum of independent log probabilities
        log_prob = torch.stack([dists[i].log_prob(action[:, i]) for i in range(len(dists))], dim=-1).sum(dim=-1)
        
        # Sum of independent entropies
        entropy = torch.stack([dist.entropy() for dist in dists], dim=-1).sum(dim=-1)

        return action, log_prob, entropy, value, hx, cx

    def init_hidden(self, batch_size: int = 1, device: Optional[torch.device] = None) -> Tuple[torch.Tensor, torch.Tensor]:
        dev = device or next(self.parameters()).device
        hx = torch.zeros(batch_size, self.hidden_dim, device=dev)
        cx = torch.zeros(batch_size, self.hidden_dim, device=dev)
        return hx, cx
