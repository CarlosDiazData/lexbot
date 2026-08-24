"""GET /health — API liveness with store + db status (API-3).

Always HTTP 200 while the API is up. vector_count comes from the Chroma
store (or -1 when the store is unreachable); db reports the PostgreSQL
reachability via Database.ping() — a failed db check never fails the request.
"""

from fastapi import APIRouter, Depends, Request

from ..app import get_db, get_store
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, store=Depends(get_store), db=Depends(get_db)):
    try:
        vector_count = store.count()
    except Exception:
        vector_count = -1

    try:
        db_status = "ok" if db.ping() else "error"
    except Exception:
        db_status = "error"

    return HealthResponse(status="ok", vector_count=vector_count, db=db_status)