"""Compatibility entrypoint for the command-line interface."""

from agenttrust.interfaces.cli import build_parser, init_project, main

__all__ = ["build_parser", "init_project", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
