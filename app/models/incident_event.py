from datetime import datetime,timezone
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.database.database import Base


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id = Column(Integer, primary_key=True, index=True)

    incident_id = Column(
        Integer,
        nullable=False
    )

    user_id = Column(
        Integer,
        nullable=False
    )

    event_type = Column(
        String,
        nullable=False
    )

    description = Column(
        Text,
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )