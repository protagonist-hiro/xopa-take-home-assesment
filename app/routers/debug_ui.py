"""
Debug UI router – only registered when DEBUG=true in the environment.

GET /debug?key=<ADMIN_KEY>
  → Serves debug.html (injecting the current API base URL so the page
    connects back to the same host automatically).

Deliberately avoids Bearer-header auth so the page can be opened
directly in a browser via URL.
"""

import pathlib
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.config import get_settings

router = APIRouter()
settings = get_settings()

_HTML_PATH = pathlib.Path(__file__).parent.parent.parent / "debug.html"


def _require_admin(key: str) -> None:
    if not settings.ADMIN_KEY or key != settings.ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/debug", response_class=HTMLResponse, include_in_schema=False)
async def debug_ui(
    request: Request,
    key: str = Query(..., description="Admin key"),
):
    _require_admin(key)

    html = _HTML_PATH.read_text(encoding="utf-8")

    # Inject the server's own base URL and the admin key as defaults so
    # the page connects back to this server automatically.
    host = request.headers.get("host", f"localhost:{settings.SERVICE_PORT}")
    base_url = f"{request.url.scheme}://{host}"

    html = html.replace(
        'value="http://localhost:8000"',
        f'value="{base_url}"',
        1,
    )
    # Pre-fill the API key field with one of the valid keys for convenience
    from app.config import get_valid_api_keys
    first_key = get_valid_api_keys()[0] if get_valid_api_keys() else ""
    html = html.replace(
        'value="test-key-1"',
        f'value="{first_key}"',
        1,
    )

    return HTMLResponse(content=html)
