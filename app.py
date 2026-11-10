"""쇼핑 리스트 Streamlit 앱 (UI).

데이터 처리는 storage.py에 맡기고, 이 파일은 화면 구성만 담당한다.

체크/삭제/편집 시작 같은 단순 동작은 위젯 콜백(on_change/on_click)으로 처리한다.
콜백은 스크립트가 다시 실행되기 전에 돌기 때문에, 화면은 항상 바뀐 데이터로 한 번에 그려진다.
입력 검사가 필요한 추가/수정 폼만 본문에서 처리하고 성공 시 st.rerun()을 호출한다.
"""

import html

import streamlit as st

import storage

st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")

EMPTY_NAME_WARNING = "아이템 이름을 입력해 주세요."

# ─── 스타일 (커스텀 CSS는 모두 여기에) ─────────────────
# 색상은 테마 변수/투명도만 사용해 라이트·다크 모드 모두에서 읽히도록 한다.
st.markdown(
    """
    <style>
    /* 상단 여백 축소 */
    .block-container {
        padding-top: 2.5rem;
    }

    /* 카드 사이 간격 축소 */
    [class*="st-key-item-"] {
        padding-top: 0.35rem;
        padding-bottom: 0.35rem;
    }

    /* 아이템 카드: 좁은 화면에서도 체크박스 / 이름 / 버튼을 한 줄로 유지 */
    [class*="st-key-item-"] [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
        gap: 0.25rem;
    }
    [class*="st-key-item-"] [data-testid="stColumn"] {
        min-width: 0 !important;
    }
    [class*="st-key-item-"] [data-testid="stColumn"]:first-child,
    [class*="st-key-item-"] [data-testid="stColumn"]:nth-child(n+3) {
        flex: 0 0 auto !important;
        width: auto !important;
    }
    [class*="st-key-item-"] [data-testid="stColumn"]:nth-child(2) {
        flex: 1 1 auto !important;
    }

    /* 터치하기 쉬운 크기 (PRD 5장) */
    [class*="st-key-item-"] button {
        min-height: 2.5rem;
        min-width: 2.5rem;
    }
    [class*="st-key-item-"] [data-testid="stCheckbox"] label {
        min-height: 2.5rem;
        min-width: 2.5rem;
        align-items: center;
        justify-content: center;
    }

    /* 아이템 이름 */
    .item-name {
        font-size: 1.05rem;
        line-height: 1.4;
        word-break: keep-all;      /* 한글은 띄어쓰기 단위로 줄바꿈 */
        overflow-wrap: anywhere;   /* 띄어쓰기 없는 긴 문자열은 강제 줄바꿈 */
    }
    .item-name.checked {
        text-decoration: line-through;
        opacity: 0.45;
    }

    /* 수량 배지 */
    .qty-badge {
        display: inline-block;
        margin-left: 0.4rem;
        padding: 0.05rem 0.5rem;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 600;
        white-space: nowrap;
        vertical-align: middle;
        /* 글자색은 본문 색을 따라가 라이트·다크 모두 대비 확보 (WCAG AA) */
        color: inherit;
        background: color-mix(in srgb, #2e9e5b 22%, transparent);
    }
    .item-name.checked .qty-badge {
        text-decoration: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── 화면 상태 ─────────────────────────────────────────
st.session_state.setdefault("editing_id", None)  # 편집 중인 아이템 id (한 번에 하나)
st.session_state.setdefault("confirm_clear_all", False)  # 전체 삭제 확인 단계 여부
st.session_state.setdefault("last_deleted", None)  # 되돌리기용 (삭제된 아이템, 원래 위치)

QTY_LABEL = f"수량 ({storage.MIN_QUANTITY}~{storage.MAX_QUANTITY})"
QTY_HELP = f"{storage.MIN_QUANTITY}~{storage.MAX_QUANTITY} 사이로 입력하세요. 범위를 벗어나면 이전 값으로 돌아갑니다."


def notify(message: str, icon: str) -> None:
    """다음 화면 렌더링 때 보여줄 토스트 알림을 예약한다 (st.rerun() 후에도 유지)."""
    st.session_state.toast = (message, icon)


def reset_transient_state() -> None:
    """다른 동작이 일어나면 전체 삭제 확인창과 되돌리기 안내를 닫는다.

    확인창이 열린 채로 남아 있다가 나중에 갑자기 다시 뜨는 문제를 막는다.
    """
    st.session_state.confirm_clear_all = False
    st.session_state.last_deleted = None


# Markdown/LaTeX 문법으로 해석될 수 있는 문자를 HTML 엔티티로 바꾼다.
_MD_ENTITIES = {c: f"&#{ord(c)};" for c in "\\`*_{}[]()#+-.!|~:$"}


def safe_text(text: str) -> str:
    """사용자 입력을 HTML로 출력하기 위해 이스케이프한다 (XSS 및 Markdown 해석 방지)."""
    escaped = html.escape(text, quote=True)
    return "".join(_MD_ENTITIES.get(c, c) for c in escaped)


def md_text(text: str) -> str:
    """사용자 입력을 Markdown 텍스트(토스트 등)에 넣기 위해 특수문자를 백슬래시로 이스케이프한다."""
    return "".join(f"\\{c}" if c in "\\`*_{}[]()#+-.!|~:$<>" else c for c in text)


# ─── 콜백 ──────────────────────────────────────────────
def on_toggle(item_id: str) -> None:
    # 현재 값을 뒤집지 않고, 사용자가 화면에서 고른 값을 그대로 저장한다.
    # (다른 탭에서 이미 바뀐 경우에도 화면과 파일이 어긋나지 않음)
    storage.set_checked(item_id, st.session_state[f"chk_{item_id}"])
    reset_transient_state()


def on_start_edit(item_id: str) -> None:
    st.session_state.editing_id = item_id
    reset_transient_state()


def on_cancel_edit() -> None:
    st.session_state.editing_id = None


def on_delete(item_id: str, name: str) -> None:
    deleted = storage.delete_item(item_id)
    if st.session_state.editing_id == item_id:
        st.session_state.editing_id = None
    reset_transient_state()
    st.session_state.last_deleted = deleted
    notify(f"'{md_text(name)}' 삭제했어요", "🗑️")


def on_undo_delete() -> None:
    if st.session_state.last_deleted:
        item, index = st.session_state.last_deleted
        storage.restore_item(item, index)
        notify(f"'{md_text(item['name'])}' 되돌렸어요", "↩️")
    reset_transient_state()


def on_clear_checked() -> None:
    removed = storage.clear_checked()
    reset_transient_state()
    notify(f"완료 항목 {removed}개를 삭제했어요", "🧹")


def on_ask_clear_all() -> None:
    reset_transient_state()
    st.session_state.confirm_clear_all = True


def on_confirm_clear_all() -> None:
    storage.clear_all()
    st.session_state.editing_id = None
    reset_transient_state()
    notify("리스트를 모두 비웠어요", "🧹")


def on_cancel_clear_all() -> None:
    st.session_state.confirm_clear_all = False


# ─── 데이터 로드 ───────────────────────────────────────
# storage.load_items()가 id·이름·수량·체크 값을 항상 올바른 형태로 보정해서 돌려준다.
items = storage.load_items()
item_ids = {item["id"] for item in items}
if st.session_state.editing_id not in item_ids:
    st.session_state.editing_id = None
if not items:
    st.session_state.confirm_clear_all = False

# 미체크 항목이 위, 체크된 항목이 아래 (같은 그룹 안에서는 추가 순서 유지: sorted는 안정 정렬)
sorted_items = sorted(items, key=lambda item: item["checked"])
total = len(items)
done = sum(1 for item in items if item["checked"])

# 데이터 파일 손상 복구 안내
recovered = storage.pop_recovery_notice()
if recovered:
    st.error(
        f"저장된 데이터 파일이 손상되어 빈 리스트로 다시 시작했어요. "
        f"원래 파일은 `data/{recovered.name}`에 백업해 두었습니다.",
        icon="🚨",
    )

# 예약된 토스트 표시
if "toast" in st.session_state:
    message, icon = st.session_state.pop("toast")
    st.toast(message, icon=icon)

# ─── 헤더 ──────────────────────────────────────────────
st.title("🛒 쇼핑 리스트")
st.caption("살 물건을 적어두고, 장보면서 하나씩 체크하세요.")

# ─── 입력 폼 (PRD 4.1) ─────────────────────────────────
with st.form("add_form", clear_on_submit=True):
    name_col, qty_col, btn_col = st.columns([5, 2, 1.4], vertical_alignment="bottom")
    new_name = name_col.text_input(
        "아이템 이름", placeholder="예: 우유, 계란, 사과", max_chars=storage.MAX_NAME_LENGTH
    )
    new_qty = qty_col.number_input(
        QTY_LABEL, min_value=storage.MIN_QUANTITY, max_value=storage.MAX_QUANTITY,
        value=1, step=1, help=QTY_HELP,
    )
    submitted = btn_col.form_submit_button("추가", type="primary", icon=":material/add:", width="stretch")

if submitted:
    duplicate = storage.has_unchecked_name(new_name)
    added = storage.add_item(new_name, new_qty)
    if added is None:
        st.warning(EMPTY_NAME_WARNING, icon="⚠️")
    else:
        reset_transient_state()
        if duplicate:
            notify(f"'{md_text(added['name'])}'은(는) 이미 목록에 있어서 하나 더 추가했어요", "ℹ️")
        else:
            notify(f"'{md_text(added['name'])}' 추가했어요", "✅")
        st.rerun()

# ─── 진행 상황 (PRD 4.2) ───────────────────────────────
if total:
    st.progress(done / total, text=f"**구매 완료 {done} / 전체 {total}**")
    if done == total:
        st.success("🎉 모두 구매했어요!")
else:
    st.markdown(f"**구매 완료 {done} / 전체 {total}**")

# ─── 목록 (PRD 4.2, 4.3, 4.5) ──────────────────────────
# 삭제 되돌리기 (다른 동작을 하면 사라짐)
if st.session_state.last_deleted:
    deleted_item, _ = st.session_state.last_deleted
    with st.container(border=True, key="undo-bar"):
        msg_col, undo_col = st.columns([4, 1.4], vertical_alignment="center")
        msg_col.markdown(f"🗑️ '{md_text(deleted_item['name'])}' 삭제됨")
        undo_col.button("되돌리기", key="undo_delete", icon="↩️", on_click=on_undo_delete, width="stretch")

if not items:
    st.info("쇼핑 리스트가 비어 있습니다. 위에서 살 물건을 추가해 보세요.", icon="📝")

for item in sorted_items:
    item_id = item["id"]
    name = item["name"]
    quantity = item["quantity"]
    checked = item["checked"]

    if st.session_state.editing_id == item_id:
        # 편집 모드 (PRD 4.3)
        with st.form(f"edit_form_{item_id}"):
            name_col, qty_col = st.columns([3, 1])
            edit_name = name_col.text_input(
                "아이템 이름", value=name, key=f"edit_name_{item_id}",
                max_chars=storage.MAX_NAME_LENGTH,
            )
            edit_qty = qty_col.number_input(
                QTY_LABEL, min_value=storage.MIN_QUANTITY, max_value=storage.MAX_QUANTITY,
                value=quantity, step=1, help=QTY_HELP, key=f"edit_qty_{item_id}",
            )
            save_col, cancel_col = st.columns(2)
            saved = save_col.form_submit_button("저장", type="primary", icon=":material/check:", width="stretch")
            cancel_col.form_submit_button("취소", on_click=on_cancel_edit, width="stretch")

        if saved:
            if storage.update_item(item_id, edit_name, edit_qty):
                st.session_state.editing_id = None
                reset_transient_state()
                notify("수정했어요", "✏️")
                st.rerun()
            else:
                st.warning(EMPTY_NAME_WARNING, icon="⚠️")
        continue

    # 일반 모드: 카드 한 장 = 아이템 하나
    with st.container(border=True, key=f"item-{item_id}"):
        chk_col, name_col, edit_col, del_col = st.columns(
            [0.6, 6, 0.8, 0.8], vertical_alignment="center", gap="small"
        )
        # 위젯 상태를 매번 파일 값으로 맞춘다. 다른 탭에서 바뀐 내용도 다음 렌더링에 반영된다.
        # (클릭 시에는 콜백이 먼저 저장하므로 여기서 덮어써도 사용자의 선택이 유지됨)
        st.session_state[f"chk_{item_id}"] = checked
        chk_col.checkbox(
            f"구매 완료: {name}",
            key=f"chk_{item_id}",
            label_visibility="collapsed",
            on_change=on_toggle,
            args=(item_id,),
        )
        css_class = "item-name checked" if checked else "item-name"
        name_col.markdown(
            f'<span class="{css_class}">{safe_text(name)}'
            f'<span class="qty-badge">× {quantity}</span></span>',
            unsafe_allow_html=True,
        )
        edit_col.button(
            "✏️", key=f"edit_{item_id}", help="수정", type="tertiary",
            on_click=on_start_edit, args=(item_id,),
        )
        del_col.button(
            "🗑️", key=f"del_{item_id}", help="삭제", type="tertiary",
            on_click=on_delete, args=(item_id, name),
        )

# ─── 하단 버튼 (PRD 4.4) ───────────────────────────────
if items:
    st.divider()
    if st.session_state.confirm_clear_all:
        st.warning(f"아이템 {total}개를 모두 삭제할까요? 되돌릴 수 없습니다.", icon="⚠️")
        yes_col, no_col = st.columns(2)
        yes_col.button(
            "모두 삭제", type="primary", key="confirm_clear_all_yes",
            on_click=on_confirm_clear_all, width="stretch",
        )
        no_col.button("취소", key="confirm_clear_all_no", on_click=on_cancel_clear_all, width="stretch")
    else:
        left_col, right_col = st.columns(2)
        left_col.button(
            f"완료 항목 삭제 ({done})",
            key="clear_checked",
            icon="🧹",
            disabled=done == 0,
            on_click=on_clear_checked,
            width="stretch",
        )
        right_col.button(
            "전체 삭제", key="ask_clear_all", icon="🗑️",
            on_click=on_ask_clear_all, width="stretch",
        )
