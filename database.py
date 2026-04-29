"""
数据库操作模块
"""
import os
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

from models import (
    Base, User, AISettings, Invitation, Transaction, 
    Admin, AdminLog, ChatLog, Announcement
)

# 同步引擎（用于 itchat 同步操作）
SYNC_DATABASE_URL = config.DATABASE_URL.replace('sqlite:///', 'sqlite:///')
engine = create_engine(
    SYNC_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False
)

# 异步引擎（用于 FastAPI）
ASYNC_DATABASE_URL = config.DATABASE_URL.replace('sqlite:///', 'sqlite+aiosqlite:///')
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False
)

# Session factories
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = sessionmaker(
    bind=async_engine, class_=AsyncSession, autocommit=False, autoflush=False
)


def get_sync_session():
    """获取同步session"""
    return SyncSessionLocal()


async def get_async_session():
    """获取异步session"""
    async with AsyncSessionLocal() as session:
        yield session


def init_database():
    """初始化数据库"""
    Base.metadata.create_all(bind=engine)
    
    # 初始化管理员账号
    with get_sync_session() as db:
        admin = db.query(Admin).filter(Admin.username == config.ADMIN_USERNAME).first()
        if not admin:
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            hashed = pwd_context.hash(config.ADMIN_PASSWORD)
            admin = Admin(
                username=config.ADMIN_USERNAME,
                password_hash=hashed,
                role="super_admin",
                permissions='{"all": true}'
            )
            db.add(admin)
            db.commit()
            print(f"✓ 管理员账号已创建: {config.ADMIN_USERNAME}")


# ==================== 用户操作 ====================

def create_user(username: str, password_hash: str, email: str) -> Optional[User]:
    """创建用户"""
    with get_sync_session() as db:
        # 检查用户名是否存在
        if db.query(User).filter(User.username == username).first():
            return None
        
        # 检查邮箱是否存在
        if db.query(User).filter(User.email == email).first():
            return None
        
        # 生成邀请码
        invite_code = str(uuid.uuid4())[:8]
        
        user = User(
            username=username,
            password_hash=password_hash,
            email=email,
            invite_code=invite_code,
            expire_time=datetime.utcnow() + timedelta(days=7)  # 新用户7天试用
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # 创建默认AI设置
        ai_settings = AISettings(user_id=user.id)
        db.add(ai_settings)
        db.commit()
        
        return user


def get_user_by_username(username: str) -> Optional[User]:
    """通过用户名获取用户"""
    with get_sync_session() as db:
        return db.query(User).filter(User.username == username).first()


def get_user_by_wechat_id(wechat_id: str) -> Optional[User]:
    """通过微信ID获取用户"""
    with get_sync_session() as db:
        return db.query(User).filter(User.wechat_id == wechat_id).first()


def get_user_by_id(user_id: int) -> Optional[User]:
    """通过ID获取用户"""
    with get_sync_session() as db:
        return db.query(User).filter(User.id == user_id).first()


def update_user_wechat_id(user_id: int, wechat_id: str):
    """绑定微信ID"""
    with get_sync_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.wechat_id = wechat_id
            user.last_login = datetime.utcnow()
            db.commit()


def increment_dialog_count(user_id: int):
    """增加对话计数"""
    with get_sync_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.dialog_count += 1
            db.commit()


def add_user_days(user_id: int, days: int, reason: str = ""):
    """添加用户使用天数"""
    with get_sync_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            if user.expire_time and user.expire_time > datetime.utcnow():
                user.expire_time += timedelta(days=days)
            else:
                user.expire_time = datetime.utcnow() + timedelta(days=days)
            
            # 记录交易
            transaction = Transaction(
                user_id=user_id,
                amount=0,
                transaction_type="admin_grant",
                description=f"管理员添加 {days} 天: {reason}"
            )
            db.add(transaction)
            db.commit()


def ban_user(user_id: int, banned: bool = True):
    """封禁/解封用户"""
    with get_sync_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.is_banned = banned
            db.commit()


def is_user_active(user_id: int) -> bool:
    """检查用户是否有效（未过期、未被封禁）"""
    with get_sync_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        if user.is_banned:
            return False
        if user.expire_time and user.expire_time < datetime.utcnow():
            return False
        return True


def get_user_remaining_days(user_id: int) -> int:
    """获取用户剩余天数"""
    with get_sync_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.expire_time:
            return 0
        remaining = (user.expire_time - datetime.utcnow()).days
        return max(0, remaining)


# ==================== AI设置操作 ====================

def get_ai_settings(user_id: int) -> Optional[AISettings]:
    """获取AI设置"""
    with get_sync_session() as db:
        return db.query(AISettings).filter(AISettings.user_id == user_id).first()


def update_ai_settings(user_id: int, **kwargs) -> Optional[AISettings]:
    """更新AI设置"""
    with get_sync_session() as db:
        settings = db.query(AISettings).filter(AISettings.user_id == user_id).first()
        if not settings:
            settings = AISettings(user_id=user_id)
            db.add(settings)
        
        for key, value in kwargs.items():
            if hasattr(settings, key) and value is not None:
                setattr(settings, key, value)
        
        settings.update_time = datetime.utcnow()
        db.commit()
        db.refresh(settings)
        return settings


# ==================== 邀请操作 ====================

def create_invitation(inviter_id: int, invited_id: int) -> Invitation:
    """创建邀请记录"""
    with get_sync_session() as db:
        invitation = Invitation(
            inviter_id=inviter_id,
            invited_id=invited_id,
            is_valid=True
        )
        db.add(invitation)
        
        # 更新邀请者统计
        inviter = db.query(User).filter(User.id == inviter_id).first()
        if inviter:
            inviter.total_invites += 1
            
            # 检查是否满足奖励条件
            from config import INVITE_REWARDS
            for threshold, days in INVITE_REWARDS.items():
                if inviter.total_invites == threshold:
                    add_user_days(inviter_id, days, f"邀请奖励: 邀请{threshold}人")
                    break
        
        db.commit()
        return invitation


def get_invite_stats(user_id: int) -> Dict[str, Any]:
    """获取邀请统计"""
    with get_sync_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"total_invites": 0, "valid_invites": 0}
        
        valid_count = db.query(Invitation).filter(
            Invitation.inviter_id == user_id,
            Invitation.is_valid == True
        ).count()
        
        return {
            "total_invites": user.total_invites,
            "valid_invites": valid_count,
            "next_reward": get_next_reward_threshold(user.total_invites)
        }


