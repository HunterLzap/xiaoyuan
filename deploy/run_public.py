import os
from pathlib import Path
import re
import subprocess
import sys
import threading


ROOT = Path(__file__).resolve().parents[1]


def capture(stream, destination):
    for line in stream:
        line = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", line)
        line = re.sub(
            r"""(?i)(authorization|api[_-]?key|password|token|[?&]key)(["\s:=]+)([^"&,}\s]+)""",
            r"\1\2[REDACTED]",
            line,
        )
        destination.write(line)
        destination.flush()


def main():
    os.environ["PYTHONIOENCODING"] = "utf-8"
    child = subprocess.Popen(
        [sys.executable, "-u", "-m", "backend.run_devices", "--public"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    readers = [
        threading.Thread(target=capture, args=(child.stdout, sys.stdout)),
        threading.Thread(target=capture, args=(child.stderr, sys.stderr)),
    ]
    for reader in readers:
        reader.start()
    exit_code = child.wait()
    for reader in readers:
        reader.join()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
