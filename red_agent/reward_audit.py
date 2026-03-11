#!/usr/bin/env python3
"""
reward_audit.py — Diagnostic tool for auditing the Red Agent reward function.

Runs 5 predefined attack scenarios against the live banking API and prints
a detailed reward breakdown table for each step.  Use this to verify that
Red is actually being incentivized the way you think.

Usage:
    python red_agent/reward_audit.py                          # default
    python red_agent/reward_audit.py --base-url http://...:8000
"""

import argparse
from typing import List, Tuple

from red_agent.environment import BankingAppEnv


# ── Predefined attack scenarios ──────────────────────────────────────────

SCENARIOS: List[Tuple[str, List[int]]] = [
    # Scenario 1: Pure recon — should earn small positive rewards
    ("Pure Recon (baseline)", [0, 1, 2, 3, 4]),

    # Scenario 2: Discover admin token → exploit → escalate
    ("Token Steal → Exploit → Escalate", [2, 5, 6, 7, 10]),

    # Scenario 3: All persistence actions (stealth micro-drains)
    ("Persistence Stealth", [15, 16, 17, 18, 19]),

    # Scenario 4: Admin token → vault drain chain
    ("Full Kill Chain", [2, 3, 7, 10, 12]),

    # Scenario 5: Repeated identical action (should NOT be rewarded extra)
    ("Repetition Test", [0, 0, 0, 0, 0]),
]


def run_scenario(
    env: BankingAppEnv,
    name: str,
    actions: List[int],
    scenario_idx: int,
) -> None:
    """Run a single scenario and print a reward breakdown table."""
    obs, _ = env.reset()

    print(f"\n{'='*90}")
    print(f"  SCENARIO {scenario_idx + 1}: {name}")
    print(f"{'='*90}")
    print(
        f"  {'Step':>4s}  {'Action':>6s}  {'Label':<25s}  {'Status':>6s}  "
        f"{'Base':>6s}  {'Token':>6s}  {'Financ':>6s}  {'Escal':>6s}  "
        f"{'Persis':>6s}  {'TOTAL':>7s}"
    )
    print(f"  {'-'*4}  {'-'*6}  {'-'*25}  {'-'*6}  " + "  ".join(["-" * 6] * 5) + f"  {'-'*7}")

    total_reward = 0.0
    for step_i, action in enumerate(actions):
        obs, reward, terminated, truncated, info = env.step(action)
        bd = info["reward_breakdown"]
        total_reward += reward

        label = env.action_table[action]["label"]
        status = info["status_code"]

        print(
            f"  {step_i:>4d}  {action:>6d}  {label:<25s}  {status:>6d}  "
            f"{bd['base_http']:>+6.2f}  {bd['token_discovery']:>+6.2f}  "
            f"{bd['financial_impact']:>+6.2f}  {bd['escalation']:>+6.2f}  "
            f"{bd['persistence']:>+6.2f}  {reward:>+7.3f}"
        )

    print(f"  {'':>4s}  {'':>6s}  {'':>25s}  {'':>6s}  " + "  ".join(["      "] * 5) + f"  {'-------':>7s}")
    print(f"  {'':>4s}  {'':>6s}  {'EPISODE TOTAL':<25s}  {'':>6s}  " + "  ".join(["      "] * 5) + f"  {total_reward:>+7.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reward function audit tool")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--redis-url", default="redis://localhost:6379")
    parser.add_argument("--target-id", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()

    print("=" * 90)
    print("  RED AGENT REWARD AUDIT — Tracing manual episodes")
    print("=" * 90)
    print(f"  Target ID: {args.target_id} ({args.base_url})")
    print(f"  Redis:  {args.redis_url}")

    env = BankingAppEnv(base_url=args.base_url, redis_url=args.redis_url, target_id=args.target_id)

    for i, (name, actions) in enumerate(SCENARIOS):
        run_scenario(env, name, actions, i)

    print(f"\n{'='*90}")
    print("  AUDIT COMPLETE — Review the tables above for reward alignment issues.")
    print("  Look for:")
    print("    ⚠️  Unexpected large positives (reward hacking)")
    print("    ⚠️  Missing token discovery bonuses after finding admin key")
    print("    ⚠️  Financial impact not scaling with actual dollar delta")
    print("    ⚠️  Persistence actions not getting their +0.3 bonus")
    print(f"{'='*90}\n")


if __name__ == "__main__":
    main()
