"""쇼핑 리스트 데이터 저장소.

아이템 목록을 JSON 파일로 저장하고 불러오며, CRUD 함수를 제공한다.
UI(app.py)는 파일에 직접 접근하지 않고 반드시 이 모듈을 통해서만 데이터를 다룬다.

아이템 구조:
    {
        "id": str,          # uuid4 앞 8자리
        "name": str,        # 아이템 이름 (앞뒤 공백 제거, 최대 MAX_NAME_LENGTH자)
        "quantity": int,    # 수량 (MIN_QUANTITY ~ MAX_QUANTITY)
        "checked": bool,    # 구매 완료 여부
        "created_at": str,  # ISO 형식 생성 시각
    }
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

Item = dict[str, Any]

DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "shopping_list.json"

MIN_QUANTITY = 1
MAX_QUANTITY = 999
MAX_NAME_LENGTH = 100

# 손상된 파일을 백업했을 때 그 경로를 담아 두고, UI가 한 번 꺼내 가서 사용자에게 알린다.
_recovery_notice: Path | None = None


def _ensure_data_file() -> None:
    """data/ 폴더와 JSON 파일이 없으면 생성한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        _atomic_write("[]")


def _atomic_write(text: str) -> None:
    """임시 파일에 먼저 쓴 뒤 교체한다.

    저장 도중 프로세스가 끊겨도 기존 파일이 잘린 채로 남지 않는다.
    Windows에서는 다른 요청이 파일을 읽는 중이면 교체가 잠깐 실패할 수 있어 몇 번 재시도한다.
    """
    tmp = DATA_FILE.with_name(f"{DATA_FILE.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        for attempt in range(5):
            try:
                os.replace(tmp, DATA_FILE)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)


def _backup_corrupt_file() -> None:
    """손상된 데이터 파일을 시각이 붙은 이름으로 보관하고 빈 파일로 다시 시작한다.

    손상 파일을 그대로 두면 다음 저장 때 덮어써져 원본을 영영 잃게 되므로, 먼저 복사본을 남긴다.
    """
    global _recovery_notice
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = DATA_FILE.with_name(f"{DATA_FILE.stem}.corrupt-{stamp}.json")
    shutil.copy2(DATA_FILE, backup)
    _atomic_write("[]")
    _recovery_notice = backup


def pop_recovery_notice() -> Path | None:
    """손상 파일을 백업한 적이 있으면 백업 경로를 한 번만 돌려준다."""
    global _recovery_notice
    notice, _recovery_notice = _recovery_notice, None
    return notice


def clean_name(name: Any) -> str:
    """이름의 앞뒤 공백을 제거하고 최대 길이로 자른다."""
    return str(name or "").strip()[:MAX_NAME_LENGTH]


def clean_quantity(quantity: Any) -> int:
    """수량을 MIN_QUANTITY ~ MAX_QUANTITY 범위의 정수로 보정한다."""
    try:
        value = int(quantity)
    except (TypeError, ValueError):
        return MIN_QUANTITY
    return min(MAX_QUANTITY, max(MIN_QUANTITY, value))


def _normalize(raw: list[Any]) -> tuple[list[Item], bool]:
    """불러온 데이터를 올바른 아이템 구조로 보정한다.

    반환값의 두 번째 요소는 id를 새로 만드는 등 파일에 다시 저장해야 할 변경이 있었는지 여부다.
    (id는 화면 위젯 key로 쓰이므로, 새로 만든 id는 저장해 두어야 다음 로드에서도 같다.)
    """
    items: list[Item] = []
    seen_ids: set[str] = set()
    changed = False
    for entry in raw:
        if not isinstance(entry, dict):
            changed = True
            continue
        name = clean_name(entry.get("name"))
        if not name:
            changed = True
            continue
        item_id = entry.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in seen_ids:
            item_id = uuid.uuid4().hex[:8]
        seen_ids.add(item_id)
        item: Item = {
            "id": item_id,
            "name": name,
            "quantity": clean_quantity(entry.get("quantity")),
            "checked": entry.get("checked") is True,
            "created_at": str(entry.get("created_at") or ""),
        }
        if item != entry:
            changed = True
        items.append(item)
    return items, changed


