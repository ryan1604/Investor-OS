from fastapi import APIRouter, Request

from app.dependencies import get_ib_client

router = APIRouter()


@router.get("/ib/status")
def ib_status(request: Request):
    return get_ib_client(request).get_status()
