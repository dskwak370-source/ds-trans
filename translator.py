"""OpenAI API를 이용한 번역 로직. Streamlit에 의존하지 않는다."""

import json
import time

import openai
from openai import OpenAI

import config

LANGUAGES = {
    "en": "English",
    "ja": "Japanese",
    "vi": "Vietnamese",
}

TONES = {
    "default": "Use a natural, neutral tone.",
    "formal": "Use a formal, polite tone suitable for business communication.",
    "casual": "Use a friendly, casual tone suitable for conversation between friends.",
}

MAX_INPUT_CHARS = 5000
MAX_COMPLETION_TOKENS = 8000
REQUEST_TIMEOUT = 60
MAX_RETRIES = 2
RETRY_BASE_DELAY = 1.0
MOCK_DELAY = 1.0

_RULES = (
    "Rules:\n"
    "- Detect the source language automatically.\n"
    "- If the text is already in the target language, return it lightly polished.\n"
    "- Preserve line breaks, paragraphs, lists and other formatting.\n"
    "- Keep proper nouns, URLs, code, and numbers as they are.\n"
    "- Output only the translation: no explanations, notes, or surrounding quotes."
)

_sleep = time.sleep  # 테스트에서 교체할 수 있도록 분리


class TranslationError(Exception):
    """사용자에게 보여줄 한국어 메시지를 담은 번역 오류."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AuthError(TranslationError):
    pass


class RateLimitExceeded(TranslationError):
    pass


class NetworkError(TranslationError):
    pass


class TranslationTimeout(TranslationError):
    pass


class ModelNotFound(TranslationError):
    pass


class APIRequestError(TranslationError):
    pass


def build_json_prompt(target_langs: list[str], tone: str) -> str:
    targets = ", ".join(f'"{lang}" ({LANGUAGES[lang]})' for lang in target_langs)
    return (
        "You are a professional translator. "
        f"Translate the user's text into each of these languages: {targets}.\n"
        f"{TONES[tone]}\n"
        f"{_RULES}\n"
        "Respond with a JSON object whose keys are the language codes and whose values "
        "are the translations, e.g. "
        + json.dumps({lang: "..." for lang in target_langs})
    )


def build_single_prompt(lang: str, tone: str) -> str:
    return (
        "You are a professional translator. "
        f"Translate the user's text into {LANGUAGES[lang]}.\n"
        f"{TONES[tone]}\n"
        f"{_RULES}"
    )


def get_client() -> OpenAI:
    # 재시도는 _request에서 직접 처리하므로 SDK 자체 재시도는 끈다.
    return OpenAI(api_key=config.get_api_key(), timeout=REQUEST_TIMEOUT, max_retries=0)


def _convert_error(error: Exception) -> TranslationError:
    """OpenAI SDK 예외를 한국어 메시지의 TranslationError로 변환한다. 원본 메시지는 키가 섞일 수 있어 노출하지 않는다."""
    if isinstance(error, openai.AuthenticationError):
        return AuthError("API 키가 올바르지 않습니다. OPENAI_API_KEY 설정을 확인하세요.")
    if isinstance(error, openai.RateLimitError):
        return RateLimitExceeded("요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
    if isinstance(error, openai.APITimeoutError):
        return TranslationTimeout("응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.")
    if isinstance(error, openai.APIConnectionError):
        return NetworkError("OpenAI 서버에 연결할 수 없습니다. 네트워크 상태를 확인하세요.")
    if isinstance(error, openai.NotFoundError):
        return ModelNotFound(
            f"모델 '{config.get_model()}'을(를) 사용할 수 없습니다. OPENAI_MODEL 설정을 확인하세요."
        )
    if isinstance(error, openai.APIStatusError):
        return APIRequestError(f"번역 요청이 실패했습니다. (HTTP {error.status_code})")
    return APIRequestError("번역 중 알 수 없는 오류가 발생했습니다.")


def _is_retryable(error: Exception) -> bool:
    return isinstance(
        error,
        (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError),
    )


def _request(client: OpenAI, messages: list[dict], json_mode: bool = False) -> str:
    kwargs = {
        "model": config.get_model(),
        "messages": messages,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(**kwargs)
        except openai.OpenAIError as error:
            if attempt < MAX_RETRIES and _is_retryable(error):
                _sleep(RETRY_BASE_DELAY * 2**attempt)
                continue
            raise _convert_error(error) from error
        if not response.choices:
            raise APIRequestError("번역 결과를 받지 못했습니다. 잠시 후 다시 시도하세요.")
        return (response.choices[0].message.content or "").strip()
    raise AssertionError("unreachable")


def parse_json_result(content: str, target_langs: list[str]) -> dict[str, str]:
    """JSON 응답에서 대상 언어의 번역만 추출한다. 형식이 맞지 않으면 빈 dict."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        lang: data[lang].strip()
        for lang in target_langs
        if isinstance(data.get(lang), str) and data[lang].strip()
    }


def translate_one(client: OpenAI, text: str, lang: str, tone: str = "default") -> str:
    messages = [
        {"role": "system", "content": build_single_prompt(lang, tone)},
        {"role": "user", "content": text},
    ]
    return _request(client, messages)


def _mock_translate(text: str, target_langs: list[str]) -> dict[str, str]:
    _sleep(MOCK_DELAY)
    return {lang: f"[{lang.upper()}] {text}" for lang in target_langs}


def translate(text: str, target_langs: list[str], tone: str = "default") -> dict[str, str]:
    """text를 target_langs(en/ja/vi) 각각으로 번역해 {언어코드: 번역문}으로 반환한다.

    한 번의 JSON 호출로 모든 언어를 받고, 파싱 실패나 누락된 언어만 개별 호출로 대체한다.
    """
    if not text.strip():
        raise ValueError("번역할 글이 비어 있습니다.")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"입력은 최대 {MAX_INPUT_CHARS}자까지 가능합니다.")
    unknown = [lang for lang in target_langs if lang not in LANGUAGES]
    if unknown or not target_langs:
        raise ValueError(f"지원하지 않는 대상 언어입니다: {unknown or '없음'}")
    if tone not in TONES:
        raise ValueError(f"지원하지 않는 톤입니다: {tone}")

    if config.is_mock_mode():
        return _mock_translate(text, target_langs)

    client = get_client()
    messages = [
        {"role": "system", "content": build_json_prompt(target_langs, tone)},
        {"role": "user", "content": text},
    ]
    results = parse_json_result(_request(client, messages, json_mode=True), target_langs)

    for lang in target_langs:
        if lang not in results:
            results[lang] = translate_one(client, text, lang, tone)

    return {lang: results[lang] for lang in target_langs}
