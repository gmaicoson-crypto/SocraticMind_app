from functools import lru_cache

from openai import OpenAI

from core.config import LLMProfile, settings


_custom_profiles: dict[str, tuple[LLMProfile, int]] = {}


def register_custom_profile(profile: LLMProfile, user_id: int) -> None:
    """将用户模型放入进程缓存，后续 Agent 阶段可按 run 中的模型 ID 复用。"""
    _custom_profiles[profile.id] = (profile, user_id)


def remove_custom_profile(profile_id: str) -> None:
    _custom_profiles.pop(profile_id, None)


def resolve_llm_profile(model_id: str | None = None, user_id: int | None = None) -> LLMProfile:
    """根据前端传入的 profile id 解析配置；空值使用服务端默认配置。"""
    profiles = settings.llm_profiles
    selected_id = model_id or settings.default_llm_profile_id
    custom_entry = _custom_profiles.get(selected_id)
    if custom_entry is not None and (user_id is None or custom_entry[1] == user_id):
        return custom_entry[0]
    for profile in profiles:
        if profile.id == selected_id or profile.model == selected_id:
            return profile
    name_matches = [profile for profile in profiles if profile.name == selected_id]
    if len(name_matches) == 1:
        return name_matches[0]
    if selected_id == "default":
        return resolve_llm_profile(user_id=user_id)
    raise ValueError(f"未知的 LLM 配置: {selected_id}")


@lru_cache(maxsize=16)
def _build_client(profile_id: str, api_key: str, base_url: str) -> OpenAI:
    # 按 profile 复用连接池，避免每次请求重建客户端。
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=0)


def get_ai_client(model_id: str | None = None) -> OpenAI:
    profile = resolve_llm_profile(model_id)
    return _build_client(profile.id, profile.api_key, profile.base_url)


def resolve_model_id(model_id: str | None = None, user_id: int | None = None) -> str:
    """校验模型选择并返回规范化 profile id，供请求和 AgentRun 持久化。"""
    return resolve_llm_profile(model_id, user_id=user_id).id
