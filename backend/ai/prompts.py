from pathlib import Path

# 所有 prompt 文件统一存放在 ai/prompts/ 目录下，以 .md 格式维护，便于单独编辑和版本追踪
_DIR = Path(__file__).parent / "prompts"


def _load(name: str) -> str:
    """从 prompts 目录加载指定名称的 .md 文件内容。"""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8")


# 苏格拉底式教学 prompt，对应三种 AI 风格
SOCRATIC_BASE_PROMPT = _load("socratic_base")
SOCRATIC_GENTLE_PROMPT = _load("socratic_gentle")
SOCRATIC_STANDARD_PROMPT = _load("socratic_standard")
SOCRATIC_STRICT_PROMPT = _load("socratic_strict")

# 各场景的独立 prompt
TOPIC_OVERVIEW_PROMPT = _load("topic_overview")  # 主题概览（约 500 字）
NODE_OVERVIEW_PROMPT = _load("node_overview")  # 节点概览（约 180-260 字）
NORMAL_CHAT_PROMPT = _load("normal_chat")  # 普通对话模式
GENERATE_NODES_PROMPT = _load("generate_nodes")  # 生成知识图谱节点
RECOMMEND_TOPICS_PROMPT = _load("recommend_topics")  # 推荐学习主题


def get_socratic_prompt(ai_style: str) -> str:
    """根据用户设置的 AI 风格返回对应的苏格拉底式 prompt。"""
    if ai_style == "温和":
        style_prompt = SOCRATIC_GENTLE_PROMPT
    elif ai_style == "严格":
        style_prompt = SOCRATIC_STRICT_PROMPT
    else:
        style_prompt = SOCRATIC_STANDARD_PROMPT
    return f"{SOCRATIC_BASE_PROMPT}\n\n{style_prompt}"


def build_topic_overview_prompt(topic_title: str) -> str:
    return f"用户想学习「{topic_title}」这个主题。请按要求生成主题概览。"


def build_node_overview_prompt(node_label: str, node_sub: str) -> str:
    return f"当前节点：{node_label}（{node_sub}）。请按要求给出节点概览。"


def build_user_message(node_label: str, node_sub: str, user_input: str) -> str:
    """将节点上下文和用户输入拼接成发给 AI 的 user 消息。"""
    return f"当前学习节点：{node_label}（{node_sub}）\n\n学生说：{user_input}"


def build_recommend_prompt(topics: list[str]) -> str:
    topics_str = "、".join(topics)
    return f"用户当前正在学习：{topics_str}。请推荐接下来适合学习的 3 个主题。"


def build_generate_prompt(topic: str) -> str:
    return f"请为「{topic}」这个主题生成知识图谱节点。"


NORMAL_SUGGESTIONS_PROMPT = _load("suggestions_normal")


def build_normal_suggestions_prompt(context: str | None = None) -> str:
    """新普通对话推荐日常主题，有消息后根据当前会话生成后续提问。"""
    if context is None:
        return NORMAL_SUGGESTIONS_PROMPT
    return _load("suggestions_normal_followup").replace("__CONTEXT__", context)


def build_socratic_suggestions_prompt(context: str, *, has_topic: bool = False) -> str:
    """未绑定主题时推荐学习主题，已绑定时根据当前对话生成追问。"""
    template = "suggestions_socratic" if has_topic else "suggestions_topics"
    return _load(template).replace("__CONTEXT__", context)
