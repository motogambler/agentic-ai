from sqlalchemy import Column, Integer, String, JSON, DateTime, func, ForeignKey, Text
from sqlalchemy.orm import relationship
from .db import Base
from pgvector.sqlalchemy import Vector
from sqlalchemy import Float


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    config = Column(JSON, nullable=True)
    memories = relationship("Memory", back_populates="agent", cascade="all, delete-orphan")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    __tablename__ = "memories"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    # default embedding dim set to 1536; adjust to your model's embedding size
    embedding = Column(Vector(1536), nullable=True)
    meta = Column('metadata', JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    agent = relationship("Agent", back_populates="memories")


class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    tokens = Column(Integer, nullable=False, default=0)
    cost = Column(Float, nullable=False, default=0.0)
    adapters = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LitellmModel(Base):
    __tablename__ = "litellm_models"
    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(String, unique=True, nullable=False, index=True)
    source = Column(String, nullable=True)
    meta = Column(JSON, nullable=True)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())
