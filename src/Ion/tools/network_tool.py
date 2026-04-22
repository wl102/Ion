import requests
import logging

from .registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


def _http_request(url: str, method: str = "GET", body: str = "") -> str:
    """Make an HTTP request."""
    try:
        if method.upper() == "POST":
            resp = requests.post(url, data=body, timeout=30)
        else:
            resp = requests.get(url, timeout=30)
        content = resp.text
        return tool_result(
            success=200 <= resp.status_code < 300,
            output=f"Status: {resp.status_code}\n\n{content}",
        )
    except requests.exceptions.RequestException as e:
        return tool_error(f"Request failed: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error in http_request: {e}", exc_info=True)
        return tool_error(f"Unexpected error: {e}")


HTTP_REQUEST_SCHEMA = {
    "type": "function",
    "function": {
        "name": "http_request",
        "description": "Make an HTTP request.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL"},
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET or POST)",
                },
                "body": {"type": "string", "description": "Request body for POST"},
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
    description="Make an HTTP request.",
    emoji="🌐",
    max_result_size_chars=10000,
)
