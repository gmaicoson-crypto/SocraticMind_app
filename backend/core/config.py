import hashlib
import json
import re
from io import StringIO
from pathlib import Path
from typing import Literal, Mapping

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, DotEnvSettingsSource, PydanticBaseSettingsSource
from pydantic_settings.sources import parse_env_vars


class MultilineLLMDotEnvSource(DotEnvSettingsSource):
    """Allow an unquoted, pretty-printed LLM_MODELS array in .env files."""

    def _read_env_file(self, file_path: Path) -> Mapping[str, str | None]:
        lines = file_path.read_text(encoding=self.env_file_encoding or "utf-8").splitlines(
            keepends=True
        )
        dotenv_lines = []
        multiline_models = None
        index = 0
        while index < len(lines):
            line = lines[index]
            start = re.fullmatch(
                r"([ \t]*)(?:export[ \t]+)?LLM_MODELS[ \t]*=[ \t]*\[[ \t]*",
                line.rstrip("\r\n"),
            )
            if start:
                closing = re.compile(rf"{re.escape(start.group(1))}\][ \t]*")
                end = index + 1
                while end < len(lines) and not closing.fullmatch(lines[end].rstrip("\r\n")):
                    end += 1
                if end < len(lines):
                    multiline_models = (
                        line.partition("=")[2] + "".join(lines[index + 1 : end + 1])
                    ).strip()
                    index = end + 1
                    continue
            dotenv_lines.append(line)
            index += 1

        values = dotenv_values(
            stream=StringIO("".join(dotenv_lines)), encoding=self.env_file_encoding or "utf-8"
        )
        if multiline_models is not None:
            values["LLM_MODELS"] = multiline_models
        return parse_env_vars(
            values, self.case_sensitive, self.env_ignore_empty, self.env_parse_none_str
        )


class LLMImageCapabilities(BaseModel):
    """Legacy image settings accepted for compatibility, without gating uploads."""

    image_input: Literal["supported", "unsupported", "unknown"] = "unknown"
    max_images: int = Field(default=9, ge=1, le=9)
    max_image_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=10 * 1024 * 1024)
    vision_token_budget: int | None = Field(default=None, gt=0, le=256_000)


class LLMContextCapabilities(LLMImageCapabilities):
    """容量按实际服务配置，默认使用项目统一的 256K 窗口。"""

    context_window_tokens: int = Field(default=256_000, gt=0)
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int = Field(default=4_096, gt=0)
    output_tokens: int = Field(default=4_096, gt=0)
    # 推理服务可单独配置“推理 + 可见回答”的总生成额度，不从窗口大小猜测。
    reasoning_output_tokens: int | None = Field(default=None, gt=0)
    safety_margin_tokens: int = Field(default=8_192, ge=0)
    target_input_tokens: int = Field(default=64_000, gt=0)
    summary_trigger_tokens: int = Field(default=48_000, gt=0)
    summary_target_tokens: int = Field(default=32_000, gt=0)
    # None 自动识别已知模型；未知模型按 UTF-8 字节保守估算。
    # 可显式指定服务的 tiktoken encoding，或 "utf8_bytes" 强制保守估算。
    tokenizer_encoding: str | None = None
    completion_token_parameter: Literal["auto", "max_tokens", "max_completion_tokens"] = "auto"
    stream_usage: bool = True
    temperature: float | None = Field(default=0.7, ge=0, le=2)

    @property
    def generation_budget_tokens(self) -> int:
        return self.reasoning_output_tokens or self.output_tokens

    @model_validator(mode="after")
    def validate_context_capacity(self):
        if self.generation_budget_tokens > self.max_output_tokens:
            raise ValueError("生成预算不能超过服务的最大输出额度")
        if self.generation_budget_tokens + self.safety_margin_tokens >= self.context_window_tokens:
            raise ValueError("上下文窗口必须大于生成预算与安全余量之和")
        if not self.summary_target_tokens < self.summary_trigger_tokens <= self.target_input_tokens:
            raise ValueError("摘要目标必须小于触发阈值，触发阈值不能超过常规输入目标")
        return self


class LLMProfile(LLMContextCapabilities):
    """一个 OpenAI 兼容服务的连接配置。密钥只在后端进程内使用。"""

    id: str
    name: str
    api_key: str
    base_url: str
    model: str


class LLMConfig(LLMContextCapabilities):
    """服务配置及可选容量覆盖；运行时 ID 由服务地址和模型生成。"""

    model_config = ConfigDict(extra="forbid")

    model: str
    api_key: str
    base_url: str
    name: str