def load_items() -> list[Item]:
    """JSON 파일에서 아이템 목록을 불러온다.

    - 파일이 없으면 새로 만들고 빈 리스트를 반환한다.
    - 파일이 손상되었으면 백업 파일을 남기고 빈 리스트로 다시 시작한다 (pop_recovery_notice 참고).
    - 항목 일부가 잘못되었으면 보정하거나 건너뛴다.
    - 파일을 읽을 수 없는 경우(OSError)는 예외를 그대로 올린다.
      빈 리스트로 처리하면 다음 저장이 기존 데이터를 덮어쓰기 때문이다.
    """
    _ensure_data_file()
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        _backup_corrupt_file()
        return []
    if not isinstance(data, list):
        _backup_corrupt_file()
        return []
    items, changed = _normalize(data)
    if changed:
        save_items(items)
    return items


def save_items(items: list[Item]) -> None:
    """아이템 목록을 JSON 파일에 저장한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(json.dumps(items, ensure_ascii=False, indent=2))


def add_item(name: str, quantity: int = 1) -> Item | None:
    """새 아이템을 추가하고 추가된 아이템을 반환한다.

    이름은 앞뒤 공백을 제거하며, 비어 있으면 추가하지 않고 None을 반환한다.
    """
    name = clean_name(name)
    if not name:
        return None
    item: Item = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "quantity": clean_quantity(quantity),
        "checked": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    items = load_items()
    items.append(item)
    save_items(items)
    return item


def has_unchecked_name(name: str) -> bool:
    """같은 이름의 미구매 아이템이 이미 있는지 확인한다 (중복 추가 안내용)."""
    name = clean_name(name)
    return any(
        item["name"] == name and not item["checked"] for item in load_items()
    )


def update_item(item_id: str, name: str, quantity: int) -> bool:
    """아이템의 이름과 수량을 수정한다.

    성공하면 True, 해당 id가 없거나 이름이 비어 있으면 False를 반환한다.
    """
    name = clean_name(name)
    if not name:
        return False
    items = load_items()
    for item in items:
        if item["id"] == item_id:
            item["name"] = name
            item["quantity"] = clean_quantity(quantity)
            save_items(items)
            return True
    return False


def set_checked(item_id: str, checked: bool) -> None:
    """아이템의 체크(구매 완료) 상태를 지정한 값으로 저장한다. 없는 id는 무시한다.

    현재 값을 뒤집지 않고 값을 지정하므로, 다른 탭에서 먼저 바뀐 경우에도
    사용자가 화면에서 고른 상태가 그대로 저장된다.
    """
    items = load_items()
    for item in items:
        if item["id"] == item_id:
            if item["checked"] != bool(checked):
                item["checked"] = bool(checked)
                save_items(items)
            return


def toggle_item(item_id: str) -> None:
    """아이템의 체크 상태를 반전한다. 없는 id는 무시한다.

    UI에서는 set_checked를 사용한다 (오래된 화면에서 눌렀을 때 반대로 저장되는 문제 방지).
    """
    items = load_items()
    for item in items:
        if item["id"] == item_id:
            item["checked"] = not item["checked"]
            save_items(items)
            return


def delete_item(item_id: str) -> tuple[Item, int] | None:
    """아이템을 삭제하고 (삭제된 아이템, 원래 위치)를 반환한다. 없는 id는 None."""
    items = load_items()
    for index, item in enumerate(items):
        if item["id"] == item_id:
            del items[index]
            save_items(items)
            return item, index
    return None


def restore_item(item: Item, index: int) -> None:
    """삭제했던 아이템을 원래 위치에 되돌린다. 이미 있는 id면 무시한다."""
    items = load_items()
    if any(existing["id"] == item["id"] for existing in items):
        return
    items.insert(min(max(index, 0), len(items)), item)
    save_items(items)


def clear_checked() -> int:
    """체크된 아이템을 모두 삭제하고 삭제한 개수를 반환한다."""
    items = load_items()
    remaining = [item for item in items if not item["checked"]]
    removed = len(items) - len(remaining)
    if removed:
        save_items(remaining)
    return removed


def clear_all() -> None:
    """모든 아이템을 삭제한다."""
    save_items([])
