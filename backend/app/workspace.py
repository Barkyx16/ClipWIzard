"""Anonymous, private workspaces.

Every browser gets a random workspace key in an HttpOnly cookie. Videos,
highlights, clips and media files are only visible to requests carrying the
key of the workspace that owns them. Only a hash of the key is stored in the
database, so a leaked database can't be used to open anyone's workspace.

Users can copy their key to another device (see /api/workspace) to open the
same workspace there.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

COOKIE = "cw_ws"
MAX_AGE = 60 * 60 * 24 * 400  # ~13 months, the browser maximum
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
# Public endpoints that never need a workspace (and so never mint one).
WORKSPACE_FREE = {"/api/health"}


def new_key() -> str:
    return secrets.token_urlsafe(32)


def workspace_id(key: str) -> str:
    return hashlib.sha256(key.encode("ascii")).hexdigest()[:32]


def valid_key(key: str | None) -> bool:
    return bool(key) and bool(KEY_RE.match(key))  # type: ignore[arg-type]


def set_cookie(request: Request, response: Response, key: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, key, max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=secure, path="/")


class WorkspaceMiddleware(BaseHTTPMiddleware):
    """Ensures every API/media request has a workspace, minting one if needed.

    The cookie is also set on the HTML page load itself, so a first-time
    visitor already has it before the app fires several API calls at once
    (otherwise each parallel call would mint a different workspace and the
    last response would win).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        page_load = request.method == "GET" and "text/html" in request.headers.get("accept", "")
        scoped = path.startswith("/api/") or path.startswith("/media/")
        public = path in WORKSPACE_FREE or path.startswith(("/api/share/", "/s/", "/share/"))
        if public or not (scoped or page_load):
            return await call_next(request)
        key = request.cookies.get(COOKIE)
        minted = None
        if not valid_key(key):
            key = minted = new_key()
        request.state.workspace_key = key
        request.state.workspace = workspace_id(key)  # type: ignore[arg-type]
        response = await call_next(request)
        if minted and not getattr(request.state, "workspace_switched", False):
            set_cookie(request, response, minted)
        return response


def current_workspace(request: Request) -> str:
    ws = getattr(request.state, "workspace", None)
    if not ws:  # middleware not installed / path not covered
        raise HTTPException(500, "Workspace middleware is not active")
    return ws


def same_workspace(owner: str | None, ws: str) -> bool:
    return owner is not None and hmac.compare_digest(owner, ws)
