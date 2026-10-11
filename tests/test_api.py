
import pytest
from app.models.user import User

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
