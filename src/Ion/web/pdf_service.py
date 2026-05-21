"""Lightweight Playwright PDF service.

A global singleton that keeps one Chromium browser alive for the lifetime
of the FastAPI application.  Each PDF render creates a fresh BrowserContext
+ Page so that cookies / localStorage never leak between reports.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class PdfRenderer:
    """Async PDF renderer backed by a single headless Chromium browser."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Launch Chromium once; safe to call multiple times."""
        async with self._lock:
            if self._browser is not None:
                return
            self._playwright = await async_playwright().start()
            # --no-sandbox is required inside Docker containers;
            # disable-gpu avoids GPU-related crashes in headless environments.
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )

    async def close(self) -> None:
        """Gracefully close browser and playwright."""
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    async def render(
        self,
        html: str,
        output_path: str | Path | None = None,
        *,
        width: str = "210mm",
        height: str = "297mm",
        margin: dict[str, str] | None = None,
        header_template: str = "",
        footer_template: str = "",
    ) -> bytes | Path:
        """Render *html* to PDF bytes (or write to *output_path*).

        Args:
            html: Complete HTML document string.
            output_path: If provided, the PDF is written to disk and the
                path is returned; otherwise raw bytes are returned.
            width, height: Page size (default A4).
            margin: Dict of top/right/bottom/left margins, e.g.
                ``{"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"}``.
            header_template: HTML template for the print header.
            footer_template: HTML template for the print footer.
        """
        if self._browser is None:
            raise RuntimeError("PdfRenderer.start() must be called before render()")

        _margin = margin or {
            "top": "15mm",
            "bottom": "15mm",
            "left": "15mm",
            "right": "15mm",
        }

        context: BrowserContext | None = None
        page: Page | None = None
        try:
            context = await self._browser.new_context()
            page = await context.new_page()
            await page.set_content(html, wait_until="networkidle")
            pdf_kwargs: dict[str, Any] = {
                "width": width,
                "height": height,
                "margin": _margin,
                "print_background": True,
                "display_header_footer": bool(header_template or footer_template),
            }
            if header_template:
                pdf_kwargs["header_template"] = header_template
            if footer_template:
                pdf_kwargs["footer_template"] = footer_template
            pdf_bytes = await page.pdf(**pdf_kwargs)
        finally:
            if page:
                await page.close()
            if context:
                await context.close()

        if output_path:
            path = Path(output_path)
            path.write_bytes(pdf_bytes)
            return path
        return pdf_bytes


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_renderer: PdfRenderer | None = None


def get_pdf_renderer() -> PdfRenderer:
    """Return the global PdfRenderer singleton."""
    global _renderer
    if _renderer is None:
        _renderer = PdfRenderer()
    return _renderer
