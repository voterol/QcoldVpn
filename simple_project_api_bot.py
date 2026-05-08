#!/usr/bin/env python3
import json
import logging
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

# =========================
# НАСТРОЙКИ ИЗ .env
# =========================
ENV_FILE = Path(os.getenv("PROJECT_API_ENV_FILE", ".env"))


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


def get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if value is None or (required and not value.strip()):
        raise RuntimeError(
            f"Не задана переменная {name}. "
            f"Добавьте ее в {ENV_FILE.resolve()} или в окружение."
        )
    return value.strip()


def get_env_int(name: str, default: int) -> int:
    raw = get_env(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Переменная {name} должна быть целым числом, сейчас: {raw!r}") from exc


load_dotenv(ENV_FILE)

BASE_URL = get_env("PROJECT_API_BASE_URL", "https://api.tgstorage.space")
FALLBACK_BASE_URL = get_env("PROJECT_API_FALLBACK_URL", "")
PROJECT_ID = get_env("PROJECT_ID", required=True)
PROJECT_KEY = get_env("PROJECT_KEY", required=True)
REQUEST_TIMEOUT = get_env_int("PROJECT_API_TIMEOUT", 30)
DEBUG_MODE = get_env("PROJECT_API_DEBUG", "false").lower() == "true"

DEFAULT_EXPIRES_DAYS = 30
DEFAULT_MAX_DEVICES = 3

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("simple_project_api_bot")


def _configure_console_utf8() -> None:
    if os.name == "nt":
        try:
            os.system("chcp 65001 > nul")
        except Exception:
            pass
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _do_request(base_url: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {PROJECT_KEY}",
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    if DEBUG_MODE:
        log.debug("REQUEST %s %s", method.upper(), url)
        if body is not None:
            log.debug("BODY %s", json.dumps(body, ensure_ascii=False))

    req = Request(url=url, method=method.upper(), headers=headers, data=data)

    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            payload = parse_json(raw)
            if DEBUG_MODE:
                log.debug("RESPONSE %s %s", resp.status, url)
            return resp.status, payload
    except HTTPError as e:
        if DEBUG_MODE:
            raw = e.read().decode("utf-8", errors="replace")
            payload = parse_json(raw)
            log.debug("RESPONSE %s %s", e.code, url)
            log.debug("ERROR_PAYLOAD %s", json.dumps(payload, ensure_ascii=False))
        return e.code, {"status": "failed", "message": "Операция временно недоступна"}
    except URLError as e:
        if DEBUG_MODE:
            log.debug("NETWORK_ERROR %s", str(e))
        return 0, {"status": "failed", "message": "Сервис недоступен. Попробуйте позже"}


def api_request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    status, payload = _do_request(BASE_URL, method, path, body)
    if status != 0:
        return status, payload

    if FALLBACK_BASE_URL and FALLBACK_BASE_URL.rstrip("/") != BASE_URL.rstrip("/"):
        if DEBUG_MODE:
            log.debug("FALLBACK %s -> %s", BASE_URL, FALLBACK_BASE_URL)
        return _do_request(FALLBACK_BASE_URL, method, path, body)

    return status, payload


def parse_json(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
    except Exception:
        return {"raw": text}


def show_result(status: int, payload: dict) -> None:
    if 200 <= status < 300:
        print("Готово.")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("Операция не выполнена.")
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        print(message.strip())
    else:
        print("Попробуйте позже.")


def create_subscription() -> None:
    days_raw = input(f"Срок в днях [{DEFAULT_EXPIRES_DAYS}]: ").strip()
    devices_raw = input(f"Макс. устройств [{DEFAULT_MAX_DEVICES}]: ").strip()
    days = int(days_raw) if days_raw else DEFAULT_EXPIRES_DAYS
    devices = int(devices_raw) if devices_raw else DEFAULT_MAX_DEVICES

    status, payload = api_request(
        "POST",
        f"/api/project-access/{PROJECT_ID}/subscriptions",
        {"expires_in_days": days, "max_devices": devices},
    )
    show_result(status, payload)
    if status == 200 and payload.get("token"):
        print(f"Новый токен: {payload['token']}")


def get_subscription() -> None:
    token = input("Токен подписки: ").strip()
    if not token:
        print("Токен пустой")
        return
    if token == PROJECT_KEY or token.startswith("qcp_"):
        print("Похоже, это PROJECT_KEY (qcp_...), а не token подписки. Создайте подписку через пункт 1 и используйте ее token.")
        return
    status, payload = api_request(
        "GET",
        f"/api/project-access/{PROJECT_ID}/subscriptions/{token}",
    )
    show_result(status, payload)
    if status == 200:
        compact = {
            "token": payload.get("token"),
            "expires_at": payload.get("expires_at"),
            "max_devices": payload.get("max_devices"),
            "subscription_url": payload.get("subscription_url"),
        }
        print("Короткий формат:")
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print("-" * 60)


def delete_subscription() -> None:
    token = input("Токен для удаления: ").strip()
    if not token:
        print("Токен пустой")
        return
    status, payload = api_request(
        "DELETE",
        f"/api/project-access/{PROJECT_ID}/subscriptions",
        {"token": token},
    )
    show_result(status, payload)


def recreate_subscription() -> None:
    token = input("Текущий токен: ").strip()
    if not token:
        print("Токен пустой")
        return
    new_tag = input("Новый tag (можно Enter): ").strip()
    body = {"new_tag": new_tag} if new_tag else {}
    status, payload = api_request(
        "POST",
        f"/api/project-access/{PROJECT_ID}/subscriptions/{token}/recreate",
        body,
    )
    show_result(status, payload)
    if status == 200 and payload.get("token"):
        print(f"Новый токен после перевыпуска: {payload['token']}")


def list_devices() -> None:
    token = input("Токен подписки для списка устройств: ").strip()
    if not token:
        print("Токен пустой")
        return
    status, payload = api_request(
        "GET",
        f"/api/project-access/{PROJECT_ID}/devices?subscription_token={quote(token, safe='')}",
    )
    show_result(status, payload)
    if status == 200:
        devices = payload.get("devices") or []
        print(f"Найдено устройств: {len(devices)}")
        for item in devices:
            ref = str(item.get("device_ref") or "")
            hwid = str(item.get("hwid") or "")
            short_hwid = hwid[:16] + "..." if len(hwid) > 16 else hwid
            print(f"- ref={ref or '-'} hwid={short_hwid}")


def ban_device() -> None:
    token = input("Токен подписки устройства: ").strip()
    if not token:
        print("Токен пустой")
        return
    device_ref = input("device_ref для блокировки (первые 10 символов HWID): ").strip().lower()
    if len(device_ref) < 6:
        print("device_ref должен быть минимум 6 символов")
        return
    status, payload = api_request(
        "POST",
        f"/api/project-access/{PROJECT_ID}/devices/{quote(device_ref, safe='')}/ban?subscription_token={quote(token, safe='')}",
    )
    show_result(status, payload)


def unban_device() -> None:
    token = input("Токен подписки устройства: ").strip()
    if not token:
        print("Токен пустой")
        return
    device_ref = input("device_ref для разблокировки (первые 10 символов HWID): ").strip().lower()
    if len(device_ref) < 6:
        print("device_ref должен быть минимум 6 символов")
        return
    status, payload = api_request(
        "POST",
        f"/api/project-access/{PROJECT_ID}/devices/{quote(device_ref, safe='')}/unban?subscription_token={quote(token, safe='')}",
    )
    show_result(status, payload)


def delete_device() -> None:
    token = input("Токен подписки устройства: ").strip()
    if not token:
        print("Токен пустой")
        return
    device_ref = input("device_ref для удаления (первые 10 символов HWID): ").strip().lower()
    if len(device_ref) < 6:
        print("device_ref должен быть минимум 6 символов")
        return
    status, payload = api_request(
        "DELETE",
        f"/api/project-access/{PROJECT_ID}/devices/{quote(device_ref, safe='')}?subscription_token={quote(token, safe='')}",
    )
    show_result(status, payload)


def print_menu() -> None:
    print("\n=== SIMPLE PROJECT API BOT ===")
    print(f"BASE_URL   = {BASE_URL}")
    print(f"FALLBACK   = {FALLBACK_BASE_URL}")
    print(f"PROJECT_ID = {PROJECT_ID}")
    print("1 - Создать ключ (подписку)")
    print("2 - Получить формат ключа по токену")
    print("3 - Удалить ключ (подписку)")
    print("4 - Перевыпустить подписку")
    print("5 - Показать устройства (по токену подписки)")
    print("6 - Заблокировать устройство")
    print("7 - Разблокировать устройство")
    print("8 - Удалить устройство")
    print("    (для 6-8 используется device_ref = первые 10 символов HWID)")
    print("0 - Выход")


def main() -> int:
    _configure_console_utf8()

    print("Старт простого API-бота.")
    print(f"Настройки загружены из .env ({ENV_FILE.resolve()}).\n")

    actions = {
        "1": create_subscription,
        "2": get_subscription,
        "3": delete_subscription,
        "4": recreate_subscription,
        "5": list_devices,
        "6": ban_device,
        "7": unban_device,
        "8": delete_device,
    }

    while True:
        print_menu()
        cmd = input("Выбери действие: ").strip()
        if cmd == "0":
            print("Выход.")
            return 0
        fn = actions.get(cmd)
        if not fn:
            print("Неизвестная команда")
            continue
        try:
            fn()
        except KeyboardInterrupt:
            print("\nОтменено пользователем")
        except Exception:
            if DEBUG_MODE:
                log.exception("Unhandled error")
            print("Операция не выполнена. Проверьте настройки и попробуйте снова.")


if __name__ == "__main__":
    raise SystemExit(main())
