#!/usr/bin/env python3
"""
run_all.py — Launch the entire Code-Audit-Zero simulation from a single terminal.

Spawns Redis, the target banking app, Blue Agent, Gold Agent, and Red Agent
as subprocesses with color-coded, prefixed log output. Ctrl+C stops everything.

Usage:
    python run_all.py                    # Train Red Agent (default)
    python run_all.py --mode attack      # Run trained Red Agent in attack mode
    python run_all.py --red-steps 50000  # Custom training step count
    python run_all.py --no-blue          # Skip Blue Agent (solo Red training)
    python run_all.py --no-gold          # Skip Gold Agent
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import shutil


# ── ANSI color codes ─────────────────────────────────────────────────────

COLORS = {
    "REDIS":  "\033[90m",     # Gray
    "APP":    "\033[97m",     # White
    "RED":    "\033[91m",     # Red
    "BLUE":   "\033[94m",     # Blue
    "GOLD":   "\033[93m",     # Yellow
    "SYS":    "\033[92m",     # Green
}
RESET = "\033[0m"
BOLD = "\033[1m"


def color_print(tag: str, msg: str) -> None:
    """Print a message with a colored agent prefix."""
    color = COLORS.get(tag, "")
    print(f"{color}[{tag:>5s}]{RESET} {msg}", flush=True)


def stream_output(proc: subprocess.Popen, tag: str) -> None:
    """Read lines from a subprocess stdout and print with color prefix."""
    try:
        for line in iter(proc.stdout.readline, ""):
            if line:
                color_print(tag, line.rstrip())
    except (ValueError, OSError):
        pass  # Pipe closed during shutdown


# ── Process management ───────────────────────────────────────────────────

class ProcessManager:
    """Manages all child processes and handles graceful shutdown.

    Spawns each agent as a subprocess, streams their output with colored
    prefixes, and tears everything down on Ctrl+C.
    """

    def __init__(self) -> None:
        self.processes: dict[str, subprocess.Popen] = {}
        self.threads: list[threading.Thread] = []
        self._shutting_down = False

    def spawn(self, name: str, cmd: list[str], cwd: str, env: dict = None) -> None:
        """Spawn a subprocess and start streaming its output.

        Parameters
        ----------
        name : str
            Display name / tag for log prefix (e.g. 'RED', 'BLUE').
        cmd : list[str]
            Command and arguments to run.
        cwd : str
            Working directory for the process.
        env : dict, optional
            Extra environment variables to merge with os.environ.
        """
        full_env = os.environ.copy()
        full_env["PYTHONUNBUFFERED"] = "1"
        full_env["PYTHONPATH"] = cwd
        if env:
            full_env.update(env)

        color_print("SYS", f"Starting {name}: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=cwd,
            env=full_env,
            bufsize=1,
        )
        self.processes[name] = proc

        thread = threading.Thread(
            target=stream_output, args=(proc, name), daemon=True
        )
        thread.start()
        self.threads.append(thread)

    def shutdown(self) -> None:
        """Gracefully terminate all child processes."""
        if self._shutting_down:
            return
        self._shutting_down = True

        print()
        color_print("SYS", f"{BOLD}Shutting down all agents...{RESET}")

        for name in reversed(list(self.processes.keys())):
            proc = self.processes[name]
            if proc.poll() is None:
                color_print("SYS", f"Stopping {name} (PID {proc.pid})")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    color_print("SYS", f"Force killing {name}")
                    proc.kill()

        color_print("SYS", "All processes stopped.")

    def wait(self) -> None:
        """Block until all processes exit or Ctrl+C."""
        try:
            while True:
                # Check if any critical process died unexpectedly
                for name, proc in self.processes.items():
                    if proc.poll() is not None and name in ("APP",):
                        color_print("SYS", f"⚠️  {name} exited unexpectedly "
                                    f"(code {proc.returncode})")
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()


# ── Main ─────────────────────────────────────────────────────────────────

def find_python() -> str:
    """Find the best available Python interpreter."""
    # Prefer the Python that is currently running this script —
    # this ensures child processes inherit the active venv and its packages.
    import sys
    if sys.executable:
        return sys.executable
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".venv", "bin", "python"),
        shutil.which("python3"),
        shutil.which("python"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.realpath(c)
    return "python3"


def check_redis() -> bool:
    """Check if Redis is already running on localhost:6379."""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379)
        r.ping()
        return True
    except Exception:
        return False


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Code-Audit-Zero — Launch all agents from one terminal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode", choices=["train", "attack"], default="train",
        help="Red Agent mode: 'train' for PPO training, 'attack' for live mode (default: train)",
    )
    parser.add_argument(
        "--red-steps", type=int, default=500_000,
        help="Total training steps for Red Agent (default: 500000)",
    )
    parser.add_argument(
        "--no-blue", action="store_true",
        help="Skip launching the Blue Agent",
    )
    parser.add_argument(
        "--no-gold", action="store_true",
        help="Skip launching the Gold Agent",
    )
    parser.add_argument(
        "--no-redis", action="store_true",
        help="Skip launching Redis (if already running externally)",
    )
    parser.add_argument(
        "--app-port", type=int, default=8000,
        help="Port for the target banking app (default: 8000)",
    )
    parser.add_argument(
        "--target2", action="store_true",
        help="Launch the second target app (Flask) on port 8001 and point Red Agent there",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point — spawn all agents and stream their output."""
    args = parse_args()

    project_dir = os.path.dirname(os.path.abspath(__file__))
    python = find_python()

    print(f"\n{BOLD}{COLORS['SYS']}{'='*60}{RESET}")
    print(f"{BOLD}{COLORS['SYS']}  Code-Audit-Zero :: Local Simulation Launcher{RESET}")
    print(f"{BOLD}{COLORS['SYS']}{'='*60}{RESET}")
    print(f"  Python   : {python}")
    print(f"  Mode     : {args.mode}")
    print(f"  Blue     : {'ON' if not args.no_blue else 'OFF'}")
    print(f"  Gold     : {'ON' if not args.no_gold else 'OFF'}")
    print(f"  App Port : {args.app_port}")
    print(f"  Target 2 : {'ON (port 8001)' if args.target2 else 'OFF'}")
    print(f"{COLORS['SYS']}{'='*60}{RESET}\n")

    mgr = ProcessManager()
    signal.signal(signal.SIGINT, lambda s, f: mgr.shutdown())

    # ── 1. Redis ──────────────────────────────────────────────────────
    if not args.no_redis:
        if check_redis():
            color_print("SYS", "Redis already running on localhost:6379 ✓")
        else:
            redis_server = shutil.which("redis-server")
            if redis_server:
                mgr.spawn("REDIS", [redis_server, "--loglevel", "warning"], project_dir)
                time.sleep(1)
                color_print("SYS", "Redis started ✓")
            else:
                color_print("SYS", "⚠️  redis-server not found. Install with: brew install redis")
                color_print("SYS", "    Continuing without Redis (some features will be limited)")

    # ── 2. Target Application(s) ──────────────────────────────────────
    if args.target2:
        mgr.spawn(
            "APP2",
            [python, "target_app_2/main.py"],
            project_dir,
        )
        # If target2 is alone, or with target1? Let's just run both to be safe
    
    mgr.spawn(
        "APP1",
        [python, "-m", "uvicorn", "target_app.main:app",
         "--host", "0.0.0.0", "--port", str(args.app_port),
         "--reload", "--timeout-graceful-shutdown", "1"],
        project_dir,
    )
    time.sleep(2)  # Let the app start

    # ── 3. Blue Agent (Defender) ──────────────────────────────────────
    if not args.no_blue:
        mgr.spawn(
            "BLUE",
            [python, "-c",
             "from blue_agent.patcher import BlueDefenseAgent; "
             "agent = BlueDefenseAgent(); agent.run_surveillance()"],
            project_dir,
        )
        time.sleep(0.5)

    # ── 4. Gold Agent (Judge) ─────────────────────────────────────────
    if not args.no_gold:
        mgr.spawn(
            "GOLD",
            [python, "gold_agent/judge.py"],
            project_dir,
        )
        time.sleep(0.5)

    # ── 5. Red Agent (Attacker) ───────────────────────────────────────
    target_url = f"http://localhost:8001" if args.target2 else f"http://localhost:{args.app_port}"
    target_id = "2" if args.target2 else "1"
    
    red_cmd = [
        python, "red_agent/train.py",
        "--mode", args.mode,
        "--base-url", target_url,
        "--redis-url", "redis://localhost:6379",
        "--target-id", target_id,
        "--no-curriculum",
    ]
    if args.mode == "train":
        red_cmd += ["--steps", str(args.red_steps)]

    time.sleep(1)  # Let other agents settle
    mgr.spawn("RED", red_cmd, project_dir)

    # ── Wait ──────────────────────────────────────────────────────────
    color_print("SYS", f"{BOLD}All agents launched. Press Ctrl+C to stop.{RESET}")
    mgr.wait()


if __name__ == "__main__":
    main()
