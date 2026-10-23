import json
from types import SimpleNamespace

from models import ChatMessage, Node, Topic, User
from routers import chat


def test_refresh_sends_visible_suggestions_to_ai_and_filters_repeats(client, monkeypatch):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        content = json.dumps({"suggestions": ["已经显示", "新的话题", "新的话题"]})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(
        chat,
        "get_ai_client",
        lambda _id: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )

    response = client.get(
        "/api/chat/suggestions",
        params=[("mode", "normal"), ("exclude", "已经显示")],
    )

    assert response.status_code == 200
    assert response.json() == {"suggestions": ["新的话题"], "source": "ai"}
    assert "已经显示" in captured["messages"][0]["content"]


def test_ai_failure_marks_static_suggestions_as_fallback(client, monkeypatch):
    def create(**_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        chat,
        "get_ai_client",
        lambda _id: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )

    response = client.get("/api/chat/suggestions", params={"mode": "normal"})

    assert response.status_code == 200
    assert response.json()["source"] == "fallback"
    assert len(response.json()["suggestions"]) == 12


def mock_suggestions(monkeypatch, *, fail=False):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        if fail:
            raise RuntimeError("model unavailable")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"suggestions": ["检索结果如何影响生成？"]}')
                )
            ]
        )

    monkeypatch.setattr(
        chat,
        "get_ai_client",
        lambda _id: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    return captured


def learning_topic(db_session, auth_user):
    topic = Topic(user_id=auth_user.id, title="RAG")
    db_session.add(topic)
    db_session.flush()
    db_session.add(
        Node(
            topic_id=topic.id,
            node_key="rag-retrieval",
            label="检索器",
            sub="向量检索",
            state="available",
        )
    )
    db_session.commit()
    return topic


def test_new_dialogue_recommends_topics_even_with_existing_learning_nodes(
    client, db_session, auth_user, monkeypatch
):
    learning_topic(db_session, auth_user)
    captured = mock_suggestions(monkeypatch)

    response = client.get("/api/chat/suggestions", params={"mode": "socratic"})

    assert response.status_code == 200
    prompt = captured["messages"][0]["content"]
    assert "尚未绑定主题的新学习对话" in prompt
    assert "具体学习主题" in prompt
    assert "RAG" in prompt
    assert "检索器" not in prompt


def test_topic_dialogue_uses_only_its_topic_node_and_recent_chat(
    client, db_session, auth_user, monkeypatch
):
    topic = learning_topic(db_session, auth_user)
    other_topic = Topic(user_id=auth_user.id, title="Python")
    other_user = User(
        username="other-suggestions", email="other-suggestions@example.test", hashed_password="hash"
    )
    db_session.add_all([other_topic, other_user])
    db_session.flush()
    base = dict(
        user_id=auth_user.id,
        topic_id=topic.id,
        session_id="rag-session",
        node_key="rag-retrieval",
        mode="socratic",
    )
    db_session.add_all(
        [
            ChatMessage(**base, role="user", content="旧消息不应出现"),
            *[
                ChatMessage(
                    **base,
                    role="ai" if index % 2 else "user",
                    content=f"当前消息{index}：" + "文" * 1000,
                )
                for index in range(6)
            ],
            ChatMessage(
                **{**base, "session_id": "another-session"}, role="user", content="其他会话秘密"
            ),
            ChatMessage(
                **{**base, "topic_id": other_topic.id}, role="user", content="其他主题秘密"
            ),
            ChatMessage(**{**base, "user_id": other_user.id}, role="user", content="其他用户秘密"),
            ChatMessage(**{**base, "mode": "normal"}, role="user", content="普通对话秘密"),
            ChatMessage(**base, role="ai", content="诊断内容", message_type="agent_step"),
        ]
    )
    db_session.commit()
    captured = mock_suggestions(monkeypatch)

    response = client.get(
        "/api/chat/suggestions",
        params={
            "mode": "socratic",
            "topic_id": topic.id,
            "session_id": "rag-session",
            "node_key": "rag-retrieval",
        },
    )

    assert response.status_code == 200
    prompt = captured["messages"][0]["content"]
    assert '"当前主题": "RAG"' in prompt
    assert '"名称": "检索器", "说明": "向量检索"' in prompt
    assert "生成12个简短且不同的追问问题" in prompt
    for excluded in [
        "旧消息不应出现",
        "其他会话秘密",
        "其他主题秘密",
        "其他用户秘密",
        "普通对话秘密",
        "诊断内容",
    ]:
        assert excluded not in prompt
    assert prompt.count('"角色"') == 6
    assert "文" * 800 in prompt
    assert "文" * 801 not in prompt


def test_topic_dialogue_without_node_or_history_still_recommends_questions(
    client, db_session, auth_user, monkeypatch
):
    topic = learning_topic(db_session, auth_user)
    captured = mock_suggestions(monkeypatch)

    response = client.get("/api/chat/suggestions", params={"topic_id": topic.id})

    assert response.status_code == 200
    prompt = captured["messages"][0]["content"]
    assert '"当前主题": "RAG"' in prompt
    assert "追问问题" in prompt
    assert '"当前节点"' not in prompt


def test_topic_fallback_stays_on_current_node_and_excludes_visible_questions(
    client, db_session, auth_user, monkeypatch
):
    topic = learning_topic(db_session, auth_user)
    mock_suggestions(monkeypatch, fail=True)
    excluded = "检索器的核心原理是什么？"

    response = client.get(
        "/api/chat/suggestions",
        params={"topic_id": topic.id, "node_key": "rag-retrieval", "exclude": excluded},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["source"] == "fallback"
    assert "检索器有什么实际用途？" in result["suggestions"]
    assert excluded not in result["suggestions"]
    assert all(value.endswith("？") for value in result["suggestions"])
    assert "我想学 Python" not in result["suggestions"]


def test_suggestions_reject_other_users_topics_and_nodes_from_other_topics(
    client, db_session, auth_user, monkeypatch
):
    topic = learning_topic(db_session, auth_user)
    other_user = User(
        username="private-suggestions",
        email="private-suggestions@example.test",
        hashed_password="hash",
    )
    db_session.add(other_user)
    db_session.flush()
    private_topic = Topic(user_id=other_user.id, title="私有主题")
    db_session.add(private_topic)
    db_session.flush()
    db_session.add(Node(topic_id=private_topic.id, node_key="private-node", label="私有节点"))
    db_session.commit()
    captured = mock_suggestions(monkeypatch)

    assert (
        client.get("/api/chat/suggestions", params={"topic_id": private_topic.id}).status_code
        == 404
    )
    assert (
        client.get(
            "/api/chat/suggestions", params={"topic_id": topic.id, "node_key": "private-node"}
        ).status_code
        == 404
    )
    assert captured == {}


def normal_conversation(db_session, auth_user):
    base = dict(user_id=auth_user.id, session_id="beach-session", node_key="normal", mode="normal")
    db_session.add_all(
        [
            ChatMessage(**base, role="user", content="周末想去海边"),
            ChatMessage(**base, role="ai", content="可以去海边露营。"),
        ]
    )
    db_session.commit()


def test_new_normal_dialogue_recommends_everyday_topics_without_other_conversations(
    client, db_session, auth_user, monkeypatch
):
    normal_conversation(db_session, auth_user)
    captured = mock_suggestions(monkeypatch)
    for params in [{"mode": "normal"}, {"mode": "normal", "session_id": "new-normal-session"}]:
        response = client.get("/api/chat/suggestions", params=params)
        assert response.status_code == 200
        prompt = captured["messages"][0]["content"]
        assert "尚未开始聊天的新普通对话" in prompt
        assert "日常对话主题" in prompt
        assert "周末想去海边" not in prompt
        assert "可以去海边露营" not in prompt


def test_normal_followups_use_only_recent_messages_in_the_current_users_session(
    client, db_session, auth_user, monkeypatch
):
    other_user = User(
        username="normal-other", email="normal-other@example.test", hashed_password="hash"
    )
    db_session.add(other_user)
    db_session.flush()
    base = dict(user_id=auth_user.id, session_id="beach-session", node_key="normal", mode="normal")
    db_session.add_all(
        [
            ChatMessage(**base, role="user", content="过早的聊天内容"),
            *[
                ChatMessage(
                    **base,
                    role="user" if index % 2 == 0 else "ai",
                    content="文" * 1000 + f"海边露营细节{index}",
                )
                for index in range(6)
            ],
            ChatMessage(
                **{**base, "session_id": "dinner-session"},
                role="user",
                content="其他聊天的晚餐计划",
            ),
            ChatMessage(
                **{**base, "user_id": other_user.id}, role="user", content="其他用户的私密内容"
            ),
            ChatMessage(**{**base, "mode": "socratic"}, role="ai", content="学习对话的检索器"),
            ChatMessage(**base, role="ai", content="诊断流程内容", message_type="agent_step"),
        ]
    )
    db_session.commit()
    captured = mock_suggestions(monkeypatch)

    response = client.get(
        "/api/chat/suggestions", params={"mode": "normal", "session_id": "beach-session"}
    )

    assert response.status_code == 200
    prompt = captured["messages"][0]["content"]
    assert "后续对话建议" in prompt
    context = json.loads(prompt.split("\n", 1)[1].split("\n\n", 1)[0])
    recent = context["最近对话"]
    assert len(recent) == 6
    assert all(len(message["内容"]) == 800 for message in recent)
    assert [message["内容"][-7:] for message in recent] == [
        f"海边露营细节{index}" for index in range(6)
    ]
    assert [message["角色"] for message in recent] == ["user", "ai"] * 3
    for excluded in [
        "过早的聊天内容",
        "其他聊天的晚餐计划",
        "其他用户的私密内容",
        "学习对话的检索器",
        "诊断流程内容",
    ]:
        assert excluded not in prompt


def test_normal_followup_fallback_continues_the_conversation_and_filters_exclusions(
    client, db_session, auth_user, monkeypatch
):
    normal_conversation(db_session, auth_user)
    mock_suggestions(monkeypatch, fail=True)
    excluded = "能展开说说刚才的内容吗？"

    response = client.get(
        "/api/chat/suggestions",
        params={"mode": "normal", "session_id": "beach-session", "exclude": excluded},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["source"] == "fallback"
    assert "能结合我的情况举个例子吗？" in result["suggestions"]
    assert excluded not in result["suggestions"]
    assert "今天天气怎么样" not in result["suggestions"]
    assert "推荐一部电影" not in result["suggestions"]
    assert all(value.endswith("？") for value in result["suggestions"])


def test_other_users_normal_session_is_not_used_as_suggestion_context(
    client, db_session, auth_user, monkeypatch
):
    other_user = User(
        username="private-normal", email="private-normal@example.test", hashed_password="hash"
    )
    db_session.add(other_user)
    db_session.flush()
    db_session.add(
        ChatMessage(
            user_id=other_user.id,
            session_id="private-normal-session",
            node_key="normal",
            mode="normal",
            role="user",
            content="他人的私密话题",
        )
    )
    db_session.commit()
    captured = mock_suggestions(monkeypatch)

    response = client.get(
        "/api/chat/suggestions", params={"mode": "normal", "session_id": "private-normal-session"}
    )

    assert response.status_code == 200
    prompt = captured["messages"][0]["content"]
    assert "尚未开始聊天的新普通对话" in prompt
    assert "他人的私密话题" not in prompt
