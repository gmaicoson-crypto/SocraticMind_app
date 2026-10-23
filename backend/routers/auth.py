import re
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from core.avatars import (
    AI_AVATAR_PRESETS,
    DEFAULT_AI_AVATAR,
    USER_AVATAR_PRESETS,
    choose_user_avatar,
)
from core.database import get_db
from core.avatar_uploads import UPLOAD_DIR, read_avatar_upload
from core.auth import hash_password, verify_password, create_access_token
from core.deps import get_current_user
from core.email import generate_code, send_verification_email
from core import rate_limit
from models.user import User
from models.topic import Topic
from models.node import Node
from models.email_code import EmailCode
from models.progress import ChatMessage, LearningRecord
from models.chat_session_title import ChatSessionTitle

CODE_TTL_MINUTES = 10
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

router = APIRouter(prefix="/api/auth", tags=["认证"])


# ── 请求 / 响应模型 ──


def _validate_password(v: str) -> str:
    """校验密码强度：至少 8 位，且必须同时包含字母和数字。"""
    if len(v) < 8:
        raise ValueError("密码至少 8 位")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("密码必须同时包含字母和数字")
    return v


def _validate_email(v: str) -> str:
    """统一转为小写并校验邮箱格式。"""
    v = v.strip().lower()
    if not EMAIL_RE.match(v):
        raise ValueError("邮箱格式不正确")
    return v


