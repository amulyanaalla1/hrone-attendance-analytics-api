# Employee Attendance & Analytics API

FastAPI + PyMongo service for employee records, attendance punch-in/out, regularization with audit history, and monthly/department analytics.

## Run

1. Use Python 3.11+.
2. Install dependencies: `python -m pip install -r requirements.txt`
3. Create a local `.env` file (do not commit it):

   ```text
   MONGO_URI=<your MongoDB connection string>
   MONGO_DB=attendance_db
   ```

4. Start from this folder: `python -m uvicorn app.main:app --port 8000`
5. Open `http://127.0.0.1:8000/docs`.

Indexes are created idempotently on startup. `GET /health` checks MongoDB connectivity. API instants use epoch milliseconds; MongoDB stores UTC BSON datetimes. Attendance calendar dates and shift times use IST.

## Endpoints

- `GET /health`
- `POST /employees`, `GET /employees`
- `POST /attendance/punch-in`, `POST /attendance/punch-out`, `GET /attendance`
- `PATCH /attendance/{emp_code}/{date}`
- `GET /analytics/employees/{emp_code}/monthly`
- `GET /analytics/departments/summary`
- `GET /analytics/leaderboard/late`
- `GET /analytics/departments/{department}/trend`
- `GET /admin/explain/{endpoint}`

## Before submission

Run manual tests against the target MongoDB version, especially the aggregation and explain endpoints, concurrent writes, overnight shifts, and rounding boundaries. Hidden-dataset performance cannot be guaranteed from the small sample alone. Do not commit `.env`, credentials, `.venv`, or database dumps.
