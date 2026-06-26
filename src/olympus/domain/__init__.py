"""The technology-free core of Olympus.

This package contains the domain *contracts* (abstract interfaces / ports) that
every adapter must implement, and - in later milestones - the domain entities,
state machine, gates, and policies. Nothing here may import an adapter
(``olympus.data``, ``olympus.ai``, ``olympus.rendering``) or any framework. The
dependency arrow always points *inward* toward this package (Clean
Architecture): adapters depend on the domain, never the reverse.
"""