def get_next_reward_threshold(current_count: int) -> Optional[Dict[str, Any]]:
    """获取下一个奖励阈值"""
    from config import INVITE_REWARDS
    for threshold, days in sorted(INVITE_REWARDS.items()):
        if current_count < threshold:
            return {"threshold": threshold, "days": days, "remaining": threshold - current_count}
    return None


# ==================== 对话记录 ====================

def save_chat_log(user_id: int, message: str, response: str, token_used: int = 0):
    """保存对话记录"""
    with get_sync_session() as db:
        log = ChatLog(
            user_id=user_id,
            message=message,
            response=response,
            token_used=token_used
        )
        db.add(log)
        db.commit()


# ==================== 管理员操作 ====================

def get_admin_by_username(username: str) -> Optional[Admin]:
    """获取管理员"""
    with get_sync_session() as db:
        return db.query(Admin).filter(Admin.username == username).first()


def create_admin(username: str, password_hash: str, role: str = "admin") -> Admin:
    """创建管理员"""
    with get_sync_session() as db:
        admin = Admin(
            username=username,
            password_hash=password_hash,
            role=role
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin


def admin_log(admin_id: int, action: str, target_type: str, target_id: int, 
              details: str = "", ip_address: str = ""):
    """记录管理员操作"""
    with get_sync_session() as db:
        log = AdminLog(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            ip_address=ip_address
        )
        db.add(log)
        db.commit()


def get_all_users(page: int = 1, page_size: int = 20, 
                  is_banned: Optional[bool] = None) -> List[User]:
    """获取所有用户（分页）"""
    with get_sync_session() as db:
        query = db.query(User)
        if is_banned is not None:
            query = query.filter(User.is_banned == is_banned)
        query = query.order_by(User.create_time.desc())
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()


def get_total_users(is_banned: Optional[bool] = None) -> int:
    """获取用户总数"""
    with get_sync_session() as db:
        query = db.query(User)
        if is_banned is not None:
            query = query.filter(User.is_banned == is_banned)
        return query.count()


def get_stats() -> Dict[str, Any]:
    """获取统计数据"""
    with get_sync_session() as db:
        total_users = db.query(User).count()
        banned_users = db.query(User).filter(User.is_banned == True).count()
        active_users = db.query(User).filter(
            User.expire_time > datetime.utcnow(),
            User.is_banned == False
        ).count()
        total_dialogs = db.query(ChatLog).count()
        total_invites = db.query(Invitation).filter(Invitation.is_valid == True).count()
        
        # 计算总收入
        transactions = db.query(Transaction).filter(
            Transaction.transaction_type.in_(["recharge", "admin_grant"])
        ).all()
        total_revenue = sum(t.amount or 0 for t in transactions if t.amount and t.amount > 0)
        
        # 今日新增用户
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_new_users = db.query(User).filter(User.create_time >= today_start).count()
        
        return {
            "total_users": total_users,
            "active_users": active_users,
            "banned_users": banned_users,
            "total_dialogs": total_dialogs,
            "total_invites": total_invites,
            "total_revenue": total_revenue,
            "today_new_users": today_new_users
        }


def search_users(keyword: str) -> List[User]:
    """搜索用户"""
    with get_sync_session() as db:
        return db.query(User).filter(
            (User.username.contains(keyword)) |
            (User.email.contains(keyword)) |
            (User.wechat_id.contains(keyword))
        ).limit(50).all()
