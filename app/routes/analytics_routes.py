
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.incident import Incident
from app.core.security import verify_token

router = APIRouter()


@router.get("/analytics/incidents")
def incident_analytics(
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    total_incidents = db.query(Incident).count()

    open_incidents = (
        db.query(Incident)
        .filter(Incident.status == "OPEN")
        .count()
    )

    investigating_incidents = (
        db.query(Incident)
        .filter(Incident.status == "INVESTIGATING")
        .count()
    )

    resolved_incidents = (
        db.query(Incident)
        .filter(Incident.status == "RESOLVED")
        .count()
    )

    critical_incidents = (
        db.query(Incident)
        .filter(Incident.severity == "CRITICAL")
        .count()
    )

    return {
        "total_incidents": total_incidents,
        "open_incidents": open_incidents,
        "investigating_incidents": investigating_incidents,
        "resolved_incidents": resolved_incidents,
        "critical_incidents": critical_incidents,
    }


@router.get("/analytics/services")
def service_analytics(
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    incidents = db.query(Incident).all()
    service_counts = {}

    for incident in incidents:
        service = incident.service
        service_counts[service] = service_counts.get(service, 0) + 1

    return [
        {
            "service": service,
            "incident_count": count,
        }
        for service, count in service_counts.items()
    ]


@router.get("/analytics/severity")
def severity_analytics(
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    result = []

    for severity in severities:
        count = (
            db.query(Incident)
            .filter(Incident.severity == severity)
            .count()
        )

        result.append({
            "severity": severity,
            "incident_count": count,
        })

    return result


@router.get("/analytics/resolution-time")
def resolution_time_analytics(
    db: Session = Depends(get_db),
    current_user: int = Depends(verify_token),
):
    resolved_incidents = (
        db.query(Incident)
        .filter(
            Incident.status == "RESOLVED",
            Incident.resolved_at.isnot(None),
        )
        .all()
    )

    if not resolved_incidents:
        return {
            "resolved_incidents": 0,
            "average_resolution_minutes": 0,
        }

    total_minutes = 0

    for incident in resolved_incidents:
        resolution_time = (
            incident.resolved_at - incident.created_at
        )
        total_minutes += resolution_time.total_seconds() / 60

    average_minutes = total_minutes / len(resolved_incidents)

    return {
        "resolved_incidents": len(resolved_incidents),
        "average_resolution_minutes": round(average_minutes, 2),
    }
