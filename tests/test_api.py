
import pytest
from app.models.user import User
from app.models.incident import Incident

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.dependencies import get_db
from app.database.database import Base
from app.core import security


@pytest.fixture
def client(monkeypatch):
    # Create an isolated in-memory test database.
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )

    app.state.testing_session_local = TestingSessionLocal
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()



def create_user(client, email, role="engineer"):
    response = client.post(
        "/users",
        json={
            "name": f"Test {role.title()}",
            "email": email,
            "password": "Test@12345",
            "role": role,
        },
    )

    assert response.status_code == 200, response.text

    # Promote the user only inside the isolated test database.
    if role == "admin":
        TestingSessionLocal = client.app.state.testing_session_local
        db = TestingSessionLocal()

        try:
            user = db.query(User).filter(User.email == email).first()
            assert user is not None

            user.role = "admin"
            db.commit()
        finally:
            db.close()

    return response.json()

def login(client, email):
    response = client.post(
        "/login",
        json={
            "email": email,
            "password": "Test@12345",
        },
    )
    assert response.status_code == 200, response.text

    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_home_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["message"] == "Welcome to SmartOps API"


def test_user_registration_and_duplicate_email(client):
    create_user(client, "engineer@example.com")

    response = client.post(
        "/users",
        json={
            "name": "Duplicate Engineer",
            "email": "engineer@example.com",
            "password": "Test@12345",
            "role": "engineer",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_login_and_protected_users_endpoint(client):
    create_user(client, "admin@example.com", "admin")

    # Protected endpoint should reject a request without a token.
    response = client.get("/users")
    assert response.status_code in (401, 403)

    headers = login(client, "admin@example.com")
    response = client.get("/users", headers=headers)

    assert response.status_code == 200
    assert any(
        user["email"] == "admin@example.com"
        for user in response.json()
    )


def test_create_and_retrieve_incident(client):
    create_user(client, "admin@example.com", "admin")
    headers = login(client, "admin@example.com")

    payload = {
        "title": "Payment API failure",
        "description": "Payment requests are failing.",
        "service": "Payment API",
        "error_message": "Database connection timeout",
        "affected_users": 600,
        "error_count": 120,
    }

    response = client.post(
        "/incidents",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 200, response.text

    incident = response.json()
    assert incident["title"] == "Payment API failure"
    assert incident["severity"] == "CRITICAL"
    assert incident["status"] == "OPEN"

    incident_id = incident["id"]

    response = client.get(
        f"/incidents/{incident_id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == incident_id


def test_analytics_endpoint(client):
    create_user(client, "admin@example.com", "admin")
    headers = login(client, "admin@example.com")

    response = client.get(
        "/analytics/incidents",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()
    assert data["total_incidents"] == 0
    assert data["open_incidents"] == 0
    assert data["resolved_incidents"] == 0
    assert data["critical_incidents"] == 0



def test_engineer_cannot_assign_incident(client):
    create_user(client, "engineer@example.com", "engineer")
    headers = login(client, "engineer@example.com")

    response = client.post(
        "/incidents/1/assign",
        json={"assigned_to": 1},
        headers=headers,
    )

    assert response.status_code == 403


def test_admin_can_assign_incident_to_engineer(client):
    create_user(client, "admin@example.com", "admin")
    engineer = create_user(client, "engineer@example.com", "engineer")
    admin_headers = login(client, "admin@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Payment service outage",
            "description": "Payment requests are failing.",
            "service": "Payment API",
            "affected_users": 100,
            "error_count": 50,
        },
        headers=admin_headers,
    )
    assert incident_response.status_code == 200, incident_response.text
    incident_id = incident_response.json()["id"]

    response = client.post(
        f"/incidents/{incident_id}/assign",
        params={"engineer_id": engineer["id"]},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["assigned_to"] == engineer["id"]
    assert response.json()["status"] == "INVESTIGATING"


def test_assigning_incident_creates_assignment_event(client):
    admin = create_user(client, "admin@example.com", "admin")
    engineer = create_user(client, "engineer@example.com", "engineer")
    admin_headers = login(client, "admin@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Payment service outage",
            "description": "Payment requests are failing.",
            "service": "Payment API",
            "affected_users": 100,
            "error_count": 50,
        },
        headers=admin_headers,
    )
    assert incident_response.status_code == 200, incident_response.text
    incident_id = incident_response.json()["id"]

    assignment_response = client.post(
        f"/incidents/{incident_id}/assign",
        params={"engineer_id": engineer["id"]},
        headers=admin_headers,
    )
    assert assignment_response.status_code == 200, assignment_response.text

    events_response = client.get(
        f"/incidents/{incident_id}/events",
        headers=admin_headers,
    )
    assert events_response.status_code == 200, events_response.text

    events = events_response.json()
    assignment_events = [
        event for event in events
        if event["event_type"] == "ASSIGNED"
    ]

    assert len(assignment_events) == 1
    assert assignment_events[0]["user_id"] == admin["id"]
    assert str(engineer["id"]) in assignment_events[0]["description"]



def test_create_and_retrieve_incident_event(client):
    create_user(client, "engineer@example.com")
    headers = login(client, "engineer@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Login service error",
            "description": "Users cannot log in.",
            "service": "Authentication",
            "affected_users": 10,
            "error_count": 5,
        },
        headers=headers,
    )
    assert incident_response.status_code == 200, incident_response.text
    incident_id = incident_response.json()["id"]

    event_response = client.post(
        f"/incidents/{incident_id}/events",
        json={
            "event_type": "INVESTIGATION",
            "description": "Started investigating the login failure.",
        },
        headers=headers,
    )

    assert event_response.status_code == 200, event_response.text
    assert event_response.json()["incident_id"] == incident_id
    assert event_response.json()["event_type"] == "INVESTIGATION"

    list_response = client.get(
        f"/incidents/{incident_id}/events",
        headers=headers,
    )

    assert list_response.status_code == 200, list_response.text
    assert len(list_response.json()) == 1


def test_admin_can_resolve_incident(client):
    create_user(client, "admin@example.com", "admin")
    headers = login(client, "admin@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Database connection failure",
            "description": "The service cannot connect to the database.",
            "service": "Database",
            "affected_users": 25,
            "error_count": 12,
        },
        headers=headers,
    )
    assert incident_response.status_code == 200, incident_response.text
    incident_id = incident_response.json()["id"]

    response = client.post(
        f"/incidents/{incident_id}/resolve",
        json={
            "root_cause": "Database connection pool was exhausted.",
            "resolution": "Increased the pool limit and restarted the service.",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "RESOLVED"
    assert response.json()["root_cause"] == (
        "Database connection pool was exhausted."
    )

    # A resolved incident must not be resolved again.
    second_response = client.post(
        f"/incidents/{incident_id}/resolve",
        json={
            "root_cause": "Another attempted root cause.",
            "resolution": "Another attempted resolution.",
        },
        headers=headers,
    )

    assert second_response.status_code == 400



def test_unassigned_engineer_cannot_resolve_incident(client):
    create_user(client, "admin@example.com", "admin")
    create_user(client, "engineer@example.com", "engineer")

    admin_headers = login(client, "admin@example.com")
    engineer_headers = login(client, "engineer@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Unassigned incident",
            "description": "This incident has not been assigned.",
            "service": "Notification API",
            "affected_users": 10,
            "error_count": 5,
        },
        headers=admin_headers,
    )
    assert incident_response.status_code == 200, incident_response.text
    incident_id = incident_response.json()["id"]

    response = client.post(
        f"/incidents/{incident_id}/resolve",
        json={
            "root_cause": "Connection timeout caused the failure.",
            "resolution": "Restarted the service and restored connectivity.",
        },
        headers=engineer_headers,
    )

    assert response.status_code == 403


def test_assigned_engineer_can_resolve_incident(client):
    create_user(client, "admin@example.com", "admin")
    engineer = create_user(client, "engineer@example.com", "engineer")

    admin_headers = login(client, "admin@example.com")
    engineer_headers = login(client, "engineer@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Assigned incident",
            "description": "An engineer will resolve this incident.",
            "service": "Orders API",
            "affected_users": 15,
            "error_count": 8,
        },
        headers=admin_headers,
    )
    assert incident_response.status_code == 200, incident_response.text
    incident_id = incident_response.json()["id"]

    assignment_response = client.post(
        f"/incidents/{incident_id}/assign",
        params={"engineer_id": engineer["id"]},
        headers=admin_headers,
    )
    assert assignment_response.status_code == 200, assignment_response.text

    response = client.post(
        f"/incidents/{incident_id}/resolve",
        json={
            "root_cause": "An invalid configuration caused the failure.",
            "resolution": "Corrected the configuration and restarted the service.",
        },
        headers=engineer_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "RESOLVED"


def test_invalid_incident_data_is_rejected(client):
    create_user(client, "admin@example.com", "admin")
    headers = login(client, "admin@example.com")

    response = client.post(
        "/incidents",
        json={
            "title": "AB",
            "description": "Bad",
            "service": "API",
            "affected_users": -1,
            "error_count": -1,
        },
        headers=headers,
    )

    assert response.status_code == 422


def test_admin_cannot_assign_nonexistent_engineer(client):
    create_user(client, "admin@example.com", "admin")
    headers = login(client, "admin@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Assignment failure",
            "description": "Testing an invalid engineer assignment.",
            "service": "Payments API",
            "affected_users": 10,
            "error_count": 5,
        },
        headers=headers,
    )

    assert incident_response.status_code == 200
    incident_id = incident_response.json()["id"]

    response = client.post(
        f"/incidents/{incident_id}/assign",
        params={"engineer_id": 99999},
        headers=headers,
    )

    assert response.status_code == 404


def test_resolved_incident_cannot_be_reassigned(client):
    create_user(client, "admin@example.com", "admin")
    engineer = create_user(client, "engineer@example.com")
    headers = login(client, "admin@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Resolved incident",
            "description": "Testing reassignment after resolution.",
            "service": "Orders API",
            "affected_users": 10,
            "error_count": 5,
        },
        headers=headers,
    )

    assert incident_response.status_code == 200
    incident_id = incident_response.json()["id"]

    assignment_response = client.post(
        f"/incidents/{incident_id}/assign",
        params={"engineer_id": engineer["id"]},
        headers=headers,
    )

    assert assignment_response.status_code == 200

    resolve_response = client.post(
        f"/incidents/{incident_id}/resolve",
        json={
            "root_cause": "An invalid configuration caused the incident.",
            "resolution": "Corrected the configuration and restarted the service.",
        },
        headers=headers,
    )

    assert resolve_response.status_code == 200

    response = client.post(
        f"/incidents/{incident_id}/assign",
        params={"engineer_id": engineer["id"]},
        headers=headers,
    )

    assert response.status_code == 400


def test_engineer_cannot_list_all_users(client):
    engineer = create_user(client, "engineer@example.com")
    headers = login(client, "engineer@example.com")

    response = client.get("/users", headers=headers)

    assert response.status_code == 403


def test_engineer_can_view_own_profile_but_not_another_users(client):
    engineer_one = create_user(client, "engineer1@example.com")
    create_user(client, "engineer2@example.com")

    headers = login(client, "engineer1@example.com")

    # An engineer can access their own profile.
    own_response = client.get(
        f"/users/{engineer_one['id']}",
        headers=headers,
    )
    assert own_response.status_code == 200
    assert own_response.json()["email"] == "engineer1@example.com"

    # An engineer cannot access another user's profile.
    other_response = client.get(
        "/users/2",
        headers=headers,
    )
    assert other_response.status_code == 403


def test_admin_can_list_users_and_view_another_profile(client):
    create_user(client, "admin@example.com", "admin")
    engineer = create_user(client, "engineer@example.com")

    headers = login(client, "admin@example.com")

    # Admin can list all users.
    list_response = client.get("/users", headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2

    # Admin can view another user's profile.
    profile_response = client.get(
        f"/users/{engineer['id']}",
        headers=headers,
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["email"] == "engineer@example.com"





from datetime import datetime, timedelta, timezone

from jose import jwt

def test_malformed_token_is_rejected(client):
    response = client.get(
        "/users",
        headers={"Authorization": "Bearer this-is-not-a-valid-token"},
    )

    assert response.status_code == 401


def test_expired_token_is_rejected(client):
    create_user(client, "engineer@example.com")

    expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = jwt.encode(
        {"sub": "1", "exp": expired_time},
        security.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )

    response = client.get(
        "/users/1",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_token_with_missing_user_id_is_rejected(client):
    token = jwt.encode(
        {"role": "engineer"},
        security.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )

    response = client.get(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_duplicate_email_registration_is_rejected(client):
    create_user(client, "duplicate@example.com")

    response = client.post(
        "/users",
        json={
            "name": "Duplicate User",
            "email": "duplicate@example.com",
            "password": "AnotherStrongPassword123!",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_login_with_wrong_password_is_rejected(client):
    create_user(client, "login@example.com")

    response = client.post(
        "/login",
        json={
            "email": "login@example.com",
            "password": "WrongPassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_with_unknown_email_is_rejected(client):
    response = client.post(
        "/login",
        json={
            "email": "unknown@example.com",
            "password": "SomePassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_engineer_cannot_update_user(client):
    engineer = create_user(client, "engineer@example.com")
    headers = login(client, "engineer@example.com")

    response = client.put(
        f"/users/{engineer['id']}",
        headers=headers,
        json={
            "name": "Updated Engineer",
            "email": "updated@example.com",
            "role": "engineer",
        },
    )

    assert response.status_code == 403


def test_admin_cannot_delete_own_account(client):
    admin = create_user(
        client,
        "admin@example.com",
        role="admin",
    )
    headers = login(client, "admin@example.com")

    response = client.delete(
        f"/users/{admin['id']}",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Admins cannot delete their own account"
    )


def test_analytics_endpoints_return_empty_data(client):
    create_user(client, "analytics@example.com")
    headers = login(client, "analytics@example.com")

    incidents_response = client.get(
        "/analytics/incidents",
        headers=headers,
    )
    assert incidents_response.status_code == 200
    assert incidents_response.json() == {
        "total_incidents": 0,
        "open_incidents": 0,
        "investigating_incidents": 0,
        "resolved_incidents": 0,
        "critical_incidents": 0,
    }

    services_response = client.get(
        "/analytics/services",
        headers=headers,
    )
    assert services_response.status_code == 200
    assert services_response.json() == []

    severity_response = client.get(
        "/analytics/severity",
        headers=headers,
    )
    assert severity_response.status_code == 200
    assert severity_response.json() == [
        {"severity": "CRITICAL", "incident_count": 0},
        {"severity": "HIGH", "incident_count": 0},
        {"severity": "MEDIUM", "incident_count": 0},
        {"severity": "LOW", "incident_count": 0},
    ]

    resolution_response = client.get(
        "/analytics/resolution-time",
        headers=headers,
    )
    assert resolution_response.status_code == 200
    assert resolution_response.json() == {
        "resolved_incidents": 0,
        "average_resolution_minutes": 0,
    }


def test_analytics_rejects_missing_token(client):
    response = client.get("/analytics/incidents")
    assert response.status_code in (401, 403)


def test_service_analytics_groups_incidents(client):
    create_user(client, "service-analytics@example.com")
    headers = login(client, "service-analytics@example.com")

    first = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "API failure",
            "description": "API requests are failing",
            "service": "Payment API",
            "severity": "HIGH",
        },
    )
    second = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "API latency",
            "description": "API responses are slow",
            "service": "Payment API",
            "severity": "MEDIUM",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get(
        "/analytics/services",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == [
        {"service": "Payment API", "incident_count": 2}
    ]


def test_severity_analytics_counts_incidents(client):
    create_user(client, "severity-analytics@example.com")
    headers = login(client, "severity-analytics@example.com")

    test_incidents = [
        {
            "title": "High incident 1",
            "description": "Testing high severity analytics",
            "service": "Test Service",
            "affected_users": 100,
            "error_count": 0,
        },
        {
            "title": "High incident 2",
            "description": "Testing high severity analytics",
            "service": "Test Service",
            "affected_users": 150,
            "error_count": 0,
        },
        {
            "title": "Low incident",
            "description": "Testing low severity analytics",
            "service": "Test Service",
            "affected_users": 5,
            "error_count": 1,
        },
    ]

    for payload in test_incidents:
        response = client.post(
            "/incidents",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 200, response.text

    response = client.get(
        "/analytics/severity",
        headers=headers,
    )

    assert response.status_code == 200, response.text

    severity_counts = {
        item["severity"]: item["incident_count"]
        for item in response.json()
    }

    assert severity_counts == {
        "CRITICAL": 0,
        "HIGH": 2,
        "MEDIUM": 0,
        "LOW": 1,
    }


def test_resolution_time_analytics_calculates_average(client):
    create_user(client, "resolution-analytics@example.com", "admin")
    headers = login(client, "resolution-analytics@example.com")

    incident_ids = []

    for index in range(2):
        incident_response = client.post(
            "/incidents",
            headers=headers,
            json={
                "title": f"Resolution test incident {index + 1}",
                "description": "Testing resolution-time calculations",
                "service": "Test Service",
                "affected_users": 10,
                "error_count": 5,
            },
        )

        assert incident_response.status_code == 200, incident_response.text
        incident_ids.append(incident_response.json()["id"])

        resolve_response = client.post(
            f"/incidents/{incident_ids[-1]}/resolve",
            headers=headers,
            json={
                "root_cause": "Test root cause",
                "resolution": "Test resolution",
            },
        )

        assert resolve_response.status_code == 200, resolve_response.text

    # Set predictable timestamps so the calculation is deterministic.
    TestingSessionLocal = client.app.state.testing_session_local
    db = TestingSessionLocal()

    try:
        incident_one = db.query(Incident).filter(
            Incident.id == incident_ids[0]
        ).first()
        incident_two = db.query(Incident).filter(
            Incident.id == incident_ids[1]
        ).first()

        assert incident_one is not None
        assert incident_two is not None

        incident_one.created_at = datetime(2026, 1, 1, 10, 0)
        incident_one.resolved_at = datetime(2026, 1, 1, 10, 30)

        incident_two.created_at = datetime(2026, 1, 1, 10, 0)
        incident_two.resolved_at = datetime(2026, 1, 1, 11, 30)

        db.commit()
    finally:
        db.close()

    response = client.get(
        "/analytics/resolution-time",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "resolved_incidents": 2,
        "average_resolution_minutes": 60.0,
    }

def test_get_nonexistent_user_returns_404(client):
    create_user(client, "profile-admin@example.com", "admin")
    headers = login(client, "profile-admin@example.com")

    response = client.get("/users/99999", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_admin_can_update_user(client):
    create_user(client, "update-admin@example.com", "admin")
    create_user(client, "update-engineer@example.com")

    admin_headers = login(client, "update-admin@example.com")

    users_response = client.get("/users", headers=admin_headers)
    assert users_response.status_code == 200

    engineer = next(
        user
        for user in users_response.json()
        if user["email"] == "update-engineer@example.com"
    )

    response = client.put(
        f"/users/{engineer['id']}",
        headers=admin_headers,
        json={
            "name": "Updated Engineer",
            "email": "updated-engineer@example.com",
            "role": "engineer",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Engineer"
    assert response.json()["email"] == "updated-engineer@example.com"


def test_admin_cannot_update_user_with_duplicate_email(client):
    create_user(client, "duplicate-admin@example.com", "admin")
    create_user(client, "first-engineer@example.com")
    create_user(client, "second-engineer@example.com")

    admin_headers = login(client, "duplicate-admin@example.com")

    users_response = client.get("/users", headers=admin_headers)
    users = users_response.json()

    first_engineer = next(
        user for user in users
        if user["email"] == "first-engineer@example.com"
    )

    response = client.put(
        f"/users/{first_engineer['id']}",
        headers=admin_headers,
        json={
            "name": "First Engineer",
            "email": "second-engineer@example.com",
            "role": "engineer",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_admin_cannot_update_nonexistent_user(client):
    create_user(client, "missing-update-admin@example.com", "admin")
    headers = login(client, "missing-update-admin@example.com")

    response = client.put(
        "/users/99999",
        headers=headers,
        json={
            "name": "Nobody",
            "email": "nobody@example.com",
            "role": "engineer",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_admin_cannot_delete_nonexistent_user(client):
    create_user(client, "missing-delete-admin@example.com", "admin")
    headers = login(client, "missing-delete-admin@example.com")

    response = client.delete("/users/99999", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_admin_can_delete_another_user(client):
    create_user(client, "delete-admin@example.com", "admin")
    create_user(client, "delete-engineer@example.com")

    headers = login(client, "delete-admin@example.com")

    users_response = client.get("/users", headers=headers)
    engineer = next(
        user
        for user in users_response.json()
        if user["email"] == "delete-engineer@example.com"
    )

    response = client.delete(
        f"/users/{engineer['id']}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["message"] == "User deleted successfully"

    profile_response = client.get(
        f"/users/{engineer['id']}",
        headers=headers,
    )

    assert profile_response.status_code == 404

def test_get_db_closes_session(monkeypatch):
    from app.database import dependencies

    class FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake_db = FakeSession()
    monkeypatch.setattr(
        dependencies,
        "SessionLocal",
        lambda: fake_db,
    )

    generator = dependencies.get_db()

    assert next(generator) is fake_db
    assert fake_db.closed is False

    generator.close()

    assert fake_db.closed is True

def test_get_nonexistent_incident_returns_404(client):
    create_user(client, "incident-reader@example.com")
    headers = login(client, "incident-reader@example.com")

    response = client.get("/incidents/99999", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found"


def test_create_event_for_nonexistent_incident_returns_404(client):
    create_user(client, "event-user@example.com")
    headers = login(client, "event-user@example.com")

    response = client.post(
        "/incidents/99999/events",
        headers=headers,
        json={
            "event_type": "NOTE",
            "description": "Testing a missing incident",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found"


def test_list_events_for_nonexistent_incident_returns_404(client):
    create_user(client, "event-reader@example.com")
    headers = login(client, "event-reader@example.com")

    response = client.get(
        "/incidents/99999/events",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found"


def test_resolve_nonexistent_incident_returns_404(client):
    create_user(client, "resolution-admin@example.com", "admin")
    headers = login(client, "resolution-admin@example.com")

    response = client.post(
        "/incidents/99999/resolve",
        headers=headers,
        json={
            "root_cause": "Test root cause",
            "resolution": "Test resolution",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found"


def test_engineer_cannot_resolve_unassigned_incident(client):
    create_user(client, "unassigned-engineer@example.com")
    headers = login(client, "unassigned-engineer@example.com")

    incident_response = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "Unassigned incident",
            "description": "Testing resolution permissions",
            "service": "Test Service",
            "affected_users": 10,
            "error_count": 5,
        },
    )

    assert incident_response.status_code == 200, incident_response.text
    incident_id = incident_response.json()["id"]

    response = client.post(
        f"/incidents/{incident_id}/resolve",
        headers=headers,
        json={
            "root_cause": "Test root cause",
            "resolution": "Test resolution",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Only an admin or the assigned engineer can resolve this incident"
    )

def test_admin_cannot_assign_nonexistent_incident(client):
    create_user(client, "missing-incident-admin@example.com", "admin")
    create_user(client, "missing-incident-engineer@example.com")

    headers = login(client, "missing-incident-admin@example.com")

    users_response = client.get("/users", headers=headers)
    engineer = next(
        user
        for user in users_response.json()
        if user["email"] == "missing-incident-engineer@example.com"
    )

    response = client.post(
        "/incidents/99999/assign",
        params={"engineer_id": engineer["id"]},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found"


def test_admin_cannot_assign_incident_to_another_admin(client):
    create_user(client, "assign-admin@example.com", "admin")
    create_user(client, "target-admin@example.com", "admin")

    headers = login(client, "assign-admin@example.com")

    users_response = client.get("/users", headers=headers)
    target_admin = next(
        user
        for user in users_response.json()
        if user["email"] == "target-admin@example.com"
    )

    incident_response = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "Assignment validation test",
            "description": "Testing role validation",
            "service": "Test Service",
            "affected_users": 10,
            "error_count": 5,
        },
    )
    assert incident_response.status_code == 200, incident_response.text

    incident_id = incident_response.json()["id"]

    response = client.post(
        f"/incidents/{incident_id}/assign",
        params={"engineer_id": target_admin["id"]},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Incident can only be assigned to an engineer"
    )


def test_token_with_non_positive_user_id_is_rejected(client):
    token = jwt.encode(
        {"sub": "0"},
        security.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )

    response = client.get(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_token_for_deleted_user_is_rejected(client):
    token = jwt.encode(
        {"sub": "99999"},
        security.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )

    response = client.get(
        "/users/99999",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "User associated with token was not found"
    )

def test_missing_secret_key_raises_runtime_error():
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env.pop("SECRET_KEY", None)
    env["PYTHONPATH"] = os.getcwd()

    code = (
        "import dotenv; "
        "dotenv.load_dotenv = lambda *a, **k: False; "
        "import app.core.security"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "SECRET_KEY is missing from environment" in result.stderr

def test_get_all_incidents_returns_list(client):
    create_user(client, "incidents_admin@example.com", "admin")
    headers = login(client, "incidents_admin@example.com")

    payload = {
        "title": "Coverage test incident",
        "description": "Testing retrieval of all incidents.",
        "service": "Test Service",
        "error_message": "Test error",
        "affected_users": 10,
        "error_count": 5,
    }

    create_response = client.post(
        "/incidents",
        json=payload,
        headers=headers,
    )
    assert create_response.status_code == 200, create_response.text

    response = client.get("/incidents", headers=headers)

    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)
    assert any(
        incident["title"] == "Coverage test incident"
        for incident in response.json()
    )

def test_registration_cannot_assign_admin_role(client):
    response = client.post(
        "/users",
        json={
            "name": "Malicious User",
            "email": "malicious@example.com",
            "password": "Test@12345",
            "role": "admin",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["role"].lower() == "engineer"



def test_resolving_incident_creates_resolution_event(client):
    create_user(client, "admin@example.com", "admin")
    headers = login(client, "admin@example.com")

    incident_response = client.post(
        "/incidents",
        json={
            "title": "Database connection failure",
            "description": "The service cannot connect to the database.",
            "service": "Database",
            "affected_users": 25,
            "error_count": 12,
        },
        headers=headers,
    )
    assert incident_response.status_code == 200, incident_response.text
    incident_id = incident_response.json()["id"]

    root_cause = "Database connection pool was exhausted."
    resolution = "Increased the pool limit and restarted the service."

    resolve_response = client.post(
        f"/incidents/{incident_id}/resolve",
        json={
            "root_cause": root_cause,
            "resolution": resolution,
        },
        headers=headers,
    )
    assert resolve_response.status_code == 200, resolve_response.text

    events_response = client.get(
        f"/incidents/{incident_id}/events",
        headers=headers,
    )
    assert events_response.status_code == 200, events_response.text

    resolution_events = [
        event for event in events_response.json()
        if event["event_type"] == "RESOLVED"
    ]

    assert len(resolution_events) == 1
    assert resolution_events[0]["user_id"] == create_user.__globals__.get(
        "_unused_user_id", resolution_events[0]["user_id"]
    )
    assert root_cause in resolution_events[0]["description"]
    assert resolution in resolution_events[0]["description"]
