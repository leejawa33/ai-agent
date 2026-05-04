def test_chat_returns_answer_and_steps(client):
    response = client.post("/chat", json={"message": "12 곱하기 3 더하기 4 계산해줘"})
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert "steps" in body
    assert isinstance(body["steps"], list)
    assert len(body["steps"]) >= 1
    assert body["steps"][-1]["action"] == "final"


def test_chat_uses_calculator_tool_for_math_query(client):
    response = client.post("/chat", json={"message": "계산해줘"})
    body = response.json()
    tool_steps = [s for s in body["steps"] if s["action"] == "tool"]
    assert any(s["tool"] == "calculator" for s in tool_steps)
    calc_step = next(s for s in tool_steps if s["tool"] == "calculator")
    assert calc_step["observation"] == "40"


def test_chat_finalizes_immediately_for_simple_query(client):
    response = client.post("/chat", json={"message": "그냥 인사"})
    body = response.json()
    assert len(body["steps"]) == 1
    assert body["steps"][0]["action"] == "final"


def test_chat_rejects_invalid_max_steps(client):
    response = client.post("/chat", json={"message": "hi", "max_steps": 0})
    assert response.status_code == 422

    response = client.post("/chat", json={"message": "hi", "max_steps": 100})
    assert response.status_code == 422


def test_chat_requires_message_field(client):
    response = client.post("/chat", json={})
    assert response.status_code == 422
