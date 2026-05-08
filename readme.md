# Examples: Unified Guide https://t.me/QcoldVpnPizdaBot

## Overview

Public, GitHub-ready examples for local testing and project API usage.

Files:
- `simple_project_api_bot.py` - interactive client for project subscription/device operations.
- `shop_api_test.py` - local Shop API stub server for integration checks.
- `.env.example` - environment template.

## Quick Start

```bash
cd examples
copy .env.example .env
python simple_project_api_bot.py
```

Run Shop API stub:

```bash
cd examples
python shop_api_test.py
```

## Project API (Project Key Scope)

Base URL:
- `https://api.tgstorage.space`

Authorization:
- `Authorization: Bearer <PROJECT_KEY>`
- `PROJECT_KEY` format: `qcp_...`

Scope:
- `/api/project-access/{project_id}/*`

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/project-access/{project_id}/subscriptions` | Create subscription |
| `GET` | `/api/project-access/{project_id}/subscriptions` | List subscriptions |
| `GET` | `/api/project-access/{project_id}/subscriptions/{token}` | Get subscription |
| `DELETE` | `/api/project-access/{project_id}/subscriptions` | Delete subscription by token |
| `POST` | `/api/project-access/{project_id}/subscriptions/{token}/recreate` | Recreate subscription |
| `GET` | `/api/project-access/{project_id}/devices?subscription_token=...` | List devices |
| `POST` | `/api/project-access/{project_id}/devices/{device_ref}/ban?subscription_token=...` | Ban device |
| `POST` | `/api/project-access/{project_id}/devices/{device_ref}/unban?subscription_token=...` | Unban device |
| `DELETE` | `/api/project-access/{project_id}/devices/{device_ref}?subscription_token=...` | Delete device |

Notes:
- `device_ref` is at least 6 characters.
- Local script: `examples/simple_project_api_bot.py`
- Script uses `examples/.env` (use `.env.example` as template).

## Shop API Stub Server

Script:
- `examples/shop_api_test.py`

What it does:
- Starts a local API server for backend integration checks.
- Accepts requests from local backend services.
- Returns valid JSON for common shop and notification routes.

Default URL:
- `http://127.0.0.1:42351`

### Environment Variables

- `SHOP_STUB_HOST` (default: `127.0.0.1`)
- `SHOP_STUB_PORT` (default: `42351`)
- `SHOP_API_KEY` (optional; enables Bearer auth)
- `SHOP_STUB_INTERACTIVE` (`true/false`, default: `false`)
- `SHOP_STUB_VERBOSE` (`true/false`, default: `false`)

Interactive mode example:

```bash
set SHOP_STUB_INTERACTIVE=true
python shop_api_test.py
```

### Supported Routes

- `GET /fapi/health`
- `GET /health`
- `GET /`
- `GET /sapi/stats`
- `POST /sapi/orders`
- `GET /sapi/orders/{order_id}`
- `GET /sapi/orders/{order_id}/status`
- `POST /sapi/orders/{order_id}/cancel`
- `POST /sapi/cancel`
- `POST /fapi/notifications/new-device`
- `POST /fapi/notifications/limit-exceeded`
- `POST /api/v1/notifications/new-device`
- `POST /api/v1/notifications/limit-exceeded`

## Notes

- Documentation and scripts are user-facing and avoid exposing internal service details.
- Configure values in `.env` before running scripts.
