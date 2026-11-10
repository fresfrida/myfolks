"""MyFolks pre-flight hello backend. Throwaway."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
async def hello():
    from hermes_constants import get_hermes_home

    return {"marker": "MYFOLKS-BACKEND-OK-3F8D", "home": get_hermes_home().name}
