import logging
from typing import Any

import httpx

from .registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


async def _http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: str = "",
    timeout: int = 30,
) -> str:
    """Make an HTTP request."""
    try:
        req_headers = headers or {}
        req_params = params or {}

        method = method.upper()

        if method not in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
            return tool_error("Invalid http method.")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.request(
                method,
                url,
                content=body,
                headers=req_headers,
                params=req_params,
                timeout=timeout,
            )

        content = resp.text
        response_headers = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())

        return tool_result(
            success=200 <= resp.status_code < 300,
            output=f"Status: {resp.status_code}\n\nResponse Headers:\n{response_headers}\n\n{content}",
        )
    except httpx.TimeoutException as e:
        return tool_error(f"Request timeout: {e}")
    except httpx.RequestError as e:
        return tool_error(f"Request failed: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error in http_request: {e}", exc_info=True)
        return tool_error(f"Unexpected error: {e}")


HTTP_REQUEST_SCHEMA = {
    "type": "function",
    "function": {
        "name": "http_request",
        "description": "Make an HTTP request with custom headers and parameters.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL"},
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)",
                    "default": "GET",
                },
                "headers": {
                    "type": "object",
                    "description": "Custom HTTP headers",
                    "additionalProperties": {"type": "string"},
                },
                "params": {
                    "type": "object",
                    "description": "URL query parameters",
                    "additionalProperties": {"type": "string"},
                },
                "body": {
                    "type": "string",
                    "description": "Request body for POST/PUT/PATCH",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds",
                    "default": 30,
                },
            },
            "required": ["url"],
        },
    },
}

registry.register(
    name="http_request",
    toolset="builtin",
    schema=HTTP_REQUEST_SCHEMA,
    handler=_http_request,
    is_async=True,
    description="Make an HTTP request with custom headers and parameters.",
    emoji="🌐",
    max_result_size_chars=10000,
)
