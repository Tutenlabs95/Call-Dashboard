# Call Center Rolling Dashboard

A static, GitHub Pages-ready dashboard tracking:

- Calls answered within 30 seconds
- Calls answered within 2 minutes
- Calls abandoned
- Calls transferred to CBSI
- SLA % attained (any call resolved within 5 minutes, as a share of all calls)

Data comes from the Metabase **Calls** table (Analytics database, table id `12288`), a
Five9 call-log export, filtered to all clients/statuses (no client or status filters).

## Files

| File | Purpose |
|---|---|
| `index.html` | The dashboard itself. Single file, no build step. Reads `data.json`. |
| `data.json` | Daily aggregated metrics. Currently backfilled with all available history. |
| `update_data.py` | Pulls one day of calls from Metabase and upserts it into `data.json`. |
| `update-dashboard.yml` | GitHub Actions workflow — move this to `.github/workflows/update-dashboard.yml` after upload (see setup below). |

## ⚠️ Data quality notes (read before sharing externally)

1. **The Metabase "Calls" table has not synced since 2025-11-03.** `data.json` is
   backfilled with all history that *is* available (2024-10-17 through 2025-11-03) so
   the dashboard, the update script, and the GitHub Action all work end-to-end today.
   Once the table starts receiving 2026 records again (or you point `update_data.py`
   at wherever 2026 data actually lives, via the `METABASE_TABLE_ID` env var), the
   daily Action will start appending real current-day rows automatically — no code
   changes needed.
2. **A large share of timing fields are corrupted in the source table.** `Total Queue
   Time` and `Time To Abandon` are sometimes stored as valid day-fraction decimals and
   sometimes as garbled comma-decimal scientific notation (e.g. `7,15E+09`). Rows with
   unparseable values are excluded from the 30s / 2min / 5min SLA buckets specifically
   (roughly 60–70% of answered calls lack a usable queue-time value), but are still
   counted in totals / answered / abandoned / CBSI counts, which key off `Talk Time`
   and `Disposition` instead. Full definitions are in `data.json → metricDefinitions`.
3. **"Answered"** is defined as `Talk Time > 0` (the caller actually connected with an
   agent) rather than any specific disposition code, since disposition codes like
   "Next Call" are used inconsistently in this table.

## Setup

1. Create a new GitHub repo and upload all the files in this folder to its root.
2. Move `update-dashboard.yml` into `.github/workflows/update-dashboard.yml`
   (GitHub's web uploader won't let you create a folder starting with `.` directly —
   either use `git` locally, or create the repo with GitHub Desktop / CLI, or add the
   file through the GitHub web UI's "Create new file" with that full path typed in).
3. In the repo, go to **Settings → Secrets and variables → Actions** and add:
   - `METABASE_URL` — e.g. `https://metabase.ops.tutenlabs.com`
   - `METABASE_USER` — a Metabase login with read access to the Analytics database
   - `METABASE_PASSWORD`
4. Go to **Settings → Pages**, set source to the `main` branch / root folder, and save.
   Your dashboard will be live at `https://<you>.github.io/<repo>/`.
5. The workflow runs daily at 06:10 UTC and can also be triggered manually from the
   **Actions** tab (`Run workflow`). It pulls "yesterday" by Metabase's clock — adjust
   the cron schedule in the workflow file if your call center's day boundary differs.

## Backfilling or re-running a specific day

```bash
pip install requests
export METABASE_URL=https://metabase.ops.tutenlabs.com
export METABASE_USER=you@example.com
export METABASE_PASSWORD=your-password
TARGET_DATE=2026-01-15 python update_data.py
```

Re-running for a date that's already in `data.json` simply recomputes and replaces
that day's entry — safe to re-run.
