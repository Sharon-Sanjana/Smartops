from datetime import datetime,timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.user import User
from app.schemas.incident import (
    IncidentCreate,
    IncidentResponse,
    IncidentResolve,
)
from app.schemas.incident_event import (
    IncidentEventCreate,
    IncidentEventResponse,
)

from app.core.security import (
    verify_token,
    get_current_user,
    require_admin,
)



router = APIRouter()


def calculate_severity(affected_users: int, error_count: int):
    if affected_users >= 500 or error_count >= 100:
        return "CRITICAL"

    if affected_users >= 100 or error_count >= 50:
        return "HIGH"

    if affected_users >= 20 or error_count >= 10:
        return "MEDIUM"

    return "LOW"


@router.post("/incidents", response_model=IncidentResponse)
def create_incident(
    incident_data: IncidentCreate,
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    severity = calculate_severity(
        incident_data.affected_users,
        incident_data.error_count,
    )

    new_incident = Incident(
        title=incident_data.title,
        description=incident_data.description,
        service=incident_data.service,
        error_message=incident_data.error_message,
        affected_users=incident_data.affected_users,
        error_count=incident_data.error_count,
        severity=severity,
        status="OPEN",
        created_by=current_user,
    )

    db.add(new_incident)
    db.commit()
    db.refresh(new_incident)

    return new_incident


@router.get("/incidents", response_model=list[IncidentResponse])
def get_incidents(
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    return db.query(Incident).all()


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    incident = (
        db.query(Incident)
        .filter(Incident.id == incident_id)
        .first()
    )

    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return incident


@router.post("/incidents/{incident_id}/assign")
def assign_incident(
    incident_id: int,
    engineer_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    incident = (
        db.query(Incident)
        .filter(Incident.id == incident_id)
        .first()
    )

    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    if incident.status == "RESOLVED":
        raise HTTPException(
        status_code=400,
        detail="Cannot assign an already resolved incident",
    )

    engineer = (
        db.query(User)
        .filter(User.id == engineer_id)
        .first()
    )

    if not engineer:
        raise HTTPException(
            status_code=404,
            detail="Engineer not found",
        )

    if engineer.role.lower() != "engineer":
        raise HTTPException(
            status_code=400,
            detail="Incident can only be assigned to an engineer",
        )

    incident.assigned_to = engineer_id
    incident.status = "INVESTIGATING"

    assignment_event = IncidentEvent(
    incident_id=incident.id,
    user_id=current_user.id,
    event_type="ASSIGNED",
    description=f"Incident assigned to engineer ID {engineer_id}",
    )

    db.add(assignment_event)
    db.commit()
    db.refresh(incident)


    return {
        "message": "Incident assigned successfully",
        "incident_id": incident.id,
        "assigned_to": engineer_id,
        "status": incident.status,
    }


@router.post(
    "/incidents/{incident_id}/events",
    response_model=IncidentEventResponse,
)
def create_incident_event(
    incident_id: int,
    event_data: IncidentEventCreate,
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    incident = (
        db.query(Incident)
        .filter(Incident.id == incident_id)
        .first()
    )

    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    new_event = IncidentEvent(
        incident_id=incident_id,
        user_id=current_user,
        event_type=event_data.event_type,
        description=event_data.description,
    )

    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    return new_event


@router.get(
    "/incidents/{incident_id}/events",
    response_model=list[IncidentEventResponse],
)
def get_incident_events(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    incident = (
        db.query(Incident)
        .filter(Incident.id == incident_id)
        .first()
    )

    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return (
        db.query(IncidentEvent)
        .filter(IncidentEvent.incident_id == incident_id)
        .all()
    )


@router.post(
    "/incidents/{incident_id}/resolve",
    response_model=IncidentResponse,
)
def resolve_incident(
    incident_id: int,
    resolution_data: IncidentResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = (
        db.query(Incident)
        .filter(Incident.id == incident_id)
        .first()
    )

    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    if incident.status == "RESOLVED":
        raise HTTPException(
            status_code=400,
            detail="Incident is already resolved",
        )

    is_admin = current_user.role.lower() == "admin"
    is_assigned_engineer = incident.assigned_to == current_user.id

    if not is_admin and not is_assigned_engineer:
        raise HTTPException(
            status_code=403,
            detail="Only an admin or the assigned engineer can resolve this incident",
        )

    incident.root_cause = resolution_data.root_cause
    incident.resolution = resolution_data.resolution
    incident.status = "RESOLVED"
    incident.resolved_at = datetime.now(timezone.utc)

    resolution_event = IncidentEvent(
    incident_id=incident.id,
    user_id=current_user.id,
    event_type="RESOLVED",
    description=(
        f"Incident resolved. Root cause: {resolution_data.root_cause}. "
        f"Resolution: {resolution_data.resolution}"
    ),
)

    db.add(resolution_event)
    db.commit()
    db.refresh(incident)
    
    return incident
