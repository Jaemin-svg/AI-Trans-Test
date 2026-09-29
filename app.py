"""AI 번역기 Streamlit 앱."""

import re

import streamlit as st

from translator import (
    LANGUAGES,
    RateLimitError,
    TranslationError,
    create_client,
    get_api_key,
    get_model,
    translate,
)

MAX_CHARS = 2000
MAX_HISTORY = 10
PREVIEW_CHARS = 30

# Streamlit 라벨/캡션은 마크다운(굵게, 링크, :color[] 등)을 해석하므로 사용자 텍스트는 이스케이프한다.
MARKDOWN_SPECIAL = set("\\`*_{}[]()<>#+-.!|~:$")
AUTOLINK_PATTERN = re.compile(r"://|@|www\.", re.IGNORECASE)

st.set_page_config(page_title="AI 번역기", page_icon="🌐", layout="wide")

# 세션 상태 기본값
st.session_state.setdefault("last_result", None)  # {"source": str, "result": dict}
st.session_state.setdefault("history", [])  # 최신순 [{"source", "result"}]
st.session_state.setdefault("busy", False)
st.session_state.setdefault("notice", None)  # ("error" | "warning", 메시지)


@st.cache_resource
def get_client():
    return create_client()


@st.cache_data(show_spinner=False)
def cached_translate(text: str) -> dict:
    # 예외는 캐싱되지 않으므로 실패한 요청은 다음에 다시 시도된다.
    return translate(get_client(), text)


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    """사용자 텍스트를 한 줄로 줄이고 마크다운으로 해석되지 않게 만든다. 자른 뒤에 이스케이프해야 문법이 깨지지 않는다."""
    line = " ".join(text.split())
    if len(line) > limit:
        line = line[:limit] + "…"
    # GFM은 이스케이프와 상관없이 URL/이메일을 자동 링크로 만들므로 폭 없는 공백으로 끊는다.
    line = AUTOLINK_PATTERN.sub(lambda m: m.group(0)[:-1] + "​" + m.group(0)[-1], line)
    return "".join("\\" + ch if ch in MARKDOWN_SPECIAL else ch for ch in line)


def start_translation():
    st.session_state.busy = True
    st.session_state.notice = None


def run_translation():
    text = st.session_state.source_text.strip()
    if not text:
        st.session_state.notice = ("warning", "번역할 텍스트를 입력해주세요.")
        return

    try:
        with st.spinner("번역 중..."):
            result = cached_translate(text)
    except RateLimitError as e:
        st.session_state.notice = ("warning", str(e))
        return
    except TranslationError as e:
        st.session_state.notice = ("error", str(e))
        return
    except Exception:
        # 예상하지 못한 오류도 화면을 깨뜨리지 않고 안내만 한다.
        # (Streamlit의 rerun/stop 신호는 BaseException이라 여기서 잡히지 않는다.)
        st.session_state.notice = ("error", "번역 중 예상하지 못한 오류가 발생했습니다. 다시 시도해주세요.")
        return

    entry = {"source": text, "result": result}
    st.session_state.last_result = entry
    # 같은 원문은 기존 기록을 지우고 맨 앞으로 올린다.
    history = [item for item in st.session_state.history if item["source"] != text]
    history.insert(0, entry)
    st.session_state.history = history[:MAX_HISTORY]


# 결과 칸(st.code)의 글꼴을 본문 글꼴로 바꿔 번역문이 읽기 편하게 한다. 색은 지정하지 않고 테마를 따른다.
# 사용자 입력/번역 결과는 이 방식으로 렌더링하지 않는다.
CUSTOM_CSS = """
<style>
.stCode pre {
    font-family: inherit !important;
}
.stCode code {
    font-family: inherit !important;
    font-size: 1rem !important;
    line-height: 1.6 !important;
}
/* 오른쪽 위 복사 아이콘이 첫 줄 글자를 가리지 않도록 여백 확보 */
.stCode pre {
    padding-right: 2.75rem !important;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# 사이드바
api_key_set = get_api_key() is not None
with st.sidebar:
    st.subheader("⚙️ 설정")
    st.markdown(f"**모델** · `{get_model()}`")
    st.markdown(f"**API 키** · {'✅ 설정됨' if api_key_set else '❌ 미설정'}")

    st.divider()
    st.subheader("📖 사용법")
    st.markdown(
        "1. 번역할 텍스트를 입력하세요.\n"
        "2. **번역하기**를 누르세요.\n"
        "3. 결과 칸 오른쪽 위 복사 아이콘으로 복사할 수 있어요."
    )

    st.divider()
    st.subheader("🕘 이번 세션 번역 기록")
    if not st.session_state.history:
        st.caption("아직 번역 기록이 없습니다.")
    for item in st.session_state.history:
        with st.expander(preview(item["source"])):
            st.text(item["source"])
            for code, label in LANGUAGES.items():
                st.caption(label)
                st.text(item["result"][code])

st.title("🌐 AI 번역기")
st.caption("입력한 텍스트를 영어 · 일본어 · 베트남어로 한 번에 번역합니다.")

if not api_key_set:
    st.error(
        "OPENAI_API_KEY가 설정되지 않았습니다. "
        "프로젝트 폴더의 .env 파일에 `OPENAI_API_KEY=sk-...` 를 추가한 뒤 앱을 다시 실행해주세요."
    )
    st.stop()

st.text_area(
    "번역할 텍스트",
    key="source_text",
    max_chars=MAX_CHARS,
    height=160,
    placeholder="예: 내일 회의는 오후 3시에 시작합니다.",
)

# 글자 수는 입력창 오른쪽 아래의 Streamlit 기본 카운터가 입력 중에 실시간으로 보여준다.
# (직접 만든 카운터는 입력창을 벗어나야 갱신돼 기본 카운터와 숫자가 달랐다.)
st.caption(f"최대 {MAX_CHARS:,}자까지 입력할 수 있어요. {MAX_CHARS:,}자를 넘는 글은 붙여넣어도 입력되지 않아요.")

st.button(
    "번역하기",
    type="primary",
    icon="🌐",
    on_click=start_translation,
    disabled=st.session_state.busy,
)

if st.session_state.busy:
    # busy가 남아 있으면 버튼이 계속 잠기고, 다음 rerun에서 번역이 저절로 다시 실행된다.
    try:
        run_translation()
    finally:
        st.session_state.busy = False
    st.rerun()

if st.session_state.notice:
    level, message = st.session_state.notice
    getattr(st, level)(message)

st.subheader("번역 결과")
last = st.session_state.last_result
if last:
    # 입력을 바꾸거나 새 번역이 실패해도 이전 결과가 남으므로, 어떤 원문의 결과인지 표시한다.
    st.caption(f"원문: {preview(last['source'], limit=80)}")
    for col, (code, label) in zip(st.columns(len(LANGUAGES)), LANGUAGES.items()):
        with col, st.container(border=True):
            st.markdown(f"**{label}**")
            st.code(last["result"][code], language=None, wrap_lines=True)
else:
    st.info("번역할 텍스트를 입력하고 **번역하기**를 누르면 여기에 결과가 표시됩니다.")
