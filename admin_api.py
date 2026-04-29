"""
管理后台API模块
提供管理员相关的REST API
"""
import os
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import database
import user_system
from database import get_sync_session, get_admin_by_username
from models import Admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ==================== 认证相关 ====================

class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None
    admin: Optional[dict] = None


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest):
    """管理员登录"""
    admin = get_admin_by_username(request.username)
    
    if not admin:
        return AdminLoginResponse(success=False, message="用户名或密码错误")
    
    if not user_system.verify_password(request.password, admin.password_hash):
        return AdminLoginResponse(success=False, message="用户名或密码错误")
    
    # 更新最后登录时间
    with get_sync_session() as db:
        admin_obj = db.query(Admin).filter(Admin.id == admin.id).first()
        if admin_obj:
            admin_obj.last_login = datetime.utcnow()
            db.commit()
    
    token = user_system.create_access_token(admin.id, f"admin_{admin.username}")
    
    return AdminLoginResponse(
        success=True,
        message="登录成功",
        token=token,
        admin={
            "id": admin.id,
            "username": admin.username,
            "role": admin.role
        }
    )


def verify_admin_token(authorization: str = Header(None)) -> dict:
    """验证管理员Token"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的认证格式")
    
    token = authorization[7:]
    payload = user_system.decode_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    
    # 验证是否为管理员
    username = payload.get("username", "")
    if not username.startswith("admin_"):
        raise HTTPException(status_code=403, detail="权限不足")
    
    return payload


# ==================== 监控面板 ====================

@router.get("/stats")
async def get_stats(current_admin: dict = Depends(verify_admin_token)):
    """获取统计数据"""
    stats = database.get_stats()
    return stats


@router.get("/recent-activities")
async def get_recent_activities(
    limit: int = 20,
    current_admin: dict = Depends(verify_admin_token)
):
    """获取最近活动"""
    with get_sync_session() as db:
        from models import AdminLog, Admin
        logs = db.query(AdminLog).order_by(
            AdminLog.create_time.desc()
        ).limit(limit).all()
        
        activities = []
        for log in logs:
            admin = db.query(Admin).filter(Admin.id == log.admin_id).first()
            activities.append({
                "id": log.id,
                "admin": admin.username if admin else "Unknown",
                "action": log.action,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "details": log.details,
                "ip": log.ip_address,
                "time": log.create_time.isoformat() if log.create_time else None
            })
        
        return activities


# ==================== 用户管理 ====================

class UserListResponse(BaseModel):
    users: List[dict]
    total: int
    page: int
    page_size: int


@router.get("/users", response_model=UserListResponse)
async def get_users(
    page: int = 1,
    page_size: int = 20,
    is_banned: Optional[bool] = None,
    search: Optional[str] = None,
    current_admin: dict = Depends(verify_admin_token)
):
    """获取用户列表"""
    if search:
        users = database.search_users(search)
        return UserListResponse(
            users=[_user_to_dict(u) for u in users],
            total=len(users),
            page=1,
            page_size=len(users)
        )
    
    users = database.get_all_users(page, page_size, is_banned)
    total = database.get_total_users(is_banned)
    
    return UserListResponse(
        users=[_user_to_dict(u) for u in users],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: int,
    current_admin: dict = Depends(verify_admin_token)
):
    """获取用户详情"""
    user = database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 获取AI设置
    ai_settings = database.get_ai_settings(user_id)
    
    # 获取邀请关系
    with get_sync_session() as db:
        from models import Invitation, User
        inviter = None
        if user.invited_by:
            inviter = db.query(User).filter(User.id == user.invited_by).first()
        
        invited_users = db.query(User).filter(User.invited_by == user_id).all()
    
    return {
        "user": _user_to_dict(user),
        "ai_settings": {
            "persona": ai_settings.persona if ai_settings else "",
            "background": ai_settings.background if ai_settings else "",
            "personality": ai_settings.personality if ai_settings else "",
            "gender": ai_settings.gender if ai_settings else "",
            "inner_voice": ai_settings.inner_voice if ai_settings else False,
            "action_desc": ai_settings.action_desc if ai_settings else True,
            "avatar_url": ai_settings.avatar_url if ai_settings else None
        },
        "inviter": {
            "id": inviter.id,
            "username": inviter.username
        } if inviter else None,
        "invited_users": [
            {"id": u.id, "username": u.username, "create_time": u.create_time.isoformat()}
            for u in invited_users
        ]
    }


class BanUserRequest(BaseModel):
    user_id: int
    banned: bool
    reason: Optional[str] = None


@router.post("/users/ban")
async def ban_user(
    request: BanUserRequest,
    current_admin: dict = Depends(verify_admin_token),
    client_ip: str = "0.0.0.0"
):
    """封禁/解封用户"""
    user = database.get_user_by_id(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    database.ban_user(request.user_id, request.banned)
    
    # 记录操作日志
    admin_id = int(current_admin["sub"].replace("admin_", ""))
    database.admin_log(
        admin_id,
        "ban_user" if request.banned else "unban_user",
        "user",
        request.user_id,
        f"{'封禁' if request.banned else '解封'}用户 {user.username}: {request.reason or '未说明'}",
        client_ip
    )
    
    return {
        "success": True,
        "message": f"用户 {'已封禁' if request.banned else '已解封'}"
    }


class AddDaysRequest(BaseModel):
    user_id: int
    days: int
    reason: Optional[str] = None


@router.post("/users/add-days")
async def add_user_days(
    request: AddDaysRequest,
    current_admin: dict = Depends(verify_admin_token),
    client_ip: str = "0.0.0.0"
):
    """添加用户天数"""
    if request.days <= 0 or request.days > 365:
        raise HTTPException(status_code=400, detail="天数必须在1-365之间")
    
    user = database.get_user_by_id(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    database.add_user_days(request.user_id, request.days, request.reason or "管理员操作")
    
    # 记录操作日志
    admin_id = int(current_admin["sub"].replace("admin_", ""))
    database.admin_log(
        admin_id,
        "add_days",
        "user",
        request.user_id,
        f"添加 {request.days} 天: {request.reason or '管理员操作'}",
        client_ip
    )
    
    return {
        "success": True,
        "message": f"已为用户 {user.username} 添加 {request.days} 天"
    }


@router.get("/users/{user_id}/avatar")
async def get_user_avatar(
    user_id: int,
    current_admin: dict = Depends(verify_admin_token)
):
    """获取用户AI头像"""
    user = database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    ai_settings = database.get_ai_settings(user_id)
    if not ai_settings or not ai_settings.avatar_url:
        raise HTTPException(status_code=404, detail="用户未设置头像")
    
    # 返回头像文件
    avatar_path = config.AVATAR_DIR / f"{user_id}_avatar.jpg"
    if avatar_path.exists():
        return FileResponse(avatar_path)
    else:
        raise HTTPException(status_code=404, detail="头像文件不存在")


# ==================== 管理员管理 ====================

class CreateAdminRequest(BaseModel):
    username: str
    password: str
    role: str = "admin"


@router.post("/admins/create")
async def create_admin(
    request: CreateAdminRequest,
    current_admin: dict = Depends(verify_admin_token)
):
    """创建管理员"""
    # 检查权限
    admin_username = current_admin.get("username", "").replace("admin_", "")
    admin = get_admin_by_username(admin_username)
    
    if not admin or admin.role != "super_admin":
        raise HTTPException(status_code=403, detail="权限不足，只有超级管理员可以创建管理员")
    
    # 检查用户名是否存在
    if get_admin_by_username(request.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 创建管理员
    hashed = user_system.hash_password(request.password)
    database.create_admin(request.username, hashed, request.role)
    
    # 记录日志
    admin_id = int(current_admin["sub"].replace("admin_", ""))
    database.admin_log(
        admin_id,
        "create_admin",
        "admin",
        0,
        f"创建管理员 {request.username}，角色: {request.role}",
        "0.0.0.0"
    )
    
    return {
        "success": True,
        "message": f"管理员 {request.username} 创建成功"
    }


@router.get("/admins")
async def get_admins(
    current_admin: dict = Depends(verify_admin_token)
):
    """获取管理员列表"""
    with get_sync_session() as db:
        from models import Admin
        admins = db.query(Admin).all()
        return [
            {
                "id": a.id,
                "username": a.username,
                "role": a.role,
                "create_time": a.create_time.isoformat() if a.create_time else None,
                "last_login": a.last_login.isoformat() if a.last_login else None
            }
            for a in admins
        ]


# ==================== 充值管理（预留） ====================

@router.get("/transactions")
async def get_transactions(
    page: int = 1,
    page_size: int = 20,
    current_admin: dict = Depends(verify_admin_token)
):
    """获取交易记录"""
    with get_sync_session() as db:
        from models import Transaction
        transactions = db.query(Transaction).order_by(
            Transaction.create_time.desc()
        ).offset((page-1)*page_size).limit(page_size).all()
        
        return [
            {
                "id": t.id,
                "user_id": t.user_id,
                "amount": t.amount,
                "type": t.transaction_type,
                "description": t.description,
                "status": t.status,
                "time": t.create_time.isoformat() if t.create_time else None
            }
            for t in transactions
        ]


# ==================== 辅助函数 ====================

def _user_to_dict(user) -> dict:
    """用户对象转字典"""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "wechat_id": user.wechat_id,
        "create_time": user.create_time.isoformat() if user.create_time else None,
        "expire_time": user.expire_time.isoformat() if user.expire_time else None,
        "dialog_count": user.dialog_count,
        "invite_code": user.invite_code,
        "total_invites": user.total_invites,
        "is_banned": user.is_banned,
        "avatar_url": user.avatar_url,
        "remaining_days": database.get_user_remaining_days(user.id)
    }
