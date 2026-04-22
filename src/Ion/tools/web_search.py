import logging
from .registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


def _web_search(query: str) -> str:
    """Search the web using DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return tool_result(success=True, output="No results found.")
        output = []
        for r in results:
            output.append(
                f"Title: {r.get('title', '')}\n"
                f"URL: {r.get('href', '')}\n"
                f"Snippet: {r.get('body', '')}\n"
            )
        return tool_result(success=True, output="\n".join(output))
    except ImportError:
        return tool_error(
            "duckduckgo-search not installed. Install with: pip install Ion[pentest]"
        )
    except Exception as e:
        logger.warning(f"Unexpected error in web_search: {e}", exc_info=True)
        return tool_error(f"Unexpected error: {e}")


WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web using DuckDuckGo.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    },
}

registry.register(
    name="web_search",
    toolset="builtin",
    schema=WEB_SEARCH_SCHEMA,
    handler=_web_search,
    description="Search the web using DuckDuckGo.",
    emoji="🔍",
    max_result_size_chars=20000,
)
