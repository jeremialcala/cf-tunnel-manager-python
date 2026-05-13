"""Bounded context: tunnel orchestration.

Internal layout follows Clean / Hexagonal Architecture::

    domain/         pure business model, no I/O
    application/    use cases, sagas, ports (interfaces)
    infrastructure/ adapters that implement ports

External code may only import from :pymod:`application` (use cases) or
:pymod:`domain` (read-only types). Importing :pymod:`infrastructure`
from outside this package is a layering violation.
"""
