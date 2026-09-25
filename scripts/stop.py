"""Stop a running local AZFlow API instance without touching unrelated software."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from dev import compose_environment

REPO_ROOT = Path(__file__).resolve().parent.parent


def listening_pids(port: int) -> set[int]:
    """Return PIDs listening on the configured API TCP port."""
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {int(pid) for pid in result.stdout.split() if pid.isdigit()}


def process_cwd(pid: int) -> Path | None:
    """Return the process working directory when it is still available."""
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
    except (FileNotFoundError, PermissionError):
        return None


def process_command(pid: int) -> str:
    """Return the process command line."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, PermissionError):
        return ""
    return raw.replace(b"\0", b" ").decode(errors="replace").strip()


def is_azflow_process(pid: int) -> bool:
    """Accept only listeners launched from this AZFlow checkout."""
    if process_cwd(pid) != REPO_ROOT:
        return False

    command = process_command(pid)
    if "scripts/dev.py" in command or "scripts/debug.py" in command:
        return True

    # Uvicorn's reload worker is a multiprocessing child of scripts/dev.py.
    if "multiprocessing.spawn" in command:
        try:
            parent = int(Path(f"/proc/{pid}/stat").read_text().split()[3])
        except (FileNotFoundError, PermissionError, ValueError, IndexError):
            return False
        return process_cwd(parent) == REPO_ROOT and "scripts/dev.py" in process_command(
            parent
        )

    return False


def main() -> int:
    """Stop AZFlow only when every listener on its port is recognized."""
    config = compose_environment()
    port = int(config["AZFLOW_API_PORT"])
    pids = listening_pids(port)

    if not pids:
        print(f"No process is listening on AZFlow port {port}.")
        return 0

    unknown = {pid for pid in pids if not is_azflow_process(pid)}
    if unknown:
        details = "; ".join(
            f"PID {pid}: {process_command(pid) or 'unknown command'}"
            for pid in sorted(unknown)
        )
        print(
            f"Port {port} is in use by a process not recognized as AZFlow. "
            f"Refusing to stop it. {details}"
        )
        return 1

    # Stop the reload parent before its worker when both own the socket.
    ordered = sorted(
        pids,
        key=lambda pid: "scripts/dev.py" not in process_command(pid),
    )
    for pid in ordered:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Stopped AZFlow process PID {pid}.")
        except ProcessLookupError:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
