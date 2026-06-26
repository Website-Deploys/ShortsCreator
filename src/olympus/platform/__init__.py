"""Cross-cutting platform concerns: configuration, logging, errors, monitoring.

These modules are dependency-light and are safe to import from anywhere in the
codebase. They must never import from ``olympus.api``, ``olympus.apps``, or any
adapter package to avoid circular dependencies.
"""
