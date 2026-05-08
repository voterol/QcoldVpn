#!/usr/bin/env python3
"""
Local Shop API stub server for integration checks.

Starts a small HTTP server that waits for requests from backend services and
returns predictable JSON responses.

Run:
  python shop_api_test.py

Environment variables:
  SHOP_API_ENV_FILE=.env          # optional; defaults to .env next to this script
  SHOP_STUB_HOST=127.0.0.1
  SHOP_STUB_PORT=42351
  SHOP_API_KEY=your_key            # optional; if set, requires Bearer token
  SHOP_STUB_INTERACTIVE=false      # true -> ask for missing data via input()
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ENV_FILE = Path(os.getenv("SHOP_API_ENV_FILE", "").strip() or Path(__file__).resolve().with_name(".env"))


def _strip_optional_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key.startswith("#"):
            continue
        os.environ.setdefault(key, _strip_optional_quotes(value))


load_dotenv(ENV_FILE)

HOST = (os.getenv("SHOP_STUB_HOST") or "127.0.0.1").strip()
PORT = int((os.getenv("SHOP_STUB_PORT") or "42351").strip())
SHOP_API_KEY = (os.getenv("SHOP_API_KEY") or "").strip()
INTERACTIVE = (os.getenv("SHOP_STUB_INTERACTIVE") or "false").strip().lower() == "true"
VERBOSE = (os.getenv("SHOP_STUB_VERBOSE") or "false").strip().lower() == "true"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prompt_or_default(name: str, default_value: Any) -> Any:
    if not INTERACTIVE:
        return default_value
    raw = input(f"[stub] Missing '{name}'. Enter value (default={default_value!r}): ").strip()
    if not raw:
        return default_value
    if isinstance(default_value, bool):
        return raw.lower() in {"1", "true", "yes", "y"}
    if isinstance(default_value, int):
        try:
            return int(raw)
        except ValueError:
            return default_value
    return raw


class StubState:
    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.notifications: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def create_or_update_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        order_id = str(payload.get("order_id") or prompt_or_default("order_id", f"order-{uuid.uuid4().hex[:10]}"))
        user_id = int(payload.get("user_id") or prompt_or_default("user_id", 123456789))
        stars_amount = int(payload.get("stars_amount") or prompt_or_default("stars_amount", 100))
        days = payload.get("days")
        max_devices = payload.get("max_devices")
        is_topup = bool(payload.get("is_topup", False))
        extend_token = payload.get("extend_token")
        target_user_id = payload.get("target_user_id") or user_id

        order = {
            "order_id": order_id,
            "user_id": user_id,
            "target_user_id": target_user_id,
            "stars_amount": stars_amount,
            "days": days,
            "max_devices": max_devices,
            "is_topup": is_topup,
            "extend_token": extend_token,
            "status": "pending",
            "created_at": utc_now_iso(),
            "paid_at": None,
            "payer_user_id": None,
            "stars_received": None,
        }
        self.orders[order_id] = order
        return order

    def get_pending_stats(self) -> dict[str, int]:
        pending = [o for o in self.orders.values() if o.get("status") == "pending"]
        return {
            "count": len(pending),
            "total_stars_needed": sum(int(o.get("stars_amount", 0)) for o in pending),
        }

    def append_notification(self, kind: str, payload: dict[str, Any]) -> None:
        self.notifications.append({"kind": kind, "payload": payload, "at": utc_now_iso()})


STATE = StubState()


class ShopStubHandler(BaseHTTPRequestHandler):
    server_version = "ShopApiStub/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if VERBOSE:
            print(f"[{self.log_date_time_string()}] {self.address_string()} - {fmt % args}")

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        content_len = int(self.headers.get("Content-Length", "0") or "0")
        if content_len <= 0:
            return {}
        raw = self.rfile.read(content_len).decode("utf-8", errors="replace").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            return {"data": data}
        except Exception:
            return {"_raw": raw}

    def _authorized(self) -> bool:
        if not SHOP_API_KEY:
            return True
        auth = (self.headers.get("Authorization") or "").strip()
        if not auth.lower().startswith("bearer "):
            self._json_response(401, {"status": "unauthorized"})
            return False
        token = auth.split(" ", 1)[1].strip()
        if token != SHOP_API_KEY:
            self._json_response(403, {"status": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in {"/fapi/health", "/health", "/"}:
            self._json_response(200, {"status": "ok", "service": "shop-api-stub"})
            return

        if not self._authorized():
            return

        if path == "/sapi/stats":
            with STATE.lock:
                stats = STATE.get_pending_stats()
            self._json_response(
                200,
                {
                    "pending_orders_count": stats["count"],
                    "pending_stars_total": stats["total_stars_needed"],
                    "pause_threshold_orders": 10,
                    "pause_threshold_stars": 5000,
                    "inactivity_minutes": 30,
                    "auto_operations_paused": False,
                    "pause_reason": "stub_mode",
                },
            )
            return

        match_order = re.fullmatch(r"/sapi/orders/([^/]+)", path)
        if match_order:
            order_id = match_order.group(1)
            with STATE.lock:
                order = STATE.orders.get(order_id)
            if not order:
                self._json_response(404, {"status": "not_found"})
                return
            self._json_response(
                200,
                {
                    "order_id": order["order_id"],
                    "user_id": order["user_id"],
                    "target_user_id": order.get("target_user_id"),
                    "stars_amount": order["stars_amount"],
                    "days": order.get("days"),
                    "max_devices": order.get("max_devices"),
                    "is_topup": order.get("is_topup", False),
                    "status": order["status"],
                },
            )
            return

        match_status = re.fullmatch(r"/sapi/orders/([^/]+)/status", path)
        if match_status:
            order_id = match_status.group(1)
            with STATE.lock:
                order = STATE.orders.get(order_id)
            if not order:
                self._json_response(404, {"status": "not_found"})
                return
            remaining_minutes = None
            if order["status"] == "pending":
                created_at = datetime.fromisoformat(order["created_at"])
                expiry = created_at + timedelta(hours=3)
                remaining = int((expiry - datetime.now(timezone.utc)).total_seconds() / 60)
                remaining_minutes = max(0, remaining)
            self._json_response(
                200,
                {
                    "order_id": order_id,
                    "status": order["status"],
                    "paid_at": order.get("paid_at"),
                    "payer_user_id": order.get("payer_user_id"),
                    "stars_received": order.get("stars_received"),
                    "remaining_minutes": remaining_minutes,
                },
            )
            return

        self._json_response(404, {"status": "not_found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        payload = self._read_json()

        if VERBOSE:
            print(f"\n[stub] {self.command} {path}")
            if payload:
                print(f"[stub] payload: {json.dumps(payload, ensure_ascii=False)}")

        if path in {"/fapi/health"}:
            self._json_response(200, {"status": "ok", "service": "shop-api-stub"})
            return

        if not self._authorized():
            return

        if path == "/sapi/orders":
            with STATE.lock:
                order = STATE.create_or_update_order(payload)
            self._json_response(
                200,
                {
                    "order_id": order["order_id"],
                    "payment_url": f"https://t.me/stub_userbot?start={order['order_id']}",
                    "stars_amount": order["stars_amount"],
                },
            )
            return

        match_cancel = re.fullmatch(r"/sapi/orders/([^/]+)/cancel", path)
        if match_cancel:
            order_id = match_cancel.group(1)
            with STATE.lock:
                order = STATE.orders.get(order_id)
                if not order:
                    self._json_response(404, {"status": "not_found"})
                    return
                if order["status"] != "pending":
                    self._json_response(400, {"status": "cannot_cancel"})
                    return
                order["status"] = "cancelled"
            self._json_response(200, {"status": "cancelled", "order_id": order_id})
            return

        if path == "/sapi/cancel":
            order_id = str(payload.get("order_id") or prompt_or_default("order_id", "missing-order-id"))
            with STATE.lock:
                order = STATE.orders.get(order_id)
                if not order:
                    self._json_response(200, {"status": "not_found", "order_id": order_id})
                    return
                if order["status"] != "pending":
                    self._json_response(200, {"status": "already_processed", "order_id": order_id})
                    return
                order["status"] = "cancelled"
            self._json_response(200, {"status": "cancelled", "order_id": order_id})
            return

        if path in {"/fapi/notifications/new-device", "/api/v1/notifications/new-device"}:
            payload.setdefault("subscription_token", prompt_or_default("subscription_token", f"stub-{uuid.uuid4().hex[:8]}"))
            payload.setdefault("user_agent", prompt_or_default("user_agent", "stub-client/1.0"))
            with STATE.lock:
                STATE.append_notification("new-device", payload)
            self._json_response(200, {"status": "sent", "mode": "stub", "kind": "new-device"})
            return

        if path in {"/fapi/notifications/limit-exceeded", "/api/v1/notifications/limit-exceeded"}:
            payload.setdefault("subscription_token", prompt_or_default("subscription_token", f"stub-{uuid.uuid4().hex[:8]}"))
            payload.setdefault("user_agent", prompt_or_default("user_agent", "stub-client/1.0"))
            payload.setdefault("client_ip", prompt_or_default("client_ip", "127.0.0.1"))
            payload.setdefault("ip_count", prompt_or_default("ip_count", 1))
            payload.setdefault("device_count", prompt_or_default("device_count", 1))
            with STATE.lock:
                STATE.append_notification("limit-exceeded", payload)
            self._json_response(200, {"status": "sent", "mode": "stub", "kind": "limit-exceeded"})
            return

        self._json_response(404, {"status": "not_found"})


def main() -> int:
    print("[shop-stub] Starting Shop API test server")
    print(f"[shop-stub] URL: http://{HOST}:{PORT}")
    print(f"[shop-stub] API key required: {'yes' if SHOP_API_KEY else 'no'}")
    print(f"[shop-stub] Interactive mode: {'on' if INTERACTIVE else 'off'}")
    print(f"[shop-stub] Verbose logs: {'on' if VERBOSE else 'off'}")
    print("[shop-stub] Waiting for backend requests. Press Ctrl+C to stop.\n")

    server = ThreadingHTTPServer((HOST, PORT), ShopStubHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[shop-stub] Stopping...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
