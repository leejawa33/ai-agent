from pathlib import Path


STREAMLIT_APP = Path(__file__).resolve().parent.parent / "streamlit_app.py"


def test_streamlit_app_does_not_import_agent_or_llm():
    """1.4 이후 Streamlit은 FastAPI 클라이언트로만 동작해야 한다.

    LLM/agent/tool/prompt를 직접 임포트하면 백엔드 분리가 깨진 것.
    """
    source = STREAMLIT_APP.read_text(encoding="utf-8")
    forbidden = ["from llm", "from mock_llm", "from react_agent", "from prompt", "from tools"]
    leaks = [token for token in forbidden if token in source]
    assert not leaks, f"Streamlit이 백엔드 모듈을 직접 임포트함: {leaks}"


def test_streamlit_app_uses_http_client():
    source = STREAMLIT_APP.read_text(encoding="utf-8")
    assert "httpx" in source
    assert "/chat/stream" in source
