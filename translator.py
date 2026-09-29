"""OpenAI ChatGPT를 사용해 텍스트를 영어/일본어/베트남어로 번역하는 모듈."""

import json
import os

import openai
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_MODEL = "gpt-4o-mini"
# 2,000자 가까운 입력은 3개 언어 응답 생성에 30초 가까이 걸린다(실측 약 27.5초). 여유 있게 잡는다.
REQUEST_TIMEOUT = 120  # 초

# 대상 언어: 코드 -> 화면 표시 라벨 (언어 추가 시 여기만 수정)
LANGUAGES = {
    "en": "🇺🇸 English",
    "ja": "🇯🇵 日本語",
    "vi": "🇻🇳 Tiếng Việt",
}

SYSTEM_PROMPT = (
    "You are a professional translator. "
    "Translate the user's text into English (en), Japanese (ja), and Vietnamese (vi). "
    "Preserve the original meaning, tone, line breaks, and formatting. "
    "If the text is already written in one of these target languages, return it as-is "
    "for that key, only correcting obvious typos or grammar mistakes. "
    'Respond ONLY with a JSON object with keys "en", "ja", "vi".'
)


class TranslationError(Exception):
    """번역 실패의 기본 예외. 메시지는 화면에 그대로 표시할 수 있는 한국어 문장이다."""


class MissingAPIKeyError(TranslationError):
    pass


class InvalidAPIKeyError(TranslationError):
    pass


class NetworkError(TranslationError):
    pass


class RateLimitError(TranslationError):
    pass


class ResponseParseError(TranslationError):
    pass


def get_api_key() -> str | None:
    return (os.getenv("OPENAI_API_KEY") or "").strip() or None


def get_model() -> str:
    return os.getenv("OPENAI_MODEL") or DEFAULT_MODEL


def create_client() -> OpenAI:
    api_key = get_api_key()
    if not api_key:
        raise MissingAPIKeyError(".env 파일에 OPENAI_API_KEY를 설정해주세요.")
    return OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT, max_retries=1)


def _parse_response(content: str | None) -> dict:
    try:
        data = json.loads(content or "")
    except json.JSONDecodeError as e:
        raise ResponseParseError("번역 결과를 해석하지 못했습니다. 다시 시도해주세요.") from e

    if not isinstance(data, dict) or not all(isinstance(data.get(code), str) for code in LANGUAGES):
        raise ResponseParseError("번역 결과를 해석하지 못했습니다. 다시 시도해주세요.")
    return {code: data[code] for code in LANGUAGES}


def translate(client: OpenAI, text: str) -> dict:
    """텍스트를 3개 언어로 번역한다. API는 1회만 호출한다.

    반환 예: {"en": "...", "ja": "...", "vi": "..."}
    실패 시 TranslationError 하위 예외를 발생시킨다.
    """
    try:
        response = client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except openai.AuthenticationError as e:
        raise InvalidAPIKeyError("API 키가 올바르지 않습니다. .env 파일을 확인해주세요.") from e
    except openai.RateLimitError as e:
        if getattr(e, "code", None) == "insufficient_quota":
            raise RateLimitError("OpenAI 크레딧이 부족합니다. 결제/사용량 설정을 확인해주세요.") from e
        raise RateLimitError("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.") from e
    except openai.APITimeoutError as e:
        raise NetworkError("응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.") from e
    except openai.APIConnectionError as e:
        raise NetworkError("OpenAI 서버에 연결하지 못했습니다. 네트워크 상태를 확인해주세요.") from e
    except openai.APIError as e:
        raise TranslationError(f"번역 중 오류가 발생했습니다: {e.message}") from e

    return _parse_response(response.choices[0].message.content)
