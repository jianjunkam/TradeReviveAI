"""The diagnosis chat, proxied through this server.

The page used to embed Flowise's own widget, which renders an iframe of the hosted chat page —
and that page sends `X-Frame-Options: SAMEORIGIN`, so the embed fell back to a floating bubble
and the page around it was decoration.

So the page now owns its chat: a list, a composer, and this endpoint. The browser never talks
to Flowise directly, which means no CORS negotiation, no chatflow id in the page requesting
anything, and one place to enforce a length limit and a per-session rate.

The assistant still answers from the chatflow the user configured; this route does not add
opinions of its own.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.permissions import public

router = APIRouter(prefix="/api/diagnosis", include_in_schema=False)

REQUEST_TIMEOUT = 75.0
MAX_MESSAGE = 2000
#: Simple guard so one browser tab cannot hammer somebody else's chatflow.
RATE_LIMIT = 20
RATE_WINDOW = 60.0

_lock = threading.Lock()
_recent: dict[str, list[float]] = {}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE)
    session_id: str | None = Field(default=None, max_length=64)


def _check_rate(key: str) -> None:
    now = time.time()
    with _lock:
        hits = [t for t in _recent.get(key, []) if now - t < RATE_WINDOW]
        if len(hits) >= RATE_LIMIT:
            _recent[key] = hits
            raise HTTPException(
                status_code=429,
                detail=f"Too many messages. Wait a moment — {RATE_LIMIT} per minute is the limit.",
            )
        hits.append(now)
        _recent[key] = hits


@router.post("/chat")
@public
def chat(request: Request, payload: ChatRequest) -> dict:
    settings = request.app.state.settings
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Write a question first.")

    if settings.demo_closed:
        raise HTTPException(status_code=404, detail="Not found.")

    if not settings.flowise_chatflow_id or not settings.flowise_host:
        raise HTTPException(
            status_code=503,
            detail="No assistant is configured. Set FLOWISE_HOST and FLOWISE_CHATFLOW_ID in the "
                   "server's .env.",
        )

    _check_rate(request.client.host if request.client else "anonymous")

    body: dict = {"question": message}
    if payload.session_id:
        # The chatflow keeps context per session; the browser owns the id so a reload does not
        # lose the conversation it is showing.
        body["overrideConfig"] = {"sessionId": payload.session_id}

    url = f"https://{settings.flowise_host}/api/v1/prediction/{settings.flowise_chatflow_id}"
    request_obj = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request_obj, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"The assistant refused the request (HTTP {exc.code}).",
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"The assistant could not be reached: {exc}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="The assistant answered with something that was not JSON.",
        ) from exc

    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="The assistant returned an empty answer.")

    return {"text": text, "session_id": payload.session_id}
