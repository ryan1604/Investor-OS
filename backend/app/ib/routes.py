from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/ib/status")
def ib_status(request: Request):
    return request.app.state.ib_client.get_status()
