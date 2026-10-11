from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.dependencies import MarketSourceDep, PriceCacheDep
from app.services import llm

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


@router.post("/api/chat")
async def post_chat(body: ChatRequest, source: MarketSourceDep, cache: PriceCacheDep) -> dict:
    return await llm.handle_chat(body.message, source, cache)


@router.get("/api/chat")
async def get_chat() -> dict:
    return {"messages": await llm.list_chat()}
