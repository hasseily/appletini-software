"""Bounded runs of the machines (every run that writes files has a bound,
and a run fails rather than grows).

`run` is subprocess.run with three limits on the child and on everything
it starts:

  - a wall-time `timeout`: on expiry the whole process group is killed
    (the child starts a session of its own), not only the direct child,
    and subprocess.TimeoutExpired is raised;
  - `max_bytes`, the largest file any of them may write (RLIMIT_FSIZE): a
    write past it kills the writer with SIGXFSZ;
  - a CPU-time limit (RLIMIT_CPU) a little above the timeout, so a child
    whose parent was killed from outside still stops on its own.

After a normal end the group is killed too, so nothing the child left
behind keeps running. Standard library only; POSIX (macOS, Linux).
"""

import math
import os
import signal
import subprocess
from typing import Optional, Sequence

try:
    import resource
except ImportError:                 # not POSIX: no rlimits
    resource = None

# The tools' default bounds: generous for any real run of the game, far
# below what fills a disk.
TOOL_TIMEOUT = 3600.0
TOOL_MAX_BYTES = 1 << 30
# The slack of the CPU-time limit over the wall timeout, in seconds.
CPU_SLACK = 30


def _lower(which, value: int, hard_too: bool) -> None:
    """Lower the limit `which` to `value`; never raise it (a bounded run
    inside another keeps the tighter bound of the outer one)."""
    soft, hard = resource.getrlimit(which)
    if hard != resource.RLIM_INFINITY:
        value = min(value, hard)
    if soft != resource.RLIM_INFINITY:
        value = min(value, soft)
    resource.setrlimit(which, (value, value if hard_too else hard))


def _limits(max_bytes: Optional[int], cpu_seconds: Optional[int]):
    def apply():
        if resource is None:
            return
        if max_bytes is not None:
            _lower(resource.RLIMIT_FSIZE, max_bytes, True)
        if cpu_seconds is not None:
            _lower(resource.RLIMIT_CPU, cpu_seconds, False)
    return apply


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def explain(returncode: int, max_bytes: Optional[int]) -> str:
    """Why a bounded run ended with `returncode`, when a bound ended it."""
    if returncode == -getattr(signal, 'SIGXFSZ', 25):
        return 'a file passed the limit of %s bytes (SIGXFSZ)' % max_bytes
    if returncode == -getattr(signal, 'SIGXCPU', 24):
        return 'the CPU-time limit (SIGXCPU)'
    return ''


def run(command: Sequence, timeout: float,
        max_bytes: Optional[int] = TOOL_MAX_BYTES, check: bool = False,
        input=None, stdout=None, stderr=None, **kwargs
        ) -> subprocess.CompletedProcess:
    """subprocess.run(command) under the three bounds (see the module).
    The arguments are those of subprocess.run; `timeout` is required.
    When a bound ends the run, stderr (if captured as text) says which."""
    if timeout is None or timeout <= 0:
        raise ValueError('a bounded run needs a timeout')
    command = [str(c) for c in command]
    cpu = int(math.ceil(timeout)) + CPU_SLACK
    stdin = kwargs.pop('stdin', None)
    if input is not None:
        stdin = subprocess.PIPE
    process = subprocess.Popen(
        command, stdin=stdin, stdout=stdout, stderr=stderr,
        start_new_session=True, preexec_fn=_limits(max_bytes, cpu),
        **kwargs)
    try:
        out, err = process.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process.pid)
        process.communicate()
        raise subprocess.TimeoutExpired(command, timeout)
    except BaseException:
        _kill_group(process.pid)
        process.wait()
        raise
    _kill_group(process.pid)
    why = explain(process.returncode, max_bytes)
    if why and isinstance(err, str):
        err += '\n[bounded run: %s]\n' % why
    elif why and isinstance(err, bytes):
        err += ('\n[bounded run: %s]\n' % why).encode()
    elif why and isinstance(out, str) and stderr == subprocess.STDOUT:
        out += '\n[bounded run: %s]\n' % why
    result = subprocess.CompletedProcess(command, process.returncode, out,
                                         err)
    if check:
        result.check_returncode()
    return result
