---
name: headless-google-oauth
description: Authenticate Google APIs from a server with no browser/display using InstalledAppFlow + URL paste-back. Works for Drive, Gmail, Sheets, Calendar, any Google API. Use when google-auth-oauthlib's run_local_server() can't open a browser (servers, CI, containers, SSH-only access).
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [google, oauth, headless, drive, pkce, desktop-app, installed-app-flow]
---

# Headless Google OAuth (InstalledAppFlow + URL paste-back)

## Overview

Standard `InstalledAppFlow.run_local_server(port=0)` opens a browser on the host and listens for the OAuth redirect. On a server with no browser/display, this hangs forever. The fix is a **two-phase script**:

1. **Print phase** — generate the authorization URL with `flow.authorization_url(...)`. Print it. User opens in any browser (phone, laptop, anywhere).
2. **Exchange phase** — user pastes back the FULL redirect URL (starts with `http://localhost/?code=...&scope=...`). Script exchanges code for token and writes `Credentials.to_json()` to disk.

The same pattern works for **any Google API** — Drive, Gmail, Sheets, Calendar, Cloud Storage, etc. Just change the `SCOPES` list.

## When to use

- Server has no GUI / no browser installed
- You can't (or won't) set up SSH port forwarding
- You have a phone or laptop nearby with a browser
- The OAuth client is "Desktop app" type (redirect URI `http://localhost`, not `http://localhost:PORT`)
- The user can copy a URL from a browser address bar and paste it back to chat

## The two-phase pattern

```python
# Phase 1: print auth URL
flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
flow.redirect_uri = "http://localhost"   # MUST match what's in client_secrets.json
auth_url, state = flow.authorization_url(
    access_type="offline",          # required for refresh_token
    include_granted_scopes="true",
    prompt="consent",               # force consent screen, ensures refresh_token issued
)
print(auth_url)
# Save state for phase 2 (code_verifier for PKCE)
pickle.dump({"code_verifier": flow.code_verifier, "state": state}, open(STATE, "wb"))
```

```python
# Phase 2: exchange pasted URL
saved = pickle.load(open(STATE, "rb"))
flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
flow.redirect_uri = "http://localhost"
flow.code_verifier = saved["code_verifier"]   # MUST restore or PKCE fails
flow.state = saved["state"]
code = parse_qs(urlparse(redirect_url).query)["code"][0]
flow.fetch_token(code=code)
TOKEN_PATH.write_text(flow.credentials.to_json())
```

A working reference is at `scripts/oauth-headless-helper.py` — drop-in for any Google API by editing `SCOPES`.

## Token storage format

`Credentials.to_json()` produces this shape; `from_authorized_user_file()` reads it back:

```json
{
  "token": "ya29.xxx",
  "refresh_token": "1//xxx",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "xxx.apps.googleusercontent.com",
  "client_secret": "GOCSPX-xxx",
  "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
  "token_type": "Bearer",
  "expiry": "2026-06-13T18:43:56.123456Z"
}
```

Store with mode 0o600. Subsequent runs auto-refresh via `creds.expired and creds.refresh_token` check.

## Pitfalls

