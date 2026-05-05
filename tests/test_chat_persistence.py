import json


def test_chat_creates_new_conversation_when_no_id(client):
    response = client.post("/chat", json={"message": "계산해줘"})
    assert response.status_code == 200
    body = response.json()
    assert "conversation_id" in body
    assert isinstance(body["conversation_id"], int)


def test_chat_persists_user_and_assistant_messages(client):
    chat_resp = client.post("/chat", json={"message": "계산해줘"})
    conv_id = chat_resp.json()["conversation_id"]

    conv_resp = client.get(f"/conversations/{conv_id}")
    assert conv_resp.status_code == 200
    conv = conv_resp.json()
    assert conv["id"] == conv_id
    assert conv["title"] == "계산해줘"

    roles = [m["role"] for m in conv["messages"]]
    assert roles == ["user", "assistant"]
    assert conv["messages"][0]["content"] == "계산해줘"
    assert conv["messages"][1]["content"] == "Mock LLM 응답입니다."


def test_chat_with_existing_conversation_id_appends_messages(client):
    first = client.post("/chat", json={"message": "계산해줘"})
    conv_id = first.json()["conversation_id"]

    second = client.post("/chat", json={"message": "그냥 인사", "conversation_id": conv_id})
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conv_id

    conv = client.get(f"/conversations/{conv_id}").json()
    assert len(conv["messages"]) == 4
    assert [m["content"] for m in conv["messages"]] == [
        "계산해줘",
        "Mock LLM 응답입니다.",
        "그냥 인사",
        "Mock LLM 응답입니다.",
    ]


def test_chat_with_unknown_conversation_id_returns_404(client):
    response = client.post("/chat", json={"message": "hi", "conversation_id": 9999})
    assert response.status_code == 404


def test_get_unknown_conversation_returns_404(client):
    response = client.get("/conversations/9999")
    assert response.status_code == 404


def test_chat_stream_emits_conversation_id_first_event(client):
    with client.stream("POST", "/chat/stream?mode=step", json={"message": "계산해줘"}) as response:
        assert response.status_code == 200
        first_event = None
        first_data = None
        for raw in response.iter_lines():
            line = raw if isinstance(raw, str) else raw.decode("utf-8")
            if line.startswith("event:"):
                first_event = line[len("event:"):].strip()
            elif line.startswith("data:") and first_event is not None:
                first_data = line[len("data:"):].strip()
                break

    assert first_event == "conversation_id"
    payload = json.loads(first_data)
    assert "conversation_id" in payload
    assert isinstance(payload["conversation_id"], int)


def test_chat_stream_persists_messages_after_completion(client):
    conv_id = None
    with client.stream("POST", "/chat/stream?mode=step", json={"message": "계산해줘"}) as response:
        for raw in response.iter_lines():
            line = raw if isinstance(raw, str) else raw.decode("utf-8")
            if line.startswith("data:") and conv_id is None:
                payload = json.loads(line[len("data:"):].strip())
                if "conversation_id" in payload:
                    conv_id = payload["conversation_id"]

    assert conv_id is not None
    conv = client.get(f"/conversations/{conv_id}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["content"] == "Mock LLM 응답입니다."
