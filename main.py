"""
微信AI角色扮演聊天系统 - 主程序入口
基于 FastAPI 构建的 Web 服务
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse

import config
import database
from admin_api import router as admin_router

# 确保目录存在
UPLOAD_DIR = config.UPLOAD_DIR
AVATAR_DIR = config.AVATAR_DIR
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AVATAR_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    print("=" * 50)
    print("微信AI角色扮演聊天系统启动中...")
    print("=" * 50)
    
    # 初始化数据库
    database.init_database()
    print("✓ 数据库初始化完成")
    
    # 创建上传目录
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    print("✓ 上传目录创建完成")
    
    print("=" * 50)
    print("系统启动成功！")
    print(f"• API文档: http://{config.HOST}:{config.PORT}/docs")
    print(f"• 管理后台: http://{config.HOST}:{config.PORT}/admin")
    print("=" * 50)
    
    yield
    
    # 关闭时清理
    print("系统关闭中...")


# 创建FastAPI应用
app = FastAPI(
    title="微信AI角色扮演聊天系统",
    description="一个功能完整的微信AI角色扮演聊天系统API",
    version="1.0.0",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# ==================== 公开API ====================

@app.get("/")
async def root():
    """首页"""
    return {
        "name": "微信AI角色扮演聊天系统",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "admin": "/admin"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


# ==================== 用户API ====================

@app.post("/api/user/register")
async def register(
    username: str,
    password: str,
    email: str,
    invite_code: str = None
):
    """用户注册"""
    import user_system
    
    valid, data, error = user_system.validate_register_format(
        f"{username}/{password}/{email}"
    )
    
    if not valid:
        raise HTTPException(status_code=400, detail=error)
    
    success, message, user_id = user_system.register_user(
        data["username"],
        data["password"],
        data["email"],
        invite_code
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message, "user_id": user_id}


@app.post("/api/user/login")
async def login(username: str, password: str, wechat_id: str = None):
    """用户登录"""
    import user_system
    
    success, message, token = user_system.login_user(
        username, password, wechat_id
    )
    
    if not success:
        raise HTTPException(status_code=401, detail=message)
    
    return {"success": True, "message": message, "token": token}


@app.get("/api/user/status/{wechat_id}")
async def get_user_status(wechat_id: str):
    """获取用户状态"""
    import user_system
    return user_system.get_user_status(wechat_id)


@app.get("/api/user/info/{wechat_id}")
async def get_user_info(wechat_id: str):
    """获取用户信息"""
    import user_system
    
    status = user_system.get_user_status(wechat_id)
    if status["status"] != "active":
        return status
    
    user = database.get_user_by_id(status["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "remaining_days": status["remaining_days"],
        "dialog_count": user.dialog_count,
        "total_invites": user.total_invites
    }


@app.get("/api/user/usage/{wechat_id}")
async def get_usage(wechat_id: str):
    """获取使用信息"""
    import user_system
    return {"message": user_system.get_usage_info(wechat_id)}


@app.get("/api/user/invite/{wechat_id}")
async def get_invite(wechat_id: str):
    """获取邀请链接"""
    import user_system
    return {"message": user_system.get_invite_link(wechat_id)}


@app.get("/api/user/invite-stats/{wechat_id}")
async def get_invite_stats(wechat_id: str):
    """获取邀请统计"""
    import user_system
    return {"message": user_system.get_invite_stats_message(wechat_id)}


# ==================== AI设置API ====================

@app.get("/api/ai/settings/{user_id}")
async def get_ai_settings(user_id: int):
    """获取AI设置"""
    settings = database.get_ai_settings(user_id)
    if not settings:
        raise HTTPException(status_code=404, detail="设置不存在")
    
    return {
        "persona": settings.persona,
        "background": settings.background,
        "personality": settings.personality,
        "gender": settings.gender,
        "inner_voice": settings.inner_voice,
        "action_desc": settings.action_desc,
        "avatar_url": settings.avatar_url
    }


@app.post("/api/ai/settings/{user_id}")
async def update_ai_settings(
    user_id: int,
    persona: str = None,
    background: str = None,
    personality: str = None,
    gender: str = None,
    inner_voice: bool = None,
    action_desc: bool = None
):
    """更新AI设置"""
    user = database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    update_data = {}
    if persona is not None:
        update_data["persona"] = persona
    if background is not None:
        update_data["background"] = background
    if personality is not None:
        update_data["personality"] = personality
    if gender is not None:
        update_data["gender"] = gender
    if inner_voice is not None:
        update_data["inner_voice"] = inner_voice
    if action_desc is not None:
        update_data["action_desc"] = action_desc
    
    settings = database.update_ai_settings(user_id, **update_data)
    
    return {"success": True, "message": "设置已更新", "settings": {
        "persona": settings.persona,
        "background": settings.background,
        "personality": settings.personality,
        "gender": settings.gender,
        "inner_voice": settings.inner_voice,
        "action_desc": settings.action_desc
    }}


@app.post("/api/ai/avatar/{user_id}")
async def upload_avatar(user_id: int, file: UploadFile = File(...)):
    """上传头像"""
    user = database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 检查文件类型
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只能上传图片文件")
    
    # 保存文件
    filename = f"{user_id}_avatar.jpg"
    filepath = AVATAR_DIR / filename
    
    with open(filepath, "wb") as f:
        content = await file.read()
        if len(content) > config.MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail="文件大小不能超过5MB")
        f.write(content)
    
    # 更新数据库
    avatar_url = f"/uploads/avatars/{filename}"
    database.update_ai_settings(user_id, avatar_url=avatar_url)
    
    return {"success": True, "avatar_url": avatar_url}


# ==================== AI对话API ====================

@app.post("/api/ai/chat")
async def chat(
    message: str,
    user_id: int = None,
    wechat_id: str = None
):
    """发送AI对话请求"""
    import user_system
    from ai_chat import ai_chat
    
    # 获取用户
    if wechat_id:
        user = database.get_user_by_wechat_id(wechat_id)
    elif user_id:
        user = database.get_user_by_id(user_id)
    else:
        raise HTTPException(status_code=400, detail="需要提供user_id或wechat_id")
    
    if not user:
        return {"error": "用户不存在，请先注册"}
    
    if user.is_banned:
        return {"error": "账号已被封禁"}
    
    # 检查使用时间
    if not database.is_user_active(user.id):
        return {"error": "使用时间已到期，请续费后使用"}
    
    # 调用AI
    response, inner_thought = await ai_chat.chat(user.id, message)
    
    # 更新对话计数
    database.increment_dialog_count(user.id)
    
    # 保存对话记录
    database.save_chat_log(user.id, message, response)
    
    return {
        "response": response,
        "inner_thought": inner_thought,
        "user": {
            "id": user.id,
            "username": user.username,
            "dialog_count": user.dialog_count + 1
        }
    }


# ==================== 管理后台API ====================

app.include_router(admin_router)


# ==================== 管理后台页面 ====================

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """管理后台页面"""
    admin_html_path = Path(__file__).parent.parent / "frontend" / "index.html"
    
    if admin_html_path.exists():
        with open(admin_html_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        return """
        <html>
        <head><title>管理后台</title></head>
        <body>
            <h1>管理后台</h1>
            <p>前端文件未找到，请检查 frontend/index.html</p>
        </body>
        </html>
        """


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG
    )
