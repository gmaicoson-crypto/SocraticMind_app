import smtplib
import logging
import secrets
from pathlib import Path
from email.message import EmailMessage
from email.utils import formataddr
from .config import settings

_TEMPLATE_DIR = Path(__file__).parent / "templates"

log = logging.getLogger(__name__)


def generate_code() -> str:
    """生成 6 位随机数字验证码，使用 secrets 模块保证密码学安全。"""
    return f"{secrets.randbelow(1_000_000):06d}"


def _plain_body(action: str, code: str) -> str:
    """构造纯文本邮件正文，作为 HTML 版本的降级备份。"""
    return (
        f"您正在{action} {settings.app_name}。\n\n"
        f"验证码：{code}\n"
        f"有效期 10 分钟，请勿泄露给他人。\n\n"
        f"若非本人操作，请忽略此邮件。"
    )


def _html_body(action: str, code: str) -> str:
    """读取 HTML 模板并填充变量，生成美观的富文本邮件正文。"""
    template = (_TEMPLATE_DIR / "verification_email.html").read_text(encoding="utf-8")
    return template.format(app_name=settings.app_name, action=action, code=code)


def _build_message(to: str, code: str, purpose: str) -> EmailMessage:
    """根据用途（注册/重置密码）组装完整的邮件对象，同时包含纯文本和 HTML 两种格式。"""
    action = "注册" if purpose == "register" else "重置密码"
    msg = EmailMessage()
    msg["Subject"] = f"【{settings.app_name}】{action}验证码：{code}"
    msg["From"] = formataddr((settings.app_name, settings.smtp_from or settings.smtp_user))
    msg["To"] = to
    msg.set_content(_plain_body(action, code))
    msg.add_alternative(_html_body(action, code), subtype="html")
    return msg


def send_verification_email(to: str, code: str, purpose: str) -> None:
    """发送验证码邮件，支持 STARTTLS 和 SSL 两种加密方式。

    发送失败时记录错误日志并向上抛出异常，由调用方决定如何响应用户。
    smtp_host 为空时退化为控制台打印，方便本地开发调试。
    """
    if not settings.smtp_host:
        log.warning(
            "[DEV] 验证码 to=%s code=%s purpose=%s（SMTP 未配置，仅打印不发送）", to, code, purpose
        )
        return

    msg = _build_message(to, code, purpose)
    try:
        if settings.smtp_use_tls:
            # STARTTLS：先建立明文连接再升级为加密，端口通常为 587
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
        else:
            # SMTP_SSL：直接建立加密连接，端口通常为 465
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
    except Exception as e:
        log.error("验证码邮件发送失败 to=%s err=%s", to, e)
        raise
