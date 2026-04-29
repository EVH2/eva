"""
微信机器人模块
基于 itchat 实现微信消息接收和回复
"""
import os
import re
import threading
from typing import Optional

import itchat
from itchat.content import TEXT, IMAGE, MAP, CARD, NOTE, SHARING, PICTURE, VIDEO, RECORDING, ATTACHMENT

import config
import database
import user_system
from ai_chat import ai_chat, setting_handler


class WeChatBot:
    """微信机器人"""
    
    def __init__(self):
        self.running = False
        self.bot = None
        
        # 命令处理映射
        self.commands = {
            "/菜单": self._cmd_menu,
            "/设置": self._cmd_settings,
            "/使用时间": self._cmd_usage,
            "/对话多少句": self._cmd_dialog_count,
            "/邀请用户链接生成": self._cmd_invite_link,
            "/已邀请多少人": self._cmd_invite_stats,
            "/充值": self._cmd_recharge,
            "/官方dy号": self._cmd_dy,
        }
    
    def _get_user_status(self, wechat_id: str) -> dict:
        """获取用户状态"""
        return user_system.get_user_status(wechat_id)
    
    def _process_register(self, msg, user_status: dict) -> str:
        """处理注册"""
        valid, data, error = user_system.validate_register_format(msg.text)
        if not valid:
            return error
        
        success, result_msg, user_id = user_system.register_user(
            data["username"],
            data["password"],
            data["email"]
        )
        
        if success:
            # 自动登录
            wechat_id = msg.fromUserName
            database.update_user_wechat_id(user_id, wechat_id)
            
            # 返回登录成功信息和帮助
            welcome = f"✅ {result_msg}\n\n"
            welcome += "🎉 您已获得7天免费试用时间！\n\n"
            welcome += user_system.get_help_message()
            return welcome
        
        return result_msg
    
    def _process_login(self, msg, user_status: dict) -> str:
        """处理登录"""
        valid, data, error = user_system.validate_login_format(msg.text)
        if not valid:
            return error
        
        wechat_id = msg.fromUserName
        success, result_msg, token = user_system.login_user(
            data["username"],
            data["password"],
            wechat_id
        )
        
        if success:
            result_msg += "\n\n" + user_system.get_help_message()
        
        return result_msg
    
    async def _process_ai_chat(self, msg, user_id: int) -> str:
        """处理AI对话"""
        # 增加对话计数
        database.increment_dialog_count(user_id)
        
        # 调用AI
        response, inner_thought = await ai_chat.chat(user_id, msg.text)
        
        # 保存对话记录
        database.save_chat_log(user_id, msg.text, response)
        
        # 如果有内心独白，附加在回复后
        if inner_thought:
            response = f"{response}\n\n（心想：{inner_thought}）"
        
        return response
    
    async def _handle_message(self, msg):
        """处理接收到的消息"""
        # 忽略群消息和公众号消息
        if msg["ToUserName"] == "filehelper":
            return
        
        # 获取用户状态
        wechat_id = msg.fromUserName
        user_status = self._get_user_status(wechat_id)
        
        # 检查是否是命令
        text = msg.text.strip() if msg.type == TEXT else ""
        
        # 检查命令
        for cmd, handler in self.commands.items():
            if text == cmd or text.startswith(cmd + " "):
                await handler(msg, user_status)
                return
        
        # 处理不同状态的消息
        if user_status["status"] == "not_bound":
            # 检查是否是注册格式
            if "/" in text:
                parts = text.split("/")
                if len(parts) >= 2:
                    # 尝试作为注册或登录处理
                    if len(parts) == 3 and "@" in parts[2]:
                        response = self._process_register(msg, user_status)
                    else:
                        response = self._process_login(msg, user_status)
                    self._send_reply(msg, response)
                    return
            
            self._send_reply(msg, user_status["message"])
            return
        
        elif user_status["status"] == "expired":
            self._send_reply(msg, user_status["message"])
            return
        
        elif user_status["status"] == "banned":
            self._send_reply(msg, user_status["message"])
            return
        
        elif user_status["status"] == "active":
            # 检查是否在设置模式
            if hasattr(msg, '_in_setting_mode') and msg._in_setting_mode:
                response, _ = setting_handler.handle_setting_input(
                    user_status["user_id"],
                    wechat_id,
                    text
                )
                if response:
                    self._send_reply(msg, response)
                    msg._in_setting_mode = False
                return
            
            # AI对话
            response = await self._process_ai_chat(msg, user_status["user_id"])
            self._send_reply(msg, response)
    
    def _send_reply(self, msg, content: str):
        """发送回复"""
        try:
            msg.reply(content)
        except Exception as e:
            print(f"发送消息失败: {e}")
    
    async def _cmd_menu(self, msg, user_status: dict):
        """菜单命令"""
        if user_status["status"] != "active":
            self._send_reply(msg, user_status.get("message", "请先登录"))
            return
        
        self._send_reply(msg, user_system.get_help_message())
    
    async def _cmd_settings(self, msg, user_status: dict):
        """设置命令"""
        if user_status["status"] != "active":
            self._send_reply(msg, user_status.get("message", "请先登录"))
            return
        
        menu = setting_handler.get_setting_menu()
        self._send_reply(msg, menu)
        msg._in_setting_mode = True
    
    async def _cmd_usage(self, msg, user_status: dict):
        """使用时间命令"""
        if user_status["status"] != "active":
            self._send_reply(msg, user_status.get("message", "请先登录"))
            return
        
        info = user_system.get_usage_info(msg.fromUserName)
        self._send_reply(msg, info)
    
    async def _cmd_dialog_count(self, msg, user_status: dict):
        """对话句数命令"""
        if user_status["status"] != "active":
            self._send_reply(msg, user_status.get("message", "请先登录"))
            return
        
        info = user_system.get_usage_info(msg.fromUserName)
        self._send_reply(msg, info)
    
    async def _cmd_invite_link(self, msg, user_status: dict):
        """邀请链接命令"""
        if user_status["status"] != "active":
            self._send_reply(msg, user_status.get("message", "请先登录"))
            return
        
        link = user_system.get_invite_link(msg.fromUserName)
        self._send_reply(msg, link)
    
    async def _cmd_invite_stats(self, msg, user_status: dict):
        """邀请统计命令"""
        if user_status["status"] != "active":
            self._send_reply(msg, user_status.get("message", "请先登录"))
            return
        
        stats = user_system.get_invite_stats_message(msg.fromUserName)
        self._send_reply(msg, stats)
    
    async def _cmd_recharge(self, msg, user_status: dict):
        """充值命令"""
        message = """【充值会员】
充值系统正在开发中，敬请期待！

当前支持的套餐：
• 基础版 - ¥29/30天
• 高级版 - ¥79/90天  
• 永久版 - ¥199/永久

📢 官方抖音：xy07s
关注抖音获取最新资讯和优惠信息！"""
        self._send_reply(msg, message)
    
    async def _cmd_dy(self, msg, user_status: dict):
        """抖音命令"""
        message = """📢 官方抖音号：xy07s
快手同步更新中～

点击复制链接：
xy07s

搜索即可关注，获取最新资讯和福利活动！"""
        self._send_reply(msg, message)
    
    def _handle_image(self, msg):
        """处理图片消息"""
        if msg.type != PICTURE:
            return
        
        user_status = self._get_user_status(msg.fromUserName)
        if user_status["status"] != "active":
            return
        
        # 下载图片
        img = msg.download(msg.id)
        
        # 这里可以保存图片并设置头像
        # 简化处理：直接返回提示
        avatar_dir = config.AVATAR_DIR
        avatar_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存图片
        filename = f"{user_status['user_id']}_avatar.jpg"
        filepath = avatar_dir / filename
        
        try:
            with open(filepath, 'wb') as f:
                f.write(img)
            
            # 更新用户头像
            avatar_url = f"/uploads/avatars/{filename}"
            database.update_ai_settings(user_status["user_id"], avatar_url=avatar_url)
            
            self._send_reply(msg, "✅ 头像已更新成功！")
        except Exception as e:
            self._send_reply(msg, f"头像设置失败：{str(e)}")
    
    def _setup_handlers(self):
        """设置消息处理器"""
        # 文本消息
        @itchat.msg_register(TEXT, isFriendChat=True, isMpChat=True)
        def text_handler(msg):
            # 在新线程中处理异步逻辑
            threading.Thread(target=self._async_wrapper, args=(msg,)).start()
        
        # 图片消息
        @itchat.msg_register(PICTURE, isFriendChat=True)
        def image_handler(msg):
            self._handle_image(msg)
        
        # 首次消息
        @itchat.msg_register(TEXT, isFriendChat=True)
        def first_msg_handler(msg):
            pass  # 已在上方处理
    
    def _async_wrapper(self, msg):
        """异步包装器"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._handle_message(msg))
        finally:
            loop.close()
    
    def login(self):
        """登录微信"""
        print("正在登录微信...")
        
        # 生成二维码
        itchat.auto_login(
            hotReload=True,
            qrCallback=self._qr_callback,
            statusStorageDir=config.WECHAT_CACHE_DIR
        )
        
        print("微信登录成功！")
        self.running = True
    
    def _qr_callback(self, uuid, status, qrcode):
        """二维码回调"""
        if status == '0':
            print("请扫描二维码登录...")
            with open(config.WECHAT_QR_PATH, 'wb') as f:
                f.write(qrcode)
            print(f"二维码已保存到: {config.WECHAT_QR_PATH}")
    
    def run(self):
        """运行机器人"""
        self.login()
        self._setup_handlers()
        itchat.run(blockThread=True)


def start_bot():
    """启动机器人"""
    bot = WeChatBot()
    bot.run()


if __name__ == "__main__":
    start_bot()
