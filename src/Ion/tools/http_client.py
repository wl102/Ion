"""Shared HTTP client for cookie persistence across tools.

The global ``_httpx_client`` is instantiated once and reused by both
``http_request`` and ``python_exec``.  This ensures cookies set during
``http_request`` calls are visible to scripts executed via ``python_exec``
and vice-versa.
"""

import httpx

_httpx_client = httpx.AsyncClient(verify=False)