class SendCodeRequest(BaseModel):
    email: str
    purpose: str  # register / reset

    @field_validator("email")
    @classmethod
    def _e(cls, v: str) -> str:
        return _validate_email(v)


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    code: str

    @field_validator("email")
    @classmethod
    def _e(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("password")
    @classmethod
    def _check_pwd(cls, v: str) -> str:
        return _validate_password(v)

    @field_validator("username")
    @classmethod
    def _check_name(cls, v: str) -> str:
        v = v.strip()
        if not (2 <= len(v) <= 20):
            raise ValueError("用户名长度需在 2-20 之间")
        return v


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str

    @field_validator("email")
    @classmethod
    def _e(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("new_password")
    @classmethod
    def _check_pwd(cls, v: str) -> str:
        return _validate_password(v)


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    avatar_url: str
    ai_avatar_url: str = DEFAULT_AI_AVATAR
    bio: str
    daily_goal: int
    ai_style: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UpdateProfileRequest(BaseModel):
    username: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    ai_avatar_url: str | None = None
    daily_goal: int | None = None
    ai_style: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_pwd(cls, v: str) -> str:
        return _validate_password(v)


class DeleteAccountRequest(BaseModel):
    password: str
    confirm: str  # 前端须回传固定确认串（"DELETE"），防止误触注销


# ── 内部工具函数 ──


def _client_ip(request: Request) -> str:
    """获取真实客户端 IP：反向代理后取 X-Forwarded-For 首段，直连时退回 client.host。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _consume_code(db: Session, email: str, code: str, purpose: str) -> None:
    """校验验证码并将其标记为已使用，防止同一验证码被重复使用（重放攻击）。

    取该 (email, purpose) 下最新一条未使用未过期的记录进行匹配。
    """
    rec = (
        db.query(EmailCode)
        .filter(
            EmailCode.email == email,
            EmailCode.purpose == purpose,
            EmailCode.used == False,  # noqa: E712
        )
        .order_by(EmailCode.id.desc())
        .first()
    )
    if not rec:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    expires = rec.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < _now_utc():
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if rec.code != code.strip():
        raise HTTPException(status_code=400, detail="验证码错误")
    rec.used = True
    db.flush()


def init_default_topic(db: Session, user_id: int):
    """新用户注册后自动创建一个 Python 基础主题，帮助用户快速上手，无需从零配置图谱。"""
    topic = Topic(user_id=user_id, title="Python 基础知识", emoji="🐍")
    db.add(topic)
    db.flush()

    default_nodes = [
        ("py-basics", "Python 基础", "Fundamentals", 300, 140, "available", ""),
        ("vars", "变量", "Variables", 130, 260, "locked", "py-basics"),
        ("types", "数据类型", "Data Types", 300, 260, "locked", "py-basics"),
        ("operators", "运算符", "Operators", 470, 260, "locked", "py-basics"),
        ("conditionals", "条件语句", "if · elif · else", 200, 400, "locked", "vars,types"),
        ("comparison", "比较运算", "== · != · >", 400, 400, "locked", "operators,types"),
        ("loops", "循环", "for · while", 130, 540, "locked", "conditionals"),
        ("functions", "函数", "def · return", 320, 540, "locked", "conditionals,comparison"),
        ("scope", "作用域", "Scope", 480, 540, "locked", "operators,functions"),
        ("data-struct", "数据结构", "list · dict", 220, 660, "locked", "loops,functions"),
        ("modules", "模块", "import", 410, 660, "locked", "functions,scope"),
    ]

    for key, label, sub, x, y, state, parents in default_nodes:
        db.add(
            Node(
                topic_id=topic.id,
                node_key=key,
                label=label,
                sub=sub,
                x=x,
                y=y,
                state=state,
                parent_keys=parents,
            )
        )
    db.commit()


# ── 验证码 ──


@router.post("/send-code")
def send_code(req: SendCodeRequest, request: Request, db: Session = Depends(get_db)):
    purpose = req.purpose.strip()
    if purpose not in {"register", "reset"}:
        raise HTTPException(status_code=400, detail="未知的验证码用途")

    email = req.email.lower().strip()

    # 双重限流：单邮箱 60 秒一次 + 单 IP 每小时 10 次，防止批量发送骚扰
    if not rate_limit.hit(f"sendcode:email:{email}", max_calls=1, window_seconds=60):
        wait = rate_limit.remaining_seconds(f"sendcode:email:{email}", 60)
        raise HTTPException(status_code=429, detail=f"请求过于频繁，请 {wait} 秒后再试")
    ip = _client_ip(request)
    if not rate_limit.hit(f"sendcode:ip:{ip}", max_calls=10, window_seconds=3600):
        raise HTTPException(status_code=429, detail="该网络请求次数过多，请稍后再试")

    user_exists = db.query(User.id).filter(User.email == email).first() is not None
    if purpose == "register" and user_exists:
        raise HTTPException(status_code=400, detail="该邮箱已注册")
    if purpose == "reset" and not user_exists:
        # 不暴露该邮箱是否已注册，但仍消耗限流配额，防止邮箱枚举攻击
        return {"message": "如果该邮箱已注册，验证码已发送"}

    code = generate_code()
    expires = _now_utc() + timedelta(minutes=CODE_TTL_MINUTES)
    db.add(EmailCode(email=email, code=code, purpose=purpose, expires_at=expires))
    db.commit()

    try:
        send_verification_email(email, code, purpose)
    except Exception:
        raise HTTPException(status_code=500, detail="邮件发送失败，请稍后重试")

    return {"message": "验证码已发送，10 分钟内有效"}


# ── 注册 ──


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    email = req.email.lower().strip()

    # IP 维度限流：同一 IP 每小时最多注册 5 次，阻止批量注册脚本
    ip = _client_ip(request)
    if not rate_limit.hit(f"register:ip:{ip}", max_calls=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="注册请求过于频繁，请稍后再试")

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="邮箱已注册")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")

    _consume_code(db, email, req.code, "register")

    user = User(
        username=req.username,
        email=email,
        hashed_password=hash_password(req.password),
        avatar_url=choose_user_avatar(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    init_default_topic(db, user.id)

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


# ── 登录 ──


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form.username.lower().strip()

    # 账号维度：连续失败超过阈值后锁定，阻止针对特定账号的暴力破解
    locked = rate_limit.is_login_locked(email)
    if locked:
        raise HTTPException(
            status_code=429, detail=f"登录失败次数过多，请 {locked // 60 + 1} 分钟后再试"
        )

    # IP 维度：5 分钟内最多 20 次，防止单点扫密码
    ip = _client_ip(request)
    if not rate_limit.hit(f"login:ip:{ip}", max_calls=20, window_seconds=300):
        raise HTTPException(status_code=429, detail="登录请求过于频繁，请稍后再试")

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(form.password, user.hashed_password):
        rate_limit.record_login_fail(email)
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    rate_limit.reset_login_fail(email)
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


# ── 找回密码 ──


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    email = req.email.lower().strip()

    ip = _client_ip(request)
    if not rate_limit.hit(f"reset:ip:{ip}", max_calls=10, window_seconds=3600):
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        # 不暴露账号是否存在，统一返回模糊错误信息
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    _consume_code(db, email, req.code, "reset")

    user.hashed_password = hash_password(req.new_password)
    db.commit()
    rate_limit.reset_login_fail(email)
    return {"message": "密码已重置，请使用新密码登录"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserResponse)
def update_me(
    req: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if "avatar_url" in req.model_fields_set:
        if req.avatar_url not in USER_AVATAR_PRESETS:
            raise HTTPException(status_code=422, detail="未知的用户头像")
    if req.ai_avatar_url is not None and req.ai_avatar_url not in AI_AVATAR_PRESETS:
        raise HTTPException(status_code=422, detail="未知的 AI 头像")

    old_avatar_url = current_user.avatar_url
    if req.username is not None:
        current_user.username = req.username
    if req.bio is not None:
        current_user.bio = req.bio
    if "avatar_url" in req.model_fields_set:
        if req.avatar_url != current_user.avatar_url:
            current_user.avatar_url = req.avatar_url
    if req.ai_avatar_url is not None:
        current_user.ai_avatar_url = req.ai_avatar_url
    if req.daily_goal is not None:
        current_user.daily_goal = req.daily_goal
    if req.ai_style is not None:
        current_user.ai_style = req.ai_style
    db.commit()
    if current_user.avatar_url != old_avatar_url:
        _delete_old_avatar(old_avatar_url)
    db.refresh(current_user)
    return current_user


def _delete_old_avatar(url: str | None):
    """删除用户当前的头像文件；文件不存在或删除失败时静默忽略，不影响主流程。"""
    if not url or not url.startswith("/static/avatars/"):
        return
    fname = url.rsplit("/", 1)[-1]
    fpath = UPLOAD_DIR / fname
    if fpath.exists():
        try:
            fpath.unlink()
        except OSError:
            pass


@router.post("/avatar", response_model=UserResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    suffix, data = await read_avatar_upload(file)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _delete_old_avatar(current_user.avatar_url)

    # 用用户 ID + UUID 命名，避免文件名冲突
    fname = f"{current_user.id}_{uuid.uuid4().hex}{suffix}"
    fpath = UPLOAD_DIR / fname
    fpath.write_bytes(data)

    current_user.avatar_url = f"/static/avatars/{fname}"
    db.commit()
    db.refresh(current_user)
    return current_user


@router.delete("/avatar", response_model=UserResponse)
def reset_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _delete_old_avatar(current_user.avatar_url)
    current_user.avatar_url = choose_user_avatar()
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/password")
def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(req.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    current_user.hashed_password = hash_password(req.new_password)
    db.commit()
    return {"message": "密码修改成功"}


CONFIRM_PHRASE = "DELETE"


@router.delete("/me")
def delete_account(
    req: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """注销账号：需要密码 + 固定确认串双重校验，通过后删除所有关联数据和头像文件。"""
    if req.confirm.strip().upper() != CONFIRM_PHRASE:
        raise HTTPException(status_code=400, detail="二次确认未通过")
    if not verify_password(req.password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="密码错误")

    user_id = current_user.id
    user_email = current_user.email

    # Queue private attachment cleanup transactionally before user/message rows vanish.
    from services.attachments.service import delete_for_user

    delete_for_user(db, user_id)

    # 先删磁盘文件：数据库回滚无法恢复文件，所以在校验通过后立即执行
    _delete_old_avatar(current_user.avatar_url)
    for image in UPLOAD_DIR.glob(f"ai_{user_id}_*"):
        try:
            image.unlink()
        except OSError:
            pass

    # 显式删除 ChatMessage / LearningRecord / EmailCode：
    # 这些模型未在 User 侧声明 cascade，不能依赖 ORM 自动级联
    db.query(ChatMessage).filter(ChatMessage.user_id == user_id).delete(synchronize_session=False)
    db.query(ChatSessionTitle).filter(ChatSessionTitle.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(LearningRecord).filter(LearningRecord.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(EmailCode).filter(EmailCode.email == user_email).delete(synchronize_session=False)

    # 删用户本身；topics → nodes 走 ORM cascade（user.topics 配置了 cascade="all, delete"）
    db.delete(current_user)
    db.commit()

    # 清除登录失败计数，避免同邮箱重新注册后状态残留
    rate_limit.reset_login_fail(user_email)
    return {"message": "账号已注销"}
