from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from core.config import settings
from core.errors import install_api_error_handler
from core.database import engine
from core.avatar_uploads import UPLOAD_DIR
from core.avatars import PRESET_ASSET_DIR
from core.migrations import assert_database_at_head
from services.chat_summaries import ChatSummaryWorker
from services.chat_titles import ChatTitleWorker
from services.attachments.worker import AttachmentWorker
from routers import (
    agent,
    auth,
    topics,
    nodes,
    chat,
    chat_titles,
    memories,
    plans,
    progress,
    llm,
    attachments,
)
import models  # noqa: F401 - ensure ORM relationships can resolve registered models

# 头像文件存储目录，不存在时自动创建
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_database_at_head(engine)
    summaries = ChatSummaryWorker()
    summaries.start()
    titles = ChatTitleWorker()
    titles.start()
    attachment_worker = AttachmentWorker()
    attachment_worker.start()
    try:
        yield
    finally:
        titles.stop()
        attachment_worker.stop()
        summaries.stop()


app = FastAPI(
    title="SocraticMind API",
    description="AI 引导的知识图谱学习系统",
    version="1.0.0",
    lifespan=lifespan,
)
install_api_error_handler(app)
app.add_middleware(attachments.AttachmentUploadLimitMiddleware)

# 允许的前端源通过环境变量 CORS_ORIGINS 配置（逗号分隔），生产环境须改为实际域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# 将头像上传目录挂载为静态文件路由，前端通过 /static/avatars/<filename> 访问
app.mount("/static/avatars", StaticFiles(directory=str(UPLOAD_DIR)), name="avatars")
app.mount("/avatars", StaticFiles(directory=str(PRESET_ASSET_DIR)), name="preset-avatars")

app.include_router(auth.router)
app.include_router(topics.router)
app.include_router(nodes.router)
app.include_router(chat.router)
app.include_router(chat_titles.router)
app.include_router(progress.router)
app.include_router(agent.router)
app.include_router(plans.router)
app.include_router(memories.router)
app.include_router(llm.router)
app.include_router(attachments.router)


@app.get("/")
def root():
    return {"message": "SocraticMind API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
