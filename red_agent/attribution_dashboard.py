#!/usr/bin/env python3
"""
attribution_dashboard.py — CLI tool to visualize deep attribution logs.

Reads the JSON cycle logs from Red Agent attacks and displays the 
action probabilities, entropy, ICM novelty, and value estimates
to help explain *why* the Red Agent made certain choices.
"""

import os
import json
import glob
import argparse

def main():
    parser = argparse.ArgumentParser(description="View Red Agent attack attribution")
    parser.add_argument("--log-dir", default="./red_agent_logs", help="Directory containing JSON logs")
    parser.add_argument("--limit", type=int, default=1, help="Number of recent cycles to display")
    args = parser.parse_args()
    
    # Find JSON files
    log_files = sorted(glob.glob(os.path.join(args.log_dir, "cycle_*.json")), reverse=True)
    if not log_files:
        print(f"❌ No cycle logs found in {args.log_dir}")
        return
        
    for log_file in log_files[:args.limit]:
        with open(log_file, "r") as f:
            data = json.load(f)
            
        print(f"\n{'='*110}")
        print(f"  ATTACK CYCLE #{data['cycle']} — {data['timestamp']}")
        print(f"{'='*110}")
        
        for agent in data["agents"]:
            print(f"\n  🕵️  AGENT: {agent['agent_name']} (Total Reward: {agent['reward']} | Steps: {agent['steps']})")
            print(f"  {'-'*108}")
            print(f"  {'Step':>4} | {'Action Label':<22} | {'Reward':>6} | {'Value':>6} | {'Entropy':>7} | {'Novelty':>7} | {'Top 3 Action Probabilities':<30}")
            print(f"  {'-'*4}-+-{'-'*22}-+-{'-'*6}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*30}")
            
            for act in agent["actions"]:
                step = act["step"]
                label = act["label"]
                reward = act["reward"]
                val = act.get("advantage_estimate", 0.0)
                ent = act.get("policy_entropy", 0.0)
                nov = act.get("icm_novelty_score", 0.0)
                
                probs = act.get("action_probabilities", [])
                prob_str = ", ".join([f"a{p['action']}:{p['prob']:.2f}" for p in probs])
                
                # Highlight successful actions
                marker = "✅" if act["success"] else "  "
                
                print(f"{marker}{step:>4} | {label:<22} | {reward:>+6.2f} | {val:>+6.2f} | {ent:>7.2f} | {nov:>7.3f} | {prob_str:<30}")

    print(f"\n{'='*110}\n")

if __name__ == "__main__":
    main()
