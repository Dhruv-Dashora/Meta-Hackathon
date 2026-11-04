"""SQLAlchemy models (scaffold — no migrations yet).

Tables: observations, evidence_items, findings, reviews.
Every finding links to evidence via finding_evidence join table.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    location_id: Mapped[str] = mapped_column(String, default="")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String, default="")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"))
    modality: Mapped[str] = mapped_column(String, default="image")
    uri_or_hash: Mapped[str] = mapped_column(String, default="")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    confidence_value: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_calibrated: Mapped[bool] = mapped_column(default=False)
    uncertainty_notes: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String, default="pending")
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_items.id"), primary_key=True)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    decision: Mapped[str] = mapped_column(String, default="pending")
    reviewer: Mapped[str] = mapped_column(String, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
