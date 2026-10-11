from datetime import datetime,timezone

from sqlalchemy import Column, Integer, String, Text, DateTime

from app.database.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String, nullable=False)

    description = Column(Text, nullable=False)

    service = Column(String, nullable=False)

    error_message = Column(Text, nullable=True)

    affected_users = Column(Integer, default=0)

    error_count = Column(Integer, default=0)

    severity = Column(String, nullable=False, default="LOW")

    status = Column(String, nullable=False, default="OPEN")

    created_by = Column(Integer, nullable=False)

    assigned_to = Column(Integer, nullable=True)

    root_cause = Column(Text, nullable=True)

    resolution = Column(Text, nullable=True)

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    resolved_at = Column(
        DateTime,
        nullable=True
    )