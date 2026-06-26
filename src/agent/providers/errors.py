"""Provider-layer errors.

Replaces ``pi_py_sdk.PiError`` for the native provider layer. A ``ProviderError`` is raised
for setup/usage problems (missing key, unknown provider) that should abort before streaming;
*transient* failures during a stream are instead surfaced as a terminal ``error``
:class:`StreamEvent` so the existing :class:`~agent.retry.RetryPolicy` can retry them.
"""

from __future__ import annotations

__all__ = ["ProviderError"]


class ProviderError(Exception):
    """A provider could not be set up or used (e.g. unknown provider, missing credentials)."""
