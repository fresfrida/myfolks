"""MyFolks pre-flight hello backend. Throwaway."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
async def hello():
    from hermes_constants import get_hermes_home

    return {"status": "ok", "home": get_hermes_home().name}
