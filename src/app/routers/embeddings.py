from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..utils.embeddings import compute_embedding

router = APIRouter()


class EmbeddingRequest(BaseModel):
    text: str


@router.post("/embeddings")
async def create_embedding(req: EmbeddingRequest):
    try:
        vec = await compute_embedding(req.text)
        return {"embedding": vec}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
