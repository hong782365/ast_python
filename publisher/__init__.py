# 导入 core.config 确保配置初始化
import core.config

from fastapi import FastAPI
from .lifespan import lifespan
from .routes import router

# 构建 FastAPI 应用
app = FastAPI(title="Audio Stream Publisher", version="1.0.0", lifespan=lifespan)
app.include_router(router)

__all__ = ['app']