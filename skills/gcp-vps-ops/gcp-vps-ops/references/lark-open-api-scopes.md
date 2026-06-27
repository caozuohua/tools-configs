---
title: Lark Open API scope names — exact strings for permission applications
source: real session 2026-06-15, cross-verified against open.larkoffice.com scope list, feishu-cli.com, Verdent AI guide
applies_to: Lark/Feishu Open Platform applications (any version, international and CN)
---

# Lark Open API Scope Reference

When building an app that calls Lark/Feishu Open APIs (calendar, bitable,
docs, etc.), the developer backend at `open.feishu.cn/app` requires you to
apply for **scope strings** by name. This file lists the exact names,
approval level, and what they're for. Cross-checked against the official
Lark scope list on 2026-06-15.

## Convention reminder

- **Naming pattern:** `module:resource:action` (e.g., `calendar:calendar:read`)
- **Action suffix `:readonly`** = read-only; **no suffix** = full read+write
- **Basic** = auto-approved (minutes to hours); **Advanced** = manual review
  (1-3 business days for self-built apps)
- **Tenant-level scopes** see data across the entire org
- Some scopes have **sensitive fields** requiring an extra `contact:user.employee:readonly`
  type sub-scope

## Identity: which token to use

Lark has TWO access token types — pick correctly or you'll get 99991663 errors.

| Token | Identity | When | Requires |
|-------|----------|------|----------|
| `tenant_access_token` | App/bot | Read org-level data, send bot messages | App ID + App Secret only |
| `user_access_token` | Specific user | Read/write the user's calendar, bitable, mail | OAuth flow + `offline_access` scope |

For per-user actions (a user's calendar, a user's bitable rows) you MUST
go through OAuth and use `user_access_token`. `tenant_access_token` can
only see org-shared resources.

`user_access_token` **expires in 2 hours** — `offline_access` scope is
required to receive a `refresh_token` for long-lived sessions. Do not
ship a Lark integration without it.

## Calendar v4 scopes (open-apis/calendar/v4)

| Scope | Level | Use for |
|-------|-------|---------|
| `calendar:calendar:readonly` | Basic | List events, query free/busy, get agenda |
| `calendar:calendar` | Advanced | Create / update / delete events, set attendees, recurrence |

## Bitable (Base) v1 scopes (open-apis/bitable/v1)

| Scope | Level | Use for |
|-------|-------|---------|
| `bitable:app:readonly` | Basic | List apps, list tables, list/get records, search |
| `bitable:app` | Advanced | Create / update / delete records, manage fields and views |

Note: some advanced record operations may also want `bitable:record` (appears
in a few third-party guides). In practice `bitable:app` covers record-level
CRUD; treat `bitable:record` as a backup.

## Docs / Sheets / Drive scopes (for future expansion)

| Scope | Level | Use for |
|-------|-------|---------|
| `docs:doc:readonly` | Basic | Read doc content |
| `docs:doc` | Advanced | Create / edit / delete docs |
| `sheets:spreadsheet:readonly` | Basic | Read sheets |
| `sheets:spreadsheet` | Advanced | Write sheets |
| `drive:drive:readonly` | Basic | List user drive files |
| `drive:drive` | Advanced | All of user's drive (over-permissioned; prefer per-file scopes) |
| `wiki:wiki:readonly` | Basic | Read wiki nodes |
| `wiki:wiki` | Advanced | Edit wiki |

## Identity / contact scopes (needed for OAuth user resolution)

| Scope | Level | Use for |
|-------|-------|---------|
| `contact:user.base:readonly` | Basic | Read user name, en_name, avatar from open_id |
| `contact:user.employee_id:readonly` | Advanced | Read user's employee_id |
| `contact:user_id:readonly` | Advanced | Map email/phone → open_id/user_id |
| `offline_access` | Advanced | **REQUIRED** for refresh_token in OAuth flow |

## IM (messaging) scopes (only if you also need bot messaging)

| Scope | Level | Use for |
|-------|-------|---------|
| `im:message:send_as_bot` | Basic | Send messages as the bot |
| `im:message` | Advanced | Send/receive DMs and group messages |
| `im:chat:readonly` | Basic | Read group info |

## IM v1 international vs CN scope name split

The Lark platform has TWO deployments and the scope strings are NOT
identical between them. Most code uses `lark-oapi` SDK which abstracts
this, but when you write a scope literally in a URL or OAuth config you
must pick the right one:

| Feature | `lark-api` (international) | `feishu-api` (CN) |
|---------|----------------------------|-------------------|
| Calendar | `calendar:calendar` | same |
| Bitable  | `bitable:app`             | same |
| Docs     | `docs:doc`                | same |
| User     | `contact:user.base:readonly` | same |

The actual API endpoints differ (`https://open.larksuite.com` vs
`https://open.feishu.cn`) but the **scope names are mostly shared**. If
you find a scope string that doesn't seem to work, you're probably
hitting a docs/code drift — the official list is the source of truth.

## Application text (Chinese) for advanced scope approval

When filling in the application reason, this text covers calendar + bitable
+ identity + offline_access. Edit per your use case:

```
本应用作为个人 AI 助手，通过 MCP server 暴露日程管理（calendar）和
多维表格（bitable）能力给本地 agent，用于自动化日常任务规划。需要
user_access_token 调用用户级 API，因此需要 offline_access 用于
refresh；contact:user.base:readonly 用于把飞书消息发送者的 open_id
解析为可读身份。所有写操作会在执行前向用户二次确认。
```

Approval time: usually 1-3 business days for self-built apps on Lark/Feishu
personal edition. Enterprise tenants may be faster if the admin pre-approves.

## Verification recipe after approval

```bash
# 1. Get tenant_access_token (just App ID + App Secret)
curl -X POST https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal \
  -H "Content-Type: application/json" \
  -d '{"app_id":"cli_xxx","app_secret":"xxx"}'

# 2. Probe a read endpoint to confirm scope is live
curl -X GET "https://open.larksuite.com/open-apis/calendar/v4/calendars" \
  -H "Authorization: Bearer t-xxx"

# Expected: 200 with calendars list, OR 99991663 if scope still pending
# Expected: 200 with empty list if scope granted but no data

# 3. For user-scoped APIs, run the OAuth flow first:
#    User clicks authorize URL → redirects to YOUR_REDIRECT_URI?code=xxx
#    Exchange code for user_access_token:
curl -X POST https://open.larksuite.com/open-apis/authen/v2/oauth/token \
  -H "Content-Type: application/json" \
  -d '{"grant_type":"authorization_code","code":"xxx","client_id":"cli_xxx","client_secret":"xxx"}'
# Response includes user_access_token (2h) and refresh_token (long-lived)
```

If you get 99991663 ("scope not enabled"), the scope either isn't
approved yet OR isn't actually in the app's permission list — re-check
the developer console, not the API.

## Pitfall: 99991663 vs 99991672

- `99991663` = "permission denied" (scope not enabled OR not approved yet)
- `99991672` = "user not in app's visible range" (scope enabled, but
  target user/org hasn't been added to the app's availability)

If 99991672 with valid scopes: ask the org admin to add the app to the
target user's available apps in the Lark admin console.
