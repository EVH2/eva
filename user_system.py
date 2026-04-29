"""
用户系统模块
处理用户注册、登录、认证等功能
"""
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

from passlib.context import CryptContext
import jwt

import config
import database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """密码哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: int, username: str) -> str:
    """创建JWT访问令牌"""
    expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """解码JWT令牌"""
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def validate_username(username: str) -> Tuple[bool, str]:
    """验证用户名格式"""
    if len(username) < 3:
        return False, "用户名至少需要3个字符"
    if len(username) > 50:
        return False, "用户名最多50个字符"
    if not re.match(r'^[\w\u4e00-\u9fff]+$', username):
        return False, "用户名只能包含字母、数字、下划线和中文"
    return True, ""


def validate_password(password: str) -> Tuple[bool, str]:
    """验证密码强度"""
    if len(password) < 6:
        return False, "密码至少需要6个字符"
    if len(password) > 100:
        return False, "密码太长"
    return True, ""


def validate_email(email: str) -> Tuple[bool, str]:
    """验证邮箱格式"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False, "邮箱格式不正确"
    return True, ""


def validate_register_format(data: str) -> Tuple[bool, Optional[Dict[str, str]], str]:
    """
    验证注册格式
    格式: 用户名/密码/邮箱
    返回: (是否成功, 解析数据, 错误信息)
    """
    parts = data.strip().split('/')
    if len(parts) != 3:
        return False, None, "格式错误，请使用：用户名/密码/邮箱"
    
    username, password, email = [p.strip() for p in parts]
    
    # 验证用户名
    valid, msg = validate_username(username)
    if not valid:
        return False, None, f"用户名错误: {msg}"
    
    # 验证密码
    valid, msg = validate_password(password)
    if not valid:
        return False, None, f"密码错误: {msg}"
    
    # 验证邮箱
    valid, msg = validate_email(email)
    if not valid:
        return False, None, f"邮箱错误: {msg}"
    
    return True, {"username": username, "password": password, "email": email}, ""


def validate_login_format(data: str) -> Tuple[bool, Optional[Dict[str, str]], str]:
    """
    验证登录格式
    格式: 用户名/密码
    返回: (是否成功, 解析数据, 错误信息)
    """
    parts = data.strip().split('/')
    if len(parts) != 2:
        return False, None, "格式错误，请使用：用户名/密码"
    
    username, password = [p.strip() for p in parts]
    
    if not username:
        return False, None, "用户名不能为空"
    if not password:
        return False, None, "密码不能为空"
    
    return True, {"username": username, "password": password}, ""


def register_user(username: str, password: str, email: str, 
                 invited_by_code: str = None) -> Tuple[bool, str, Optional[int]]:
    """
    注册新用户
    返回: (是否成功, 消息, 用户ID)
    """
    # 检查用户名是否存在
    if database.get_user_by_username(username):
        return False, "用户名已存在", None
    
    # 哈希密码
    hashed = hash_password(password)
    
    # 创建用户
    user = database.create_user(username, hashed, email)
    if not user:
        return False, "注册失败，请稍后重试", None
    
    # 处理邀请关系
    if invited_by_code:
        inviter = None
        # 通过邀请码查找邀请者
        from database import get_sync_session
        with get_sync_session() as db:
            from models import User
            inviter = db.query(User).filter(User.invite_code == invited_by_code).first()
        
        if inviter:
            database.create_invitation(inviter.id, user.id)
    
    return True, f"注册成功！欢迎 {username}", user.id


def login_user(username: str, password: str, wechat_id: str = None) -> Tuple[bool, str, Optional[str]]:
    """
    用户登录
    返回: (是否成功, 消息, JWT令牌)
    """
    user = database.get_user_by_username(username)
    if not user:
        return False, "用户名或密码错误", None
    
    if not verify_password(password, user.password_hash):
        return False, "用户名或密码错误", None
    
    if user.is_banned:
        return False, "账号已被封禁", None
    
    # 绑定微信ID（如果提供）
    if wechat_id:
        database.update_user_wechat_id(user.id, wechat_id)
    
    # 创建令牌
    token = create_access_token(user.id, user.username)
    
    return True, f"登录成功！欢迎回来 {user.username}", token


