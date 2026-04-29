import logging
from typing import Any

from .http_client import _httpx_client
from .registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


async def _http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: str = "",
    timeout: int = 30,
    follow_redirects: bool = True,
) -> str:
    """Make an HTTP request. Uses a shared client so cookies persist across calls."""
    try:
        req_headers = headers or {}
        req_params = params or {}

        method = method.upper()

        if method not in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
            return tool_error("Invalid http method.")

        resp = await _httpx_client.request(
            method,
            url,
            content=body,
            headers=req_headers,
            params=req_params,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

        content = resp.text
        response_headers = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())

        # Build redirect chain info
        redirect_info = ""
        if resp.history:
            redirect_info = "\n\nRedirect Chain:\n"
            for idx, prior in enumerate(resp.history, 1):
                loc = prior.headers.get("location", "")
                redirect_info += f"  {idx}. {prior.status_code} {prior.request.method} {prior.request.url}"
                if loc:
                    redirect_info += f" -> Location: {loc}"
                redirect_info += "\n"

        # Show current cookies in the shared jar (helpful for debugging sessions)
        cookie_info = ""
        jar = _httpx_client.cookies.jar
        if jar:
            cookies = [(c.name, c.value, c.domain, c.path) for c in jar if c.value]
            if cookies:
                cookie_info = "\n\nActive Cookies (shared jar):\n"
                for name, value, domain, path in cookies:
                    cookie_info += f"  {name}={value[:50]}... (domain={domain}, path={path})\n"

        output = (
            f"Status: {resp.status_code}\n"
            f"Final URL: {resp.url}\n\n"
            f"Response Headers:\n{response_headers}"
            f"{redirect_info}{cookie_info}\n\n"
            f"{content}"
        )

        return tool_result(
            success=200 <= resp.status_code < 300,
            output=output,
        )
    except Exception as e:
        logger.warning(f"Unexpected error in http_request: {e}", exc_info=True)
        return tool_error(f"Unexpected error: {e}")


HTTP_REQUEST_SCHEMA = {
    "type": "function",
    "function": {
        "name": "http_request",
        "description": (
            "Make an HTTP request with custom headers and parameters. "
            "Cookies are persisted across calls in a shared jar (shared with python_exec). "
            "Set follow_redirects=false to inspect 302 redirects and Location headers."
        ),
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
                "follow_redirects": {
                    "type": "boolean",
                    "description": (
                        "Whether to automatically follow HTTP redirects (3xx). "
                        "Default true. Set to false to capture 302/301 responses and Location headers."
                    ),
                    "default": True,
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
