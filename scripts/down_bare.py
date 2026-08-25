"""Cross-platform script to stop bare mode services."""
import os
import pathlib
import signal
import sys

RUN_DIR = pathlib.Path("run")

for pid_file in RUN_DIR.glob("*.pid"):
    try:
        content = pid_file.read_text().strip()
        if content:
            pid = int(content)
            try:
                sig_kill = getattr(signal, "SIGKILL", getattr(signal, "SIGTERM", 15))
                os.kill(pid, sig_kill)
            except OSError:
                pass
    except Exception as e:
        print(f"Error stopping PID from {pid_file}: {e}")
    finally:
        pid_file.unlink(missing_ok=True)

print("all stopped")
