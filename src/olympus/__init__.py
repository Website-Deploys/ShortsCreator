"""Project Olympus.

An AI Creative Studio that turns one long-form video into multiple premium,
creator-ready Shorts.

This package contains the backend implementation. Its internal layout mirrors
the responsibility areas defined in the MVP Engineering Architecture:

- ``olympus.platform`` - cross-cutting concerns (config, logging, errors,
  monitoring).
- ``olympus.domain``   - technology-free core: entities and the abstract
  contracts (ports) every adapter must implement.
- ``olympus.data``     - data access adapters: the database connection layer
  and storage backends.
- ``olympus.services`` - shared service logic (the queue infrastructure).
- ``olympus.ai``       - the AI service adapters behind the domain contracts.
- ``olympus.rendering``- the rendering adapters behind the domain contract.
- ``olympus.api``      - the HTTP API layer (FastAPI app, routes, schemas).
- ``olympus.apps``     - deployable entry points (the API server, the worker).
- ``olympus.utils``    - small, dependency-free helpers.

No business logic lives in this foundation release; the modules provide the
wiring, abstractions, and infrastructure on which the rest of Olympus is built.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
