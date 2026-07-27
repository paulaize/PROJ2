"""Restricted ANTsPyx execution backend for the reviewed registration workflows."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from lys_bbb.atlas_registration import AntsExecutables, CommandExecution


ANTSPYX_VERSION = "0.6.3"
ANTSPYX_ENGINE = "ANTsPyx"
ANTSPYX_BACKEND = "antspyx"
ANTS_CLI_BACKEND = "cli"
ANTS_DISABLED_BACKEND = "disabled"

_COMPILED_ENTRY_POINTS = frozenset(
    {
        "antsApplyTransforms",
        "antsRegistration",
        "CreateJacobianDeterminantImage",
        "N4BiasFieldCorrection",
    }
)


def antspyx_executables() -> AntsExecutables:
    """Return virtual command identities after verifying the pinned Python package."""

    ants = _import_pinned_antspyx()
    virtual_bin = Path("antspyx-compiled")
    return AntsExecutables(
        registration=virtual_bin / "antsRegistration",
        apply_transforms=virtual_bin / "antsApplyTransforms",
        n4_bias_field_correction=virtual_bin / "N4BiasFieldCorrection",
        create_jacobian=virtual_bin / "CreateJacobianDeterminantImage",
        version=str(ants.__version__),
        engine=ANTSPYX_ENGINE,
    )


def antspyx_command_runner(
    args: tuple[str, ...],
    cwd: Path,
) -> CommandExecution:
    """Execute one allow-listed ANTs operation through ANTsPyx's compiled library."""

    started = time.monotonic()
    if not args:
        return _failed_execution(args, started, "No ANTs operation was provided")
    if not cwd.is_dir():
        return _failed_execution(
            args,
            started,
            f"ANTsPyx working directory does not exist: {cwd}",
        )
    operation = Path(args[0]).name
    if operation not in _COMPILED_ENTRY_POINTS:
        return _failed_execution(
            args,
            started,
            f"ANTsPyx operation is not allow-listed: {operation}",
        )
    try:
        return_code = execute_compiled_ants(operation, args[1:])
    except Exception as exc:
        return _failed_execution(
            args,
            started,
            f"{type(exc).__name__}: {exc}",
        )
    return CommandExecution(
        args=args,
        return_code=return_code,
        stdout=(
            f"{operation} executed through the pinned ANTsPyx "
            f"{ANTSPYX_VERSION} compiled library.\n"
        ),
        stderr="",
        runtime_seconds=time.monotonic() - started,
    )


def antspyx_subprocess_command_runner(
    args: tuple[str, ...],
    cwd: Path,
) -> CommandExecution:
    """Run one compiled ANTsPyx operation in an isolated, log-capturable process."""

    started = time.monotonic()
    if not args:
        return _failed_execution(args, started, "No ANTs operation was provided")
    if not cwd.is_dir():
        return _failed_execution(
            args,
            started,
            f"ANTsPyx working directory does not exist: {cwd}",
        )
    operation = Path(args[0]).name
    if operation not in _COMPILED_ENTRY_POINTS:
        return _failed_execution(
            args,
            started,
            f"ANTsPyx operation is not allow-listed: {operation}",
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lys_bbb.antspyx_worker",
            operation,
            *args[1:],
        ],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    return CommandExecution(
        args=args,
        return_code=int(result.returncode),
        stdout=result.stdout,
        stderr=result.stderr,
        runtime_seconds=time.monotonic() - started,
    )


def execute_compiled_ants(operation: str, arguments: tuple[str, ...]) -> int:
    """Dispatch an allow-listed operation to the pinned ANTsPyx native library."""

    if operation not in _COMPILED_ENTRY_POINTS:
        raise ValueError(f"ANTsPyx operation is not allow-listed: {operation}")
    _import_pinned_antspyx()
    from ants.internal import get_lib_fn, process_arguments

    processed_args = process_arguments(list(arguments))
    return int(get_lib_fn(operation)(processed_args))


def backend_components(
    backend: str,
) -> tuple[Callable[..., CommandExecution] | None, AntsExecutables | None]:
    """Resolve optional runner overrides for an application registration backend."""

    normalised = backend.strip().casefold()
    if normalised in {ANTS_CLI_BACKEND, ANTS_DISABLED_BACKEND}:
        return None, None
    if normalised == ANTSPYX_BACKEND:
        return antspyx_subprocess_command_runner, antspyx_executables()
    raise ValueError(f"Unsupported ANTs registration backend: {backend!r}")


def _import_pinned_antspyx():
    try:
        import ants
    except ImportError as exc:
        raise RuntimeError(
            f"ANTsPyx {ANTSPYX_VERSION} is required for native Windows registration"
        ) from exc
    observed = str(getattr(ants, "__version__", "unknown"))
    if observed != ANTSPYX_VERSION:
        raise RuntimeError(
            f"Expected ANTsPyx {ANTSPYX_VERSION}; observed {observed}"
        )
    return ants


def _failed_execution(
    args: tuple[str, ...],
    started: float,
    message: str,
) -> CommandExecution:
    return CommandExecution(
        args=args,
        return_code=1,
        stdout="",
        stderr=message,
        runtime_seconds=time.monotonic() - started,
    )
