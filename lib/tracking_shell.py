#!/usr/bin/env python3
"""Self-contained tracking shell — vendored from the trackingshell library.

Acts as the GNU Make SHELL.  Every recipe command is routed through this
script so that:
  1. stdout/stderr are tee'd to logs/<date>/<target>.log
  2. BEGIN/END JSON records are appended to logs/<date>/timing_env.log
  3. the original command's exit code is preserved

No external dependencies.  Replaces the old wunderlist/trackingshell plugin
system with ~80 lines of stdlib.
"""

import datetime
import json
import os
import random
import shlex
import subprocess
import sys


def today_str():
    return datetime.date.today().isoformat()


def is_make_level():
    """True when make invokes us at the top level (MAKELEVEL == 0)."""
    return os.environ.get("MAKELEVEL", "0") == "0"


def write_timing_record(log_dir, record):
    path = os.path.join(log_dir, "timing_env.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
            f.flush()
    except IOError:
        pass


def main():
    # We can't use argparse normally because make may pass `--target` with
    # an empty value when $@ doesn't expand (macOS make 3.81).  On gmake 4.4+
    # $@ expands correctly.  We handle both by scanning argv manually.
    argv = sys.argv[1:]
    target = None
    date = None
    shell_command = None
    rest = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--target":
            # Next arg is the target — unless it starts with -- (make 3.81
            # left $@ empty, so the next token is --date or -c).
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                target = argv[i + 1]
                i += 2
            else:
                target = "no-target"
                i += 1
        elif arg == "--date":
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                date = argv[i + 1]
                i += 2
            else:
                i += 1
        elif arg == "-c":
            # Everything after -c is the shell command.
            shell_command = " ".join(argv[i + 1:])
            break
        else:
            rest.append(arg)
            i += 1

    date = date or today_str()
    target = target or "no-target"

    # Make invokes: $(SHELL) $(.SHELLFLAGS) "recipe"
    # i.e. tracking_shell.py --target $@ --date $(TODAY) -c "recipe command"
    # The -c flag carries the actual command; if not present, use the rest.
    if shell_command is not None:
        command = shell_command
    else:
        command = " ".join(rest) if rest else ""

    log_dir = f"logs/{date}"

    # No real command (e.g. directory targets) — nothing to track.
    if not command.strip():
        sys.exit(0)

    # Ensure the logs directory exists before we try to write to it.
    os.makedirs(log_dir, exist_ok=True)

    unique_nr = random.randint(0, 1_000_000)

    # Write BEGIN record to timing_env.log.
    begin_record = {
        "command": command.replace("\n", ""),
        "target": target,
        "unique_nr": unique_nr,
        "has_make_level": is_make_level(),
        "started_at": datetime.datetime.now().isoformat(),
        "tag": "BEGIN",
    }
    write_timing_record(log_dir, begin_record)

    # Per-target log file.
    safe_name = target.replace("/", "_")
    target_log = os.path.join(log_dir, f"{safe_name}.log")

    attempt = os.environ.get("ATTEMPT_COUNT", "0")
    header = (
        f"\n[tracking_shell {datetime.datetime.now()}] "
        f"Working on target {target} attempt {attempt} command {command!r}\n\n"
    )
    try:
        with open(target_log, "a", encoding="utf-8") as f:
            f.write(header)
    except IOError:
        pass

    # Execute the command, teeing output to the target log.
    # Use PIPESTATUS to preserve the command's exit code through the pipe.
    wrapped = (
        f"set -o pipefail; ({command}) 2>&1 | tee -a {shlex.quote(target_log)}; "
        f"exit ${{PIPESTATUS[0]}}"
    )
    result = subprocess.run(wrapped, shell=True, executable="/bin/bash")

    # Write END record to timing_env.log.
    end_record = {
        "command": command.replace("\n", ""),
        "target": target,
        "unique_nr": unique_nr,
        "has_make_level": is_make_level(),
        "started_at": begin_record["started_at"],
        "finished_at": datetime.datetime.now().isoformat(),
        "exit_code": result.returncode,
        "tag": "END",
    }
    write_timing_record(log_dir, end_record)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
