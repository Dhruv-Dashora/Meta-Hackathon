"""Browser-session endpoint: binds cached analyses to one session.

The session id is an opaque random value the client keeps in session
storage and returns in the ``x-session-id`` header. Cached analyses are
retrievable only with the owning session id plus the analysis reference.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.analysis_store import session_store

router = APIRouter(prefix="/session", tags=["session"])


class SessionResponse(BaseModel):
    session_id: str


@router.post("", response_model=SessionResponse)
def create_session() -> SessionResponse:
    return SessionResponse(session_id=session_store.create())
