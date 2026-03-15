from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, Dict, Any


class AgentCreate(BaseModel):
    model_config = ConfigDict()
    name: str
    config: Optional[Dict[str, Any]] = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    config: Optional[Dict[str, Any]] = None


class MemoryCreate(BaseModel):
    model_config = ConfigDict()
    content: str
    embedding: Optional[list[float]] = None
    metadata: Optional[Dict[str, Any]] = None


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    agent_id: int
    content: str
    embedding: Optional[list[float]] = None
    metadata: Optional[Dict[str, Any]] = Field(None, alias="meta")
    created_at: Optional[datetime] = None