class Settings(BaseSettings):
    # 保留旧变量，未配置 LLM_MODELS 时继续支持单模型部署。
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    # JSON 数组必填 MODEL、API_KEY、BASE_URL、NAME，可附加上下文能力配置。
    llm_models: str = ""
    llm_default_model_id: str = ""
    secret_key: str
    database_url: str = "mysql+pymysql://root@localhost:3306/socraticmind"
    access_token_expire_minutes: int = 60 * 24 * 7  # 默认 7 天

    # 联网默认关闭；真实质量、延迟、费用验收后再启用。
    web_search_enabled: bool = False
    tavily_api_key: str = ""
    web_search_api_base: str = "https://api.tavily.com"
    web_decision_timeout_seconds: float = Field(default=5, gt=0, le=30)
    web_search_timeout_seconds: float = Field(default=8, gt=0, le=60)
    web_decision_input_tokens: int = Field(default=6_000, ge=512, le=32_000)
    web_decision_output_tokens: int = Field(default=2_048, ge=128, le=16_384)
    web_evidence_tokens: int = Field(default=4_000, ge=128, le=16_000)
    web_search_daily_query_limit: int = Field(default=100, ge=0)
    web_search_global_daily_query_limit: int = Field(default=1_000, ge=0)
    web_search_max_workers: int = Field(default=8, ge=1, le=64)
    chat_stream_max_workers: int = Field(default=8, ge=1, le=128)
    web_search_max_pending: int = Field(default=8, ge=0, le=128)
    web_search_max_response_bytes: int = Field(default=1_000_000, ge=1_024, le=8_000_000)

    attachment_storage_dir: str | None = None
    attachment_libreoffice_path: str | None = None
    avatar_storage_dir: str | None = None

    # 允许的前端源，逗号分隔；生产环境需改为实际域名，禁止保留 localhost
    cors_origins: str = "http://localhost:5173"

    # SMTP 邮件配置；smtp_host 为空时验证码只打印到控制台，适合本地开发调试
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    app_name: str = "SocraticMind"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: DotEnvSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            MultilineLLMDotEnvSource(
                settings_cls,
                env_file=(".env" if dotenv_settings.env_file == () else dotenv_settings.env_file),
                env_file_encoding=dotenv_settings.env_file_encoding,
                case_sensitive=dotenv_settings.case_sensitive,
                env_prefix=dotenv_settings.env_prefix,
                env_nested_delimiter=dotenv_settings.env_nested_delimiter,
                env_ignore_empty=dotenv_settings.env_ignore_empty,
                env_parse_none_str=dotenv_settings.env_parse_none_str,
                env_parse_enums=dotenv_settings.env_parse_enums,
            ),
            file_secret_settings,
        )

    @property
    def cors_origins_list(self) -> list[str]:
        """将逗号分隔的字符串解析为列表，过滤空白项。"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_profiles(self) -> list[LLMProfile]:
        """解析多模型配置，并为旧版环境变量生成一个兼容 profile。"""
        if self.llm_models.strip():
            try:
                raw_profiles = json.loads(self.llm_models)
            except json.JSONDecodeError as error:
                raise ValueError("LLM_MODELS 必须是合法的 JSON 数组") from error
            if not isinstance(raw_profiles, list) or not raw_profiles:
                raise ValueError("LLM_MODELS 必须是非空 JSON 数组")
            profiles = []
            for raw_profile in raw_profiles:
                if not isinstance(raw_profile, dict):
                    raise ValueError("LLM_MODELS 中的每项必须是对象")
                values = {key.lower(): value for key, value in raw_profile.items()}
                legacy_id = values.pop("id", None)
                config = LLMConfig.model_validate(values)
                profile_id = (
                    legacy_id
                    or "env:"
                    + hashlib.sha256(
                        f"{config.base_url.rstrip('/')}\0{config.model}".encode()
                    ).hexdigest()[:16]
                )
                profiles.append(LLMProfile(id=profile_id, **config.model_dump()))
        else:
            if not all((self.llm_api_key, self.llm_base_url, self.llm_model)):
                raise ValueError(
                    "请配置 LLM_MODELS，或同时配置 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL"
                )
            profiles = [
                LLMProfile(
                    id="default",
                    name="默认模型",
                    api_key=self.llm_api_key,
                    base_url=self.llm_base_url,
                    model=self.llm_model,
                )
            ]

        ids = [profile.id for profile in profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("LLM_MODELS 中的 id 必须唯一")
        return profiles

    @property
    def default_llm_profile_id(self) -> str:
        if self.llm_default_model_id:
            matches = [
                profile
                for profile in self.llm_profiles
                if self.llm_default_model_id in (profile.id, profile.name, profile.model)
            ]
            if len(matches) == 1:
                return matches[0].id
        return self.llm_profiles[0].id

    class Config:
        # The built-in dotenv source is created before custom sources; keep it empty.
        env_file = ()


settings = Settings()
