"""Shared kernel — utilities shared across all bounded contexts.

Only depends on the standard library and third-party libraries used
horizontally (pydantic, structlog, opentelemetry). Must NOT import from
``services`` or ``apps``.
"""
