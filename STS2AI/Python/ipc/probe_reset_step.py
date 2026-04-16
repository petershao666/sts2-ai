"""Mac/Linux milestone probe: reset + N steps on real HeadlessSim.

Proves the POSIX pipe port can actually drive the game, not just handshake.

Usage:
    python3 STS2AI/Python/ipc/probe_reset_step.py
    python3 STS2AI/Python/ipc/probe_reset_step.py --steps 10 --protocol bin
    python3 STS2AI/Python/ipc/probe_reset_step.py --auto-launch        # spawn our own sim
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
_PY_ROOT = _HERE.parents[1]
_IPC_ROOT = _HERE.parent
for _p in (_PY_ROOT, _IPC_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from binary_pipe_client import BinaryPipeClient
from pipe_client import PipeClient
from headless_sim_runner import start_headless_sim, stop_process
from simulator_api_error import SimulatorApiError


def _extract_state(result: dict) -> dict:
    if isinstance(result, dict) and isinstance(result.get("state"), dict):
        return result["state"]
    return result


def _action_payload(action: dict) -> dict:
    keep = ("action", "index", "card_index", "hand_index",
            "slot", "target_id", "target", "value")
    return {k: v for k, v in action.items() if k in keep}


def run_probe(*, port: int, protocol: str, steps: int,
              character: str, seed: str | None) -> int:
    client = BinaryPipeClient(port=port) if protocol == "bin" else PipeClient(port=port)
    client.connect(timeout_s=10)
    print(f"[probe] connected via {protocol} on port {port}")

    reset_params: dict = {"character_id": character, "ascension_level": 0}
    if seed:
        reset_params["seed"] = seed
    state = client.call("reset", reset_params)
    state = _extract_state(state)
    print(f"[probe] reset OK  state_type={state.get('state_type')!r}  "
          f"run_outcome={state.get('run_outcome')!r}")

    errors = 0
    for i in range(steps):
        st = (state.get("state_type") or "").lower()
        if st == "game_over" or state.get("terminal"):
            print(f"[probe] step {i}: terminal reached ({st}), stopping early")
            break

        legal = [a for a in (state.get("legal_actions") or [])
                 if isinstance(a, dict) and a.get("is_enabled") is not False]
        if not legal:
            print(f"[probe] step {i}: no legal actions  state_type={st!r}  skipping")
            state = _extract_state(client.call("state"))
            continue

        action = _action_payload(legal[0])
        try:
            result = client.call("step", action)
        except SimulatorApiError as exc:
            print(f"[probe] step {i}: rejected ({exc}); action={action}")
            errors += 1
            state = _extract_state(client.call("state"))
            continue

        state = _extract_state(result)
        print(f"[probe] step {i+1:>2}  action={action.get('action'):<20}  "
              f"→ state_type={state.get('state_type')!r}")

    client.close()
    print(f"[probe] DONE  steps_requested={steps}  errors={errors}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=15527)
    ap.add_argument("--protocol", choices=["bin", "json"], default="bin")
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--character", default="IRONCLAD")
    ap.add_argument("--seed", default="PROBE1")
    ap.add_argument("--auto-launch", action="store_true",
                    help="Start our own HeadlessSim (else expect one already running)")
    args = ap.parse_args()

    proc = None
    if args.auto_launch:
        print(f"[probe] launching HeadlessSim on port {args.port} ({args.protocol})...")
        proc = start_headless_sim(port=args.port, protocol=args.protocol,
                                   connect_timeout_s=15.0)
        print(f"[probe] HeadlessSim pid={proc.pid}")
        # Small settle so the pipe slot is fully owner-free before we reconnect.
        time.sleep(0.2)

    try:
        return run_probe(port=args.port, protocol=args.protocol,
                         steps=args.steps, character=args.character,
                         seed=args.seed)
    finally:
        if proc is not None:
            print("[probe] stopping HeadlessSim")
            stop_process(proc)


if __name__ == "__main__":
    raise SystemExit(main())
