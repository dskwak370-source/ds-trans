import streamlit as st

import config
from translator import LANGUAGES, MAX_INPUT_CHARS, TONES, TranslationError, translate

LANGUAGE_LABELS = {
    "en": "English",
    "ja": "日本語",
    "vi": "Tiếng Việt",
}

TONE_LABELS = {
    "default": "기본",
    "formal": "격식체",
    "casual": "친근체",
}


def build_download_text(source: str, results: dict[str, str]) -> str:
    sections = [f"[원문]\n{source}"]
    sections += [f"[{LANGUAGE_LABELS[lang]}]\n{translated}" for lang, translated in results.items()]
    return "\n\n".join(sections) + "\n"


def render_sidebar(mock_mode: bool, has_key: bool) -> None:
    with st.sidebar:
        st.header("설정")
        if mock_mode:
            st.badge("테스트 모드", icon="🧪", color="orange")
            st.caption("MOCK_TRANSLATION이 켜져 있어 실제 API를 호출하지 않습니다.")

        st.markdown(f"**모델**  \n`{config.get_model()}`")
        if has_key:
            st.markdown("**API 키**  \n✅ 설정됨")
        else:
            st.markdown("**API 키**  \n❌ 미설정")

        st.divider()
        st.subheader("사용법")
        st.markdown(
            "1. 번역할 글을 입력합니다.\n"
            "2. 대상 언어와 톤을 고릅니다.\n"
            "3. **번역하기**를 누릅니다.\n"
            "4. 결과 오른쪽 위의 버튼으로 복사하거나, 전체 결과를 내려받습니다."
        )


st.set_page_config(page_title="다국어 번역기", page_icon="🌐", layout="centered")

# 한국어 제목·안내문이 글자 단위로 끊기지 않게 단어 단위 줄바꿈 (번역 결과 코드 블록에는 적용하지 않음)
st.markdown(
    "<style>h1, h2, h3, [data-testid='stCaptionContainer'], [data-testid='stMarkdownContainer'] p"
    " { word-break: keep-all; }</style>",
    unsafe_allow_html=True,
)

mock_mode = config.is_mock_mode()
has_key = config.has_api_key()
ready = mock_mode or has_key

render_sidebar(mock_mode, has_key)

st.title("🌐 다국어 번역기")
st.caption("입력한 글을 영어 · 일본어 · 베트남어로 번역합니다")

if not ready:
    st.error(
        "OPENAI_API_KEY가 설정되지 않았습니다. "
        "로컬에서는 `.env` 파일에, Streamlit Cloud에서는 App settings → Secrets에 키를 등록하세요.",
        icon="🔑",
    )

with st.container(border=True):
    # max_chars를 쓰면 한도를 넘는 붙여넣기가 잘리지 않고 통째로 무시되므로, 길이 제한은 직접 검사한다.
    text = st.text_area(
        "번역할 글",
        height=220,
        placeholder="번역할 글을 입력하세요. 원문 언어는 자동으로 감지합니다.",
    )
    too_long = len(text) > MAX_INPUT_CHARS
    counter = f"{len(text):,} / {MAX_INPUT_CHARS:,}자"
    st.caption(f":red[**{counter}**]" if too_long else counter, text_alignment="right")
    if too_long:
        st.warning(
            f"입력은 최대 {MAX_INPUT_CHARS:,}자까지 번역할 수 있습니다. "
            f"{len(text) - MAX_INPUT_CHARS:,}자를 줄여 주세요.",
            icon="📏",
        )

    lang_col, tone_col = st.columns([3, 2], vertical_alignment="bottom")
    selected = lang_col.pills(
        "대상 언어",
        options=list(LANGUAGES),
        format_func=LANGUAGE_LABELS.get,
        selection_mode="multi",
        default=list(LANGUAGES),
        key="target_langs",
    )
    tone = tone_col.segmented_control(
        "톤",
        options=list(TONES),
        format_func=TONE_LABELS.get,
        default="default",
        required=True,
        key="tone",
    )

    clicked = st.button(
        "번역하기",
        type="primary",
        icon=":material/translate:",
        width="stretch",
        disabled=not ready or too_long,
    )

# pills는 선택한 순서대로 값을 돌려주므로 화면 표시 순서(en, ja, vi)로 맞춘다.
target_langs = [lang for lang in LANGUAGES if lang in (selected or [])]

if clicked:
    if not text.strip():
        st.warning("번역할 글을 입력하세요.", icon="✏️")
    elif not target_langs:
        st.warning("대상 언어를 하나 이상 선택하세요.", icon="🌐")
    elif too_long:
        pass  # 위에서 이미 경고를 표시함
    else:
        try:
            with st.spinner("번역 중입니다..."):
                results = translate(text, target_langs, tone)
        except TranslationError as error:
            st.session_state.pop("translation", None)
            st.error(error.message, icon="🚨")
        else:
            st.session_state["translation"] = {"source": text, "results": results}
            st.success("번역이 완료되었습니다.", icon="✅")

translation = st.session_state.get("translation")
if translation:
    results = translation["results"]
    with st.container(border=True):
        st.subheader("번역 결과")
        tabs = st.tabs([LANGUAGE_LABELS[lang] for lang in results])
        for tab, (lang, translated) in zip(tabs, results.items()):
            with tab:
                st.code(translated, language=None, wrap_lines=True)

        st.download_button(
            "결과 전체 다운로드 (.txt)",
            data=build_download_text(translation["source"], results),
            file_name="translation.txt",
            mime="text/plain",
            icon=":material/download:",
            width="stretch",
        )
