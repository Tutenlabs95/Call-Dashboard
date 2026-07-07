# Call Center Dashboard — network access issue for dev team

**Repo:** https://github.com/Tutenlabs95/Call-Dashboard
**Reported by:** Dylan Turman
**Date found:** 2026-07-07

## Summary

The dashboard (`index.html` + `data.json`) and its daily updater (`update_data.py`,
triggered by `.github/workflows/update-dashboard.yml`) are fully built and committed to
`main`. Everything about the GitHub side of the setup is correct and verified working:
files are in the right place, `.github/workflows/update-dashboard.yml` is recognized by
GitHub Actions, and all three required secrets (`METABASE_URL`, `METABASE_USER`,
`METABASE_PASSWORD`) are set correctly on the repo.

**The one thing that doesn't work:** GitHub's hosted Actions runners cannot reach
`metabase.ops.tutenlabs.com` over the network. This needs an infra decision/fix from
the team, which is why this is being handed off.

## Evidence

Manual run of the workflow (`Actions → Update call center dashboard data → Run workflow`)
fails every time at the login step, before it ever gets a chance to authenticate:

```
Fetching 2026-07-06 from Metabase table 12288...
Traceback (most recent call last):
  ...
  File ".../urllib3/connection.py", line 213, in _new_conn
    raise ConnectTimeoutError(
urllib3.exceptions.ConnectTimeoutError: (<HTTPSConnection(host='metabase.ops.tutenlabs.com', port=443)>,
  'Connection to metabase.ops.tutenlabs.com timed out. (connect timeout=30)')
...
requests.exceptions.ConnectTimeout: HTTPSConnectionPool(host='metabase.ops.tutenlabs.com', port=443):
  Max retries exceeded with url: /api/session
Error: Process completed with exit code 1.
```

This is a `ConnectTimeout` at the TCP level — the runner can't even open a socket to
port 443 on that host. That's not a credentials problem or a bug in `update_data.py`;
it means `metabase.ops.tutenlabs.com` isn't reachable from the public internet (where
GitHub-hosted runners live), most likely because it sits behind a corporate
firewall/VPN or an IP allowlist.

You can reproduce this yourself from any machine **not** on the office network/VPN:
`curl -v https://metabase.ops.tutenlabs.com` — if that also hangs/times out, it
confirms the host is network-restricted rather than just an Actions-specific quirk.

## Options (pick one — this is the decision we need from the dev/infra team)

### Option A — Self-hosted GitHub Actions runner (recommended if you have a server on the VPN)

Run the GitHub Actions *runner* itself on a machine that's already inside the network
that can reach Metabase (an existing internal server, a small VM, even a container).
The workflow logic doesn't change at all — only which machine executes it.

1. On a machine inside the network: repo → **Settings → Actions → Runners → New
   self-hosted runner**, follow GitHub's generated install script for your OS.
2. Once it's registered and shows "Idle" in the Runners list, swap one line in the
   workflow file: change `runs-on: ubuntu-latest` to `runs-on: self-hosted`.
   (`update-dashboard-self-hosted.yml` in this handoff is the workflow file with that
   change already made — just replace the contents of
   `.github/workflows/update-dashboard.yml` with it.)
3. Nothing else changes. Secrets, schedule, and `update_data.py` all stay the same.
4. Re-run the workflow manually to confirm it now reaches Metabase.

Tradeoff: someone has to keep that runner machine up and patched. For a single daily
job this is usually a non-issue (idles at ~0% CPU between runs).

### Option B — Cron job on an internal server, pushing to GitHub (no GitHub Actions involved)

Skip GitHub Actions entirely for the *pulling* part. Run `update_data.py` on a cron
schedule on any internal server that can already reach Metabase, then have that same
job `git push` the updated `data.json` back to the repo. GitHub Pages picks up the new
`data.json` automatically once it's pushed — no Actions run needed.

`push_data.sh` (included in this handoff) is a ready-to-use wrapper: it clones/pulls the
repo, runs `update_data.py`, commits, and pushes, using a **fine-grained GitHub Personal
Access Token** (scoped to just this repo, contents: read/write) instead of a full login.

Setup:
1. Pick an internal server that can reach `metabase.ops.tutenlabs.com` and has `git`,
   `python3`, and `pip` available.
2. Create a GitHub PAT: **github.com → Settings → Developer settings → Fine-grained
   tokens → Generate new token**, scope it to only the `Call-Dashboard` repo, permission
   `Contents: Read and write`.
3. Copy `push_data.sh` and `update_data.py` to that server, fill in the placeholders at
   the top of `push_data.sh` (repo URL, PAT, Metabase credentials), and test it manually:
   `bash push_data.sh`
4. Add it to that server's crontab to run once a day after close of business, e.g.:
   `10 6 * * * /path/to/push_data.sh >> /var/log/call-dashboard-update.log 2>&1`
5. You can then either delete `.github/workflows/update-dashboard.yml` or just leave it
   disabled — it won't hurt anything sitting unused, but it also won't run successfully
   from GitHub's side, so don't rely on it.

### Option C — Open up network access to GitHub's runners (not recommended)

Technically possible by allowlisting GitHub's published Actions runner IP ranges
(`https://api.github.com/meta` → `actions` key) on whatever firewall/proxy sits in
front of Metabase. Not recommended: those IP ranges are large, shared across every
GitHub Actions customer, and rotate over time — this is a much bigger, harder-to-audit
firewall change than options A or B for the same result.

## What does NOT need to change

- `index.html`, `data.json`'s structure/schema, and `update_data.py`'s logic are all
  correct and tested — only *where* `update_data.py` runs needs to change.
- The separate, still-open issue that the source Metabase table ("Calls", table id
  `12288`) hasn't synced past 2025-11-03 is unrelated to this network problem and is
  tracked in `README.md`'s "Data quality notes" section.
