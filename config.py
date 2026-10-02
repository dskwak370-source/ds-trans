"""설정 로딩: st.secrets → 환경 변수 / .env 순서로 읽는다."""

import os

from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-6-astra"

load_dotenv()


def _from_secrets(key: str) -> str | None:
    """st.secrets에서 값을 읽는다. secrets.toml이 없는 로컬 환경에서는 None."""
    try:
        import streamlit as st

        value = st.secrets.get(key)
    except Exception:
        return None
    return str(value) if value else None


def get_setting(key: str, default: str | None = None) -> str | None:
    return _from_secrets(key) or os.getenv(key) or default


def get_api_key() -> str | None:
    return get_setting("OPENAI_API_KEY")


def get_model() -> str:
    return get_setting("OPENAI_MODEL", DEFAULT_MODEL)


def has_api_key() -> bool:
    return bool(get_api_key())


def is_mock_mode() -> bool:
    """MOCK_TRANSLATION=true이면 API를 호출하지 않는 테스트 모드."""
    return (get_setting("MOCK_TRANSLATION") or "").strip().lower() in ("1", "true", "yes")
