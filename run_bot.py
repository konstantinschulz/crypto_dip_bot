import os
import runpy
from pathlib import Path


def main() -> None:
    # Stable launcher for systemd and shell scripts.
    script_path = Path(__file__).with_name("dip_bot_v24.py")
    if not script_path.exists():
        raise FileNotFoundError(f"Bot script not found: {script_path}")

    runpy.run_path(str(script_path), run_name="__main__")


if __name__ == "__main__":
    main()

