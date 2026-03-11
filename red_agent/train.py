#!/usr/bin/env python3
"""
train.py — CLI entry point for the Red Agent PPO training system.

Usage examples
--------------
Train from scratch (500k steps):
    python red_agent/train.py

Train with custom step count:
    python red_agent/train.py --steps 50000

Resume training from checkpoint:
    python red_agent/train.py --resume

Run live attack mode with a trained checkpoint:
    python red_agent/train.py --mode attack

Attack mode with custom agent step count:
    python red_agent/train.py --mode attack --attack-steps 100
"""

import argparse
import os
import sys


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with all training/attack configuration.
    """
    parser = argparse.ArgumentParser(
        description="Red Agent PPO Training & Attack System for Code-Audit-Zero",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--mode",
        choices=["train", "attack"],
        default="train",
        help="Operating mode: 'train' runs PPO training, 'attack' runs "
             "the live orchestrator with a trained checkpoint (default: train)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume training from the latest checkpoint (train mode only)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=500_000,
        help="Total environment steps for training (default: 500000)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="Banking app API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default="redis://localhost:6379",
        help="Redis connection URL (default: redis://localhost:6379)",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=str,
        default="./red_agent_checkpoints",
        help="Directory for model checkpoints (default: ./red_agent_checkpoints)",
    )
    parser.add_argument(
        "--attack-steps",
        type=int,
        default=50,
        help="Steps per agent per attack cycle in attack mode (default: 50)",
    )
    parser.add_argument(
        "--no-curriculum",
        action="store_true",
        help="Disable curriculum training (default: curriculum is enabled)",
    )
    parser.add_argument(
        "--target-id",
        type=int,
        default=1,
        choices=[1, 2],
        help="Target Application ID (1=FastAPI, 2=Flask)",
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point — dispatches to train or attack mode."""
    args = parse_args()

    print("=" * 60)
    print("  Code-Audit-Zero :: Red Agent PPO System")
    print("=" * 60)
    print(f"  Mode           : {args.mode}")
    print(f"  Base URL       : {args.base_url}")
    print(f"  Redis URL      : {args.redis_url}")
    print(f"  Checkpoint Dir : {args.checkpoint_dir}")

    if args.mode == "train":
        print(f"  Total Steps    : {args.steps:,}")
        print(f"  Resume         : {args.resume}")
        print("=" * 60)

        from red_agent.trainer import PPOTrainer

        trainer = PPOTrainer(
            base_url=args.base_url,
            redis_url=args.redis_url,
            total_steps=args.steps,
            checkpoint_dir=args.checkpoint_dir,
            resume=args.resume,
            curriculum=not args.no_curriculum,
            target_id=args.target_id,
        )
        trainer.train()

    elif args.mode == "attack":
        print(f"  Steps/Agent    : {args.attack_steps}")
        print("=" * 60)

        from red_agent.orchestrator import AttackOrchestrator

        # Find checkpoint
        checkpoint_path = os.path.join(
            args.checkpoint_dir, "red_agent_latest.pt"
        )
        if not os.path.exists(checkpoint_path):
            # Try final checkpoint
            checkpoint_path = os.path.join(
                args.checkpoint_dir, "red_agent_final.pt"
            )
            if not os.path.exists(checkpoint_path):
                print(f"❌ No checkpoint found in {args.checkpoint_dir}")
                print("   Train a model first: python red_agent/train.py")
                sys.exit(1)

        orchestrator = AttackOrchestrator(
            checkpoint_path=checkpoint_path,
            base_url=args.base_url,
            redis_url=args.redis_url,
            steps_per_agent=args.attack_steps,
            target_id=args.target_id,
        )
        orchestrator.run()


if __name__ == "__main__":
    main()
