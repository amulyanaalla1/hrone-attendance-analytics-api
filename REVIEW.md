# REVIEW.md — starter defects and fixes

| # | Where | Defect | How to reproduce / observe | Fix in this version |
|---|---|---|---|---|
| 1 | `health` | Always returned 200 without checking MongoDB. | Stop/restrict MongoDB and call `/health`. | Ping MongoDB; return 503 on connection failure. |
| 2 | `create_employee` | Duplicate check then insert is race-prone. | Send simultaneous POSTs with the same `emp_code`. | Unique database index; catch `DuplicateKeyError` and return 409. |
| 3 | `create_employee` | `created_at` was local-naive time, not a UTC instant. | Compare stored timestamp across machine time zones. | Store UTC-naive BSON datetime and expose epoch milliseconds. |
| 4 | `list_employees` | `skip = page * page_size` skipped the first page. | Request page 1 with page size 2. | Use `(page - 1) * page_size`. |
| 5 | `list_employees` | Total count ignored the department filter. | Filter a department and compare `total` to returned population. | Count using the same filter query. |
| 6 | `list_employees` | Results were not sorted by `emp_code`. | Insert codes out of order and list them. | Sort ascending by `emp_code`. |
| 7 | pagination | Page and page size had no bounds. | Send page 0 or page_size 101. | Validate page >= 1 and page_size 1–100. |
| 8 | time helpers | Punch timestamps were accepted as local machine time. | Run from a machine configured outside IST. | Treat epoch milliseconds as UTC instants and derive dates in IST. |
| 9 | `compute_late_minutes` | The helper did not account for overnight shifts and the grace threshold needed strict > 10 minutes. | Test exactly 09:40:00 and 09:40:01 for a 09:30 shift. | Calculate against the correct shift-start instant; strictly apply the 10-minute rule. |
| 10 | `compute_work_hours` | Python `round` uses ties-to-even, not required half-up rounding. | Test a duration exactly halfway between hundredths. | Use `Decimal` with `ROUND_HALF_UP`. |
| 11 | `compute_overtime` | Overnight shift end was placed on the wrong calendar day. | Test a 22:00–06:00 shift. | Place shift end on the next day for overnight shifts; require at least 30 minutes. |
| 12 | `punch_in` | Unknown employee caused a subscript/server error. | Punch in with an unknown `emp_code`. | Return 404 before reading employee shift fields. |
| 13 | `punch_in` | Check-then-insert could create duplicate records under concurrency. | Send parallel punch-in requests for one employee/date. | Unique `(emp_code, date)` index is the final arbiter; duplicate becomes 409. |
| 14 | `punch_in` | Status and timestamp validation were incomplete. | Send seconds, float/string timestamps, or ABSENT as punch-in status. | Strict epoch-millisecond validation and presence-status enum. |
| 15 | `attendance` list | Loaded all matching documents and sorted/sliced in Python. | Query a large attendance collection. | Database-side sort, skip, limit and count. |
| 16 | `attendance` list | Returned MongoDB `_id` as a public `id` and raw BSON datetimes. | Inspect response fields. | Never expose `_id`; serialize instants as epoch milliseconds. |
| 17 | `attendance` list | Did not validate date ranges or pagination bounds. | Set date_from after date_to or page_size > 100. | Validate ISO dates/range and bounded pagination. |
| 18 | all endpoints | Missing required punch-out, regularization, analytics and explain endpoints. | Inspect `/docs` against `openapi.yaml`. | Implemented endpoints and aggregation pipeline builders in `app/main.py`. |

Reviewed but retained: `emp_code` is the business key, not MongoDB `_id`; attendance is addressed by `(emp_code, date)`. These are contract requirements, not defects.

**Note:** Validate this implementation against the full contract and a MongoDB test database before claiming every hidden test passes. Explain-plan performance depends on the target MongoDB version, indexes, and query planner.
