# DECISIONS.md

1. **Indexes.** A unique index on `employees.emp_code` prevents duplicate employee identities. A unique compound index on `attendance_logs (emp_code, date)` guarantees one attendance record per employee/day and makes concurrent punch-ins safe. Additional employee department/join-date and attendance date/employee/status indexes support common filters and sorted lists. I avoided adding indexes for every individual field because each index increases write and storage costs; the explain endpoint should be used to confirm plans against the actual dataset.

2. **Punch-in race.** Both requests may initially find no attendance record, but only one insert can satisfy the unique compound index. MongoDB rejects the other insert with a duplicate-key error, which the API translates to HTTP 409. The correctness guarantee comes from the database, not a pre-insert check.

3. **Ties.** The leaderboard uses MongoDB `$rank` after sorting by total late minutes. Equal totals share a rank, the next rank is skipped, and `rank <= limit` is applied after ranking, so a tie at the cutoff can return extra rows. Rows are then ordered by employee code for deterministic output.

4. **Headcount.** Department summary starts from employees who joined on or before month-end, then looks up that employee's monthly logs while preserving employees with no logs. It groups by department, so people without attendance still contribute to headcount.

5. **100x data.** I would load-test with production-like data, inspect execution statistics, tune compound indexes from observed query patterns, and consider pre-aggregated daily summaries for expensive analytics while preserving the source records as authoritative.