def get_user_status(wechat_id: str) -> Dict[str, Any]:
    """
    获取用户状态
    """
    user = database.get_user_by_wechat_id(wechat_id)
    if not user:
        return {"status": "not_bound", "message": "未注册账号请注册，格式：用户名/密码/邮箱"}
    
    # 检查是否过期
    remaining = database.get_user_remaining_days(user.id)
    if remaining <= 0 and user.expire_time:
        return {
            "status": "expired",
            "message": f"账号已过期，请充值后使用。发送 /充值 查看套餐"
        }
    
    # 检查是否被封禁
    if user.is_banned:
        return {
            "status": "banned",
            "message": "账号已被封禁，请联系管理员"
        }
    
    return {
        "status": "active",
        "user_id": user.id,
        "username": user.username,
        "remaining_days": remaining,
        "dialog_count": user.dialog_count,
        "token": create_access_token(user.id, user.username)
    }


def get_help_message() -> str:
    """获取帮助菜单"""
    return """【AI恋人助手】
/菜单 - 显示此帮助
/设置 - 设置人设、背景故事、性格、性别、心声、动作描述
/官方dy号：xy07s - 查看官方抖音
/使用时间 - 查看剩余使用时间
/对话多少句 - 查看已对话句数
/邀请用户链接生成 - 生成专属邀请链接
/已邀请多少人 - 查看邀请统计
/充值 - 充值会员（待接入）

💡 提示：直接发送消息即可与AI对话"""


def get_usage_info(wechat_id: str) -> str:
    """获取使用信息"""
    user = database.get_user_by_wechat_id(wechat_id)
    if not user:
        return "请先登录账号"
    
    remaining = database.get_user_remaining_days(user.id)
    return f"""【使用信息】
用户名：{user.username}
剩余时间：{remaining} 天
对话句数：{user.dialog_count} 句
注册时间：{user.create_time.strftime('%Y-%m-%d')}"""


def get_invite_link(wechat_id: str) -> str:
    """获取邀请链接"""
    user = database.get_user_by_wechat_id(wechat_id)
    if not user:
        return "请先登录账号"
    
    invite_url = f"https://example.com/register?code={user.invite_code}"
    stats = database.get_invite_stats(user.id)
    next_reward = stats.get("next_reward")
    
    message = f"""【邀请链接】
您的专属邀请链接：
{invite_url}

邀请码：{user.invite_code}

已邀请人数：{stats['total_invites']} 人"""
    
    if next_reward:
        message += f"\n\n🎁 再邀请 {next_reward['remaining']} 人即可获得 {next_reward['days']} 天会员！"
    else:
        message += "\n\n🎉 您已完成所有邀请任务！"
    
    return message


def get_invite_stats_message(wechat_id: str) -> str:
    """获取邀请统计消息"""
    user = database.get_user_by_wechat_id(wechat_id)
    if not user:
        return "请先登录账号"
    
    stats = database.get_invite_stats(user.id)
    next_reward = stats.get("next_reward")
    
    message = f"""【邀请统计】
已邀请人数：{stats['total_invites']} 人
有效邀请数：{stats['valid_invites']} 人"""
    
    if next_reward:
        message += f"\n\n🎁 邀请奖励进度："
        message += f"\n再邀请 {next_reward['remaining']} 人可获得 {next_reward['days']} 天会员"
        from config import INVITE_REWARDS
        for threshold, days in INVITE_REWARDS.items():
            if stats['total_invites'] < threshold:
                message += f"\n• 邀请 {threshold} 人 → {days} 天"
                break
    
    return message
