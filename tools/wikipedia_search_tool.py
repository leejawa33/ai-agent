import requests

class WikipediaSearchTool:
    name = "wikipedia_search"
    description = "위키피디아에서 키워드를 검색해 요약을 반환한다."

    def run(self, tool_input: str) -> str:
        if not tool_input:
            return "ERROR: 검색어가 필요합니다."

        url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + tool_input
        try:
            res = requests.get(url, timeout=5)
            if res.status_code != 200:
                return f"ERROR: 위키피디아에서 '{tool_input}' 문서를 찾지 못했습니다."

            data = res.json()
            extract = data.get("extract")
            if not extract:
                return "ERROR: 요약 정보를 가져오지 못했습니다."

            # 너무 길면 잘라서 Observation으로 넘김
            return extract[:500]

        except Exception as e:
            return f"ERROR: wikipedia request failed ({e})"
