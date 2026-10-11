# SmartOps — Incident Management API

A Python REST API for managing production incidents, assigning engineers, tracking incident events, and monitoring operational metrics.

## Overview

SmartOps is a backend application built with FastAPI that demonstrates REST API development, authentication, role-based authorization, relational database integration, input validation, and automated testing.

The application helps teams record incidents, track their status throughout the resolution lifecycle, and retrieve operational analytics.

## Features

- **User management:** Register users and retrieve user information.
- **Authentication:** Secure endpoints using JSON Web Tokens (JWT).
- **Role-based authorization:** Restrict administrative actions to authorized users.
- **Incident management:** Create, list, and retrieve incidents.
- **Severity classification:** Automatically classify incidents based on affected-user and error-count thresholds.
- **Incident assignment:** Allow administrators to assign incidents to engineers.
- **Incident event tracking:** Record and retrieve events associated with an incident.
- **Incident resolution:** Store root-cause analysis and resolution details.
- **Operational analytics:** Retrieve incident counts by status, service, and severity, along with resolution-time metrics.
- **Automated testing:** Validate API behavior using pytest and FastAPI's test client.

## Technology Stack

- Python
- FastAPI
- SQLAlchemy
- SQLite
- Pydantic
- JWT authentication
- Pytest
- HTTPX / test-client dependencies

## Project Structure

```text
SmartOps/
├── app/
│   ├── core/
│   │   └── security.py
│   ├── database/
│   │   ├── database.py
│   │   └── dependencies.py
│   ├── models/
│   │   ├── user.py
│   │   ├── incident.py
│   │   └── incident_event.py
│   ├── routes/
│   │   ├── user_routes.py
│   │   ├── incident_routes.py
│   │   └── analytics_routes.py
│   ├── schemas/
│   │   ├── user.py
│   │   ├── incident.py
│   │   └── incident_event.py
│   ├── services/
│   └── main.py
├── tests/
│   └── test_api.py
├── .gitignore
├── pytest.ini
├── requirements.txt
└── README.md
```

## Getting Started

### 1. Prerequisites

- Python 3.12 or a compatible Python version
- pip
- Git

### 2. Clone the repository

Replace the placeholder URL with the actual GitHub repository URL after publishing the project.

```bash
git clone <your-github-repository-url>
cd SmartOps
```

### 3. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 4. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 5. Configure environment variables

Create a `.env` file in the project root:

```dotenv
DATABASE_URL=sqlite:///./smartops.db
SECRET_KEY=replace-with-a-long-random-secret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Use a strong, randomly generated secret key. Never commit `.env` or real credentials to version control.

### 6. Start the API

```powershell
uvicorn app.main:app --reload
```

The API will be available at:

`http://127.0.0.1:8000`

### 7. Explore the API

Open the interactive Swagger documentation:

`http://127.0.0.1:8000/docs`

Use Swagger to inspect endpoint schemas, submit requests, and test authenticated operations.

## Incident Lifecycle

1. Create an incident.
2. Calculate its severity from the configured incident thresholds.
3. Assign the incident to an engineer.
4. Track investigation events.
5. Record the root cause and resolution.
6. Review operational analytics.

The API enforces permissions for administrative assignment and incident resolution.

## Testing

Run the automated test suite:

```powershell
python -m pytest -v
```

The project has reached **14 passing tests** during development. Run the suite again after making changes to confirm the current result.

## Future Improvements

Potential extensions include:

- PostgreSQL support for deployment environments.
- Pagination and filtering for incident listings.
- More comprehensive audit logging.
- API rate limiting and additional security hardening.
- Continuous integration with automated test execution.
- Containerized deployment.

## Author

Developed as a Python backend project to practise REST API design, authentication, database operations, authorization, incident lifecycle management, and automated testing.