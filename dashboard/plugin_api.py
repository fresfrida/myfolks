"""Backend for the MyFolks Desktop page. Thin routes over desktop_service.

Hermes puts these routes behind its own login check. Contact text travels only in request and
response bodies, never in URLs, so it cannot end up in access logs.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


def _service():
    """Load the plugin's own code as a package, wherever Hermes installed it."""
    root = Path(__file__).resolve().parent.parent
    name = "myfolks_page_" + hashlib.sha256(str(root).encode()).hexdigest()[:12]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return importlib.import_module(f"{name}.desktop_service")


def _call(action: Callable[[object], dict]) -> dict:
    service = _service()
    try:
        return action(service)
    except service.VaultError as error:
        return service.state_for(error)
    except Exception as error:
        logger.error("MyFolks page request failed: %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="error") from None


class FindBody(BaseModel):
    query: str = ""


class LineBody(BaseModel):
    text: str


class HiddenBody(BaseModel):
    hidden: bool


class UndoBody(BaseModel):
    change_id: int


class ReviewBody(BaseModel):
    action: str
    card_id: Optional[int] = None


@router.get("/status")
def status():
    return _call(lambda s: s.status())


@router.post("/setup")
def setup():
    return _call(lambda s: s.setup())


@router.post("/find")
def find(body: FindBody):
    return _call(lambda s: s.find(body.query))


@router.get("/cards/{card_id}")
def card(card_id: int):
    return _call(lambda s: s.card_detail(card_id))


@router.post("/cards/{card_id}/lines")
def save_line(card_id: int, body: LineBody):
    return _call(lambda s: s.save_line(card_id, body.text))


@router.post("/cards/{card_id}/delete")
def delete_person(card_id: int):
    return _call(lambda s: s.delete_person(card_id))


@router.post("/lines/{line_id}/delete")
def delete_line(line_id: int):
    return _call(lambda s: s.delete_line(line_id))


@router.post("/lines/{line_id}/edit")
def edit_line(line_id: int, body: LineBody):
    return _call(lambda s: s.edit_line(line_id, body.text))


@router.post("/undo")
def undo(body: UndoBody):
    return _call(lambda s: s.undo(body.change_id))


@router.post("/lines/{line_id}/hidden")
def set_hidden(line_id: int, body: HiddenBody):
    return _call(lambda s: s.set_hidden(line_id, body.hidden))


@router.get("/review")
def review():
    return _call(lambda s: s.review_list())


@router.post("/review/{item_id}")
def resolve_review(item_id: int, body: ReviewBody):
    return _call(lambda s: s.resolve_review(item_id, body.action, body.card_id))
