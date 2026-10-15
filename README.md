# Employee Attendance & Analytics API

A RESTful backend application developed using **Python, FastAPI, and MongoDB** to manage employee records, track attendance, process attendance regularization, and generate workforce analytics.

The application provides APIs for employee management, attendance punch-in and punch-out, attendance record updates with audit history, monthly attendance summaries, department-level analytics, and late-arrival rankings.

## Table of Contents

- [Features](#features)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
- [Environment Configuration](#environment-configuration)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Data and Time Handling](#data-and-time-handling)
- [Database and Indexing](#database-and-indexing)
- [Project Structure](#project-structure)
- [Testing and Validation](#testing-and-validation)
- [Security Considerations](#security-considerations)
- [Additional Documentation](#additional-documentation)
- [Limitations](#limitations)

## Features

- **Employee Management:** Create employee records and retrieve employee information.
- **Attendance Tracking:** Record employee punch-in and punch-out events.
- **Attendance Regularization:** Update attendance records through a dedicated API endpoint while maintaining audit history.
- **Monthly Attendance Analytics:** Retrieve monthly attendance information for individual employees.
- **Department Analytics:** Generate department-level attendance summaries and trends.
- **Late-Arrival Leaderboard:** Retrieve employee rankings based on late-arrival metrics.
- **Database Query Analysis:** Inspect query execution plans through the administrative explain endpoint.
- **Database Indexing:** Create database indexes idempotently during application startup.
- **Health Monitoring:** Check application health and MongoDB connectivity.
- **API Documentation:** Explore endpoints, request parameters, and response schemas through interactive Swagger documentation.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming language |
| FastAPI | REST API framework |
| PyMongo | MongoDB database integration |
| MongoDB | Database and persistent storage |
| Uvicorn | ASGI application server |
| OpenAPI | API specification and documentation |

## Prerequisites

Before running the application, ensure the following are available:

- Python 3.11 or later
- MongoDB instance or MongoDB Atlas cluster
- pip package installer
- Git

## Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/amulyanaalla1/hrone-attendance-analytics-api.git
cd hrone-attendance-analytics-api
```

### 2. Create a Virtual Environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Linux or macOS:**

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

Install the required Python packages:

```bash
python -m pip install -r requirements.txt
```

## Environment Configuration

Create a `.env` file in the project root directory and configure the MongoDB connection:

```env
MONGO_URI=<your MongoDB connection string>
MONGO_DB=attendance_db
```

Replace the placeholder with your actual MongoDB connection string.

Ensure that the database is accessible from your development environment and that the required connection permissions are configured.

**Security notice:** Never commit `.env` files, database credentials, API keys, or other sensitive information to version control.

## Running the Application

Start the FastAPI application from the project root:

```bash
python -m uvicorn app.main:app --port 8000
```

Once the application starts, the following endpoints are available:

| Resource | URL |
|---|---|
| API Base URL | http://127.0.0.1:8000 |
| Swagger UI | http://127.0.0.1:8000/docs |
| OpenAPI JSON | http://127.0.0.1:8000/openapi.json |
| Health Check | http://127.0.0.1:8000/health |

The application requires a reachable MongoDB instance for database-dependent operations.

## API Endpoints

### 1. Health Monitoring

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Check application health and MongoDB connectivity |

### 2. Employee Management

| Method | Endpoint | Description |
|---|---|---|
| POST | `/employees` | Create an employee record |
| GET | `/employees` | Retrieve employee records |

### 3. Attendance Management

| Method | Endpoint | Description |
|---|---|---|
| POST | `/attendance/punch-in` | Record an employee's punch-in |
| POST | `/attendance/punch-out` | Record an employee's punch-out |
| GET | `/attendance` | Retrieve attendance records |
| PATCH | `/attendance/{emp_code}/{date}` | Update an attendance record through regularization |

### 4. Employee Attendance Analytics

| Method | Endpoint | Description |
|---|---|---|
| GET | `/analytics/employees/{emp_code}/monthly` | Retrieve monthly attendance analytics for an employee |

### 5. Department Analytics

| Method | Endpoint | Description |
|---|---|---|
| GET | `/analytics/departments/summary` | Retrieve department-level attendance summaries |
| GET | `/analytics/departments/{department}/trend` | Retrieve attendance trends for a department |

### 6. Late-Arrival Analytics

| Method | Endpoint | Description |
|---|---|---|
| GET | `/analytics/leaderboard/late` | Retrieve the late-arrival leaderboard |

### 7. Administrative Operations

| Method | Endpoint | Description |
|---|---|---|
| GET | `/admin/explain/{endpoint}` | Inspect query execution plans for supported endpoints |

For detailed request schemas, query parameters, response formats, and available operations, open the Swagger UI at `/docs` while the application is running.

## Data and Time Handling

The application follows these timestamp and time-zone conventions:

- **API timestamps:** Epoch milliseconds.
- **Database timestamps:** UTC BSON datetime values in MongoDB.
- **Attendance calendar dates:** Interpreted using Indian Standard Time (IST).
- **Shift times:** Handled according to IST-based attendance rules.

Consistent timestamp handling is important for attendance calculations, daily boundaries, overnight shifts, and monthly analytics.

## Database and Indexing

The application uses MongoDB for persistent storage and PyMongo for database interactions.

Key database considerations include:

- Indexes are created idempotently during application startup.
- The health endpoint checks MongoDB connectivity.
- The administrative explain endpoint supports inspection of query execution plans.
- Aggregation pipelines should be evaluated against representative datasets.
- Index selection and query performance should be validated against the target MongoDB version.

## Project Structure

```text
hrone-attendance-analytics-api/
│
├── app/
│   ├── __init__.py
│   └── main.py
│
├── sample_data/
│   ├── attendance_logs.json
│   └── employees.json
│
├── .gitignore
├── DATA_MODEL.md
├── DECISIONS.md
├── README.md
├── REVIEW.md
├── openapi.yaml
├── requirements.txt
└── sample_seed.py
```

## Testing and Validation

The following areas should be validated before submission or deployment:

- Employee creation and retrieval.
- Attendance punch-in and punch-out workflows.
- Duplicate or invalid attendance operations.
- Attendance regularization and audit-history preservation.
- Monthly employee attendance calculations.
- Department-level summaries and trends.
- Late-arrival leaderboard calculations.
- MongoDB aggregation behavior.
- Database index usage and query execution plans.
- Concurrent attendance writes.
- Overnight shifts and calendar-date boundaries.
- Rounding boundaries in attendance calculations.
- Invalid requests and database error handling.

Testing should be performed against the intended MongoDB version and representative datasets.

Results from a small sample dataset alone do not establish correctness or performance for larger workloads.

## Security Considerations

- Store database connection strings and credentials in environment variables.
- Exclude `.env`, virtual environments, Python cache files, and database dumps from version control.
- Validate incoming request data.
- Handle database exceptions appropriately.
- Restrict administrative endpoints according to the deployment environment.
- Review authentication and authorization requirements before exposing the API publicly.
- Avoid logging sensitive employee information or database credentials.

## Additional Documentation

The repository includes supporting technical documentation:

- **[DATA_MODEL.md](DATA_MODEL.md):** Documents the data model and associated design considerations.
- **[DECISIONS.md](DECISIONS.md):** Describes technical and architectural decisions.
- **[REVIEW.md](REVIEW.md):** Contains review notes and identified considerations.
- **[openapi.yaml](openapi.yaml):** Provides the OpenAPI specification.

## Limitations

Application behavior and performance depend on the implementation, database configuration, indexing strategy, and workload.

Aggregation correctness, concurrency handling, overnight shifts, rounding rules, and query execution plans should be validated before production use.

Performance on hidden datasets or larger workloads cannot be guaranteed solely from sample-data testing.

## License

No license has been specified for this repository. Add an appropriate license if distribution or reuse beyond the assignment requirements is intended.
