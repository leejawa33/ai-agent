import os
from urllib.parse import quote

import requests
from pydantic import BaseModel, Field

from .base import tool

# 환경변수로 결과 길이 캡 조정 가능 (Phase 3 토큰 최적화)
WIKI_MAX_CHARS = int(os.getenv("WIKI_MAX_CHARS", "500"))


class WikipediaSearchArgs(BaseModel):
    query: str = Field(..., description="검색할 키워드 (영문 권장, 예: Python_programming_language)")


@tool(WikipediaSearchArgs, name="wikipedia_search", description="위키피디아에서 키워드를 검색해 요약을 반환합니다")
def wikipedia_search(query: str) -> str:
    if not query:
        return "ERROR: 검색어가 필요합니다."

    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(query)
    try:
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return f"ERROR: 위키피디아에서 '{query}' 문서를 찾지 못했습니다."

        data = res.json()
        extract = data.get("extract")
        if not extract:
            return "ERROR: 요약 정보를 가져오지 못했습니다."

        return extract[:WIKI_MAX_CHARS]
    except Exception as e:
        return f"ERROR: wikipedia request failed ({e})"
