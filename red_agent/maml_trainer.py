import time
import torch
import os
from typing import List

from red_agent.environment import BankingAppEnv
from red_agent.trainer import PPOTrainer
from red_agent.models import RedAgentSwarm

class MAMLPOCoordinator(PPOTrainer):
    """
    Model-Agnostic Meta Learning (MAML) wrapper for PPO.
    
    Instead of overfitting to a single target application, the Red Agent
    alternates learning across multiple environments (FastAPI Banking App
    and Flask Multi-Vuln App). The meta-gradient forces the model to discover
    generalized exploit patterns that adapt quickly to new targets.
    """
    def __init__(self, target_urls: List[str], redis_url: str = "redis://localhost:6379", **kwargs):
        # Base init uses the first URL
        super().__init__(base_url=target_urls[0], redis_url=redis_url, **kwargs)
        
        self.target_urls = target_urls
        # Create an environment for each target
        self.meta_envs = [
            BankingAppEnv(base_url=url, redis_url=redis_url, target_id=i+1)
            for i, url in enumerate(target_urls)
        ]
        
    def meta_train(self, meta_epochs: int = 10, inner_steps: int = 500):
        """
        Outer meta-learning loop.
        """
        print(f"\n🧠 Starting MAML Meta-Training across {len(self.meta_envs)} targets.")
        print(f"   Targets: {self.target_urls}")
        
        for epoch in range(meta_epochs):
            print(f"\n{'='*50}")
            print(f"  MAML Epoch {epoch+1}/{meta_epochs}")
            print(f"{'='*50}")
            
            for env_idx, env in enumerate(self.meta_envs):
                print(f"\n  🎯 INNER LOOP: Adapting to Target {env_idx+1} ({env.base_url})")
                
                # Swap the active environment
                self.env = env
                
                # Reset curriculum progress for the inner loop
                self.global_step = 0
                self.total_steps = inner_steps
                
                # Run standard inner PPO
                self.train()
                
            # Checkpoint the meta-weights
            chk_name = f"maml_meta_epoch_{epoch+1}.pt"
            self._save_checkpoint(chk_name)
            
if __name__ == "__main__":
    targets = ["http://localhost:8000", "http://localhost:8001"]
    maml = MAMLPOCoordinator(target_urls=targets, total_steps=500)
    print("✅ MAML Trainer initialized and ready for cross-domain meta-learning.")