- **Don't `pickle.dumps(flow)`** — `OAuth2Session.__init__` contains an unpicklable lambda (likely a `compliance_fix` hook). You'll get `AttributeError: Can't pickle local object`. Workaround: save only `flow.code_verifier` and `flow.state` (both plain strings) to a `.pkl` dict, then reconstruct a fresh `InstalledAppFlow` in phase 2 and set the two attributes on it before `fetch_token()`.
- **Don't forget PKCE restoration** — when the auth URL includes `code_challenge=...&code_challenge_method=S256` (it always does by default in modern `google-auth-oauthlib`), Google will reject the token exchange unless you restore `flow.code_verifier` on the second-phase flow instance. Symptom: `invalid_grant` error.
- **Don't use `redirect_uri="http://localhost:8080"`** unless your `client_secrets.json` lists that EXACT URI in `redirect_uris`. Mismatches fail with `redirect_uri_mismatch`. The Desktop app default in `client_secrets.json` is `"http://localhost"` (no port). Match it exactly.
- **Don't use `prompt="none"`** — that needs a prior session, which a headless server never has. Use `prompt="consent"` to always get the consent screen and a fresh `refresh_token`.
- **Don't skip `access_type="offline"`** — without it, you get an access token but NO `refresh_token`, and the token expires in 1 hour with no way to refresh. With `offline` + `prompt=consent`, Google issues a `refresh_token` that lasts until manually revoked.
- **Don't redirect to a real port you can't bind** — the classic `run_local_server()` opens `http://localhost:8080` and waits. If you're doing paste-back, the user has to copy the URL after the browser says "site can't be reached" — that's expected and not a bug.
- **Don't sign in as a different Google account** than the one owning the data being accessed. If the configured Drive folder belongs to `alice@gmail.com` but the user authorizes as `bob@gmail.com`, the folder won't be visible. Surface the authorized user via `service.about().get(fields='user').execute()['user']['emailAddress']` after the first exchange to confirm.
- **Don't reuse the same Drive token for SA-style API access** — OAuth tokens are USER-bound; the token can only access files the user has access to. For service-account-style access (e.g., reading public buckets), use `GOOGLE_APPLICATION_CREDENTIALS` pointing at a SA key, not a user OAuth token.
- **Don't let the auth URL sit too long before the user authorizes** — Google's auth code is short-lived (typically 10 min, sometimes less). If the user opens the URL hours later, they'll get `invalid_grant` at the exchange step. If a long delay is expected, re-run the `url` phase to get a fresh URL + new `code_verifier`. Same goes for the `state` in `/tmp/.headless_oauth_state.pkl` — it has no value once the code expires.
- **Don't confuse `gcloud` auth with `GOOGLE_APPLICATION_CREDENTIALS`** — `gcloud` defaults to the VM's compute SA (e.g. `PROJECT_NUMBER-compute@developer.gserviceaccount.com`), NOT the SA in your key file. If you `gcloud storage buckets get-iam-policy` and get 403, that's because the *compute SA* lacks permission, not your `api-user` SA. To verify the SA in `GOOGLE_APPLICATION_CREDENTIALS` has access, use Python with explicit `Credentials.from_service_account_file()` and call the API directly.

## Verification

After phase 2, the **most direct** test is to call `about().get()` — it works on every Drive-enabled account and doesn't need a folder ID:

```python
service = build("drive", "v3", credentials=creds, cache_discovery=False)
user = service.about().get(fields="user").execute()["user"]
print(f"authorized as: {user['emailAddress']} ({user['displayName']})")
```

If you also want to confirm folder access, list 1 file from each configured Drive folder:

```python
service.files().list(
    q=f"'{FOLDER_ID}' in parents and trashed = false",
    pageSize=1, fields="files(id,name,mimeType)",
    supportsAllDrives=True, includeItemsFromAllDrives=True,
).execute()
```

A 404 on the folder means wrong ID; 403 means token valid but no access; 200 + empty `files` means the folder is empty.

## Why not just use SSH port forwarding?

`gcloud compute ssh --ssh-flag="-L 8080:localhost:8080"` (or `ssh -L`) lets the local browser hit `http://localhost:8080` and the redirect reaches the server's listener. Works in principle but:

- Requires the user to have a local machine with a browser (sometimes you don't)
- `gcloud compute ssh` port forwarding can be flaky with OS Login + 2FA
- The paste-back pattern works from a phone, a borrowed laptop, anywhere

Use port forwarding when the script will be re-run frequently. Use paste-back for one-time setup or rare jobs.

## First-run slowness on Drive API

`googleapiclient.discovery.build("drive", "v3", ...)` does heavy cold-start work (~3-5s). It's slower on the FIRST call of a session. If a script times out at 60s, it might just be doing init, not a real hang. Give it 180-300s the first time, and `cache_discovery=False` (the default) is correct for production — set `True` only for repeated calls in one process.

**Concrete measurement from a 3-folder / 45-file Drive tree:**
- `AI` folder (~3 files, flat): walk finished in ~2s
- `Electric` folder (~15 files, deeper tree): walk took ~3 min
- `Other` folder (~27 files): walk took ~16s
- Total: ~3.5 min for the whole `kb ingest --dry-run` first time

If you have N folders of unknown depth, budget **5 min for the first walk across all of them** even if individual folders look small — the API does paginated `files.list` with `pageSize=200` per page, and deeply-nested folders have higher per-call latency.
