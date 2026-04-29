"""
数据模型定义
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Float
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class User(Base):
    """用户模型"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    wechat_id = Column(String(100), index=True)
    create_time = Column(DateTime, default=datetime.utcnow)
    expire_time = Column(DateTime)
    dialog_count = Column(Integer, default=0)
    invite_code = Column(String(20), unique=True, index=True)
    invited_by = Column(Integer, ForeignKey("users.id"))
    is_banned = Column(Boolean, default=False)
    avatar_url = Column(String(500))
    total_invites = Column(Integer, default=0)
    last_login = Column(DateTime)
    
    # 关系
    ai_settings = relationship("AISettings", back_populates="user", uselist=False)
    invitations_sent = relationship("Invitation", foreign_keys="Invitation.inviter_id")
    invitations_received = relationship("Invitation", foreign_keys="Invitation.invited_id")


class AISettings(Base):
    """AI设置模型"""
    __tablename__ = "ai_settings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    persona = Column(Text, default="一个温柔体贴的AI恋人")
    background = Column(Text, default="我是你的专属恋人，随时陪伴在你身边")
    personality = Column(String(50), default="温柔")
    gender = Column(String(10), default="女")
    inner_voice = Column(Boolean, default=False)
    action_desc = Column(Boolean, default=True)
    avatar_url = Column(String(500))
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    user = relationship("User", back_populates="ai_settings")


class Invitation(Base):
    """邀请记录模型"""
    __tablename__ = "invitations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    inviter_id = Column(Integer, ForeignKey("users.id"))
    invited_id = Column(Integer, ForeignKey("users.id"), unique=True)
    create_time = Column(DateTime, default=datetime.utcnow)
    is_valid = Column(Boolean, default=True)


class Transaction(Base):
    """交易记录模型"""
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Float)
    transaction_type = Column(String(50))
    description = Column(String(200))
    create_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="completed")


class Admin(Base):
    """管理员模型"""
    __tablename__ = "admins"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="admin")
    permissions = Column(Text)
    create_time = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)


class AdminLog(Base):
    """管理员操作日志"""
    __tablename__ = "admin_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    action = Column(String(100))
    target_type = Column(String(50))
    target_id = Column(Integer)
    details = Column(Text)
    ip_address = Column(String(50))
    create_time = Column(DateTime, default=datetime.utcnow)


class ChatLog(Base):
    """对话记录模型"""
    __tablename__ = "chat_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    message = Column(Text)
    response = Column(Text)
    token_used = Column(Integer)
    create_time = Column(DateTime, default=datetime.utcnow)


class Announcement(Base):
    """公告模型"""
    __tablename__ = "announcements"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200))
    content = Column(Text)
    create_time = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


# ==================== Pydantic 模型（API请求/响应） ====================

class UserRegister(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    email: EmailStr


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str
    password: str


class UserInfo(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    email: str
    wechat_id: Optional[str]
    create_time: datetime
    expire_time: Optional[datetime]
    dialog_count: int
    invite_code: str
    total_invites: int
    is_banned: bool
    avatar_url: Optional[str]
    
    class Config:
        from_attributes = True


class AISettingsUpdate(BaseModel):
    """AI设置更新"""
    persona: Optional[str] = None
    background: Optional[str] = None
    personality: Optional[str] = None
    gender: Optional[str] = None
    inner_voice: Optional[bool] = None
    action_desc: Optional[bool] = None


class AISettingsResponse(BaseModel):
    """AI设置响应"""
    id: int
    user_id: int
    persona: str
    background: str
    personality: str
    gender: str
    inner_voice: bool
    action_desc: bool
    avatar_url: Optional[str]
    
    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    wechat_id: Optional[str] = None


class ChatResponse(BaseModel):
    """聊天响应"""
    response: str
    inner_thought: Optional[str] = None
    token_used: int = 0


class AdminLogin(BaseModel):
    """管理员登录"""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Token响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class StatsResponse(BaseModel):
    """统计数据响应"""
    total_users: int
    active_users: int
    total_dialogs: int
    total_invites: int
    total_revenue: float
    today_new_users: int
    banned_users: int


class UserListItem(BaseModel):
    """用户列表项"""
    id: int
    username: str
    email: str
    wechat_id: Optional[str]
    create_time: datetime
    expire_time: Optional[datetime]
    dialog_count: int
    total_invites: int
    is_banned: bool
    avatar_url: Optional[str]
    
    class Config:
        from_attributes = True


class BanUserRequest(BaseModel):
    """封禁用户请求"""
    user_id: int
    reason: Optional[str] = None


class AddDaysRequest(BaseModel):
    """添加天数请求"""
    user_id: int
    days: int
    reason: Optional[str] = None
