"""Process-isolated entry point for one restricted ANTsPyx native operation."""

from __future__ import annotations

import sys

from lys_bbb.antspyx_backend import execute_compiled_ants


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        print("No ANTsPyx operation was provided", file=sys.stderr)
        return 2
    operation, *operation_arguments = arguments
    try:
        return execute_compiled_ants(operation, tuple(operation_arguments))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
