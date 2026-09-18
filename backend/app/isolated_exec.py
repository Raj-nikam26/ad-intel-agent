"""
isolated_exec.py
----------------
Runs a model-generated table query in a separate process.

safe_executor.py validates the expression and evaluates it with no
builtins, but that happens inside the API process: an expression that
slipped past the checks would run with the server's memory, files and
network. Here the evaluation happens in a child process that

  - has network access disabled,
  - is limited to a few seconds of CPU (Linux),
  - is killed if it does not answer within the wall-clock timeout,
  - can return only a size-capped DataFrame, Series or scalar.

The expression is still validated in the parent first, so obviously bad
input is rejected without starting a process at all.

Process start method: "forkserver" on Linux, so children come from a
clean single-threaded server rather than being forked from the threaded
web process (forking a threaded process can deadlock on a held lock).
"spawn" on Windows, where fork does not exist.
"""

from __future__ import annotations

import multiprocessing as mp
import sys

import pandas as pd

from app.safe_executor import ExecutionError, UnsafeExpressionError, validate_expression

TIMEOUT_SECONDS = 10
CPU_SECONDS = 5
MAX_RESULT_ROWS = 500

_ctx = None


def _context():
    global _ctx
    if _ctx is None:
        if sys.platform == "win32":
            _ctx = mp.get_context("spawn")
        else:
            _ctx = mp.get_context("forkserver")
            _ctx.set_forkserver_preload(["pandas", "app.safe_executor"])
    return _ctx


def _child(expr: str, df: pd.DataFrame, conn) -> None:
    try:
        if sys.platform != "win32":
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))

        import socket

        def _no_network(*_a, **_k):
            raise OSError("Network access is disabled for table queries.")

        socket.socket = _no_network
        socket.create_connection = _no_network
        socket.getaddrinfo = _no_network

        from app.safe_executor import run_expression

        result = run_expression(expr, df)
        if isinstance(result, (pd.DataFrame, pd.Series)):
            result = result.head(MAX_RESULT_ROWS)
        conn.send(("ok", result))
    except (UnsafeExpressionError, ExecutionError) as e:
        conn.send(("error", str(e)))
    except Exception as e:  # noqa: BLE001 - reported to the caller, never raised in the child
        conn.send(("error", f"{type(e).__name__}: {e}"))
    finally:
        conn.close()


def run_isolated(expr: str, df: pd.DataFrame, timeout: float = TIMEOUT_SECONDS):
    """Evaluates `expr` against `df` in a child process and returns the result."""
    validate_expression(expr)

    ctx = _context()
    receiver, sender = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(expr, df, sender), daemon=True)
    proc.start()
    sender.close()
    try:
        if not receiver.poll(timeout):
            raise ExecutionError(f"The query took longer than {timeout:g} seconds and was stopped.")
        try:
            status, payload = receiver.recv()
        except EOFError as e:
            raise ExecutionError("The query was stopped (time or resource limit reached).") from e
        if status != "ok":
            raise ExecutionError(payload)
        return payload
    finally:
        receiver.close()
        proc.join(0.5)
        if proc.is_alive():
            proc.kill()
            proc.join(1)
