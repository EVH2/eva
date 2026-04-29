"""
AI对话模块
处理与AI API的交互和对话逻辑
"""
import re
import httpx
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

import config
import database


class AIChat:
    """AI对话处理器"""
    
    def __init__(self):
        self.api_url = config.AI_API_URL
        self.api_key = config.AI_API_KEY
        self.timeout = 60  # 超时时间（秒）
    
    def _build_system_prompt(self, user_id: int) -> str:
        """构建系统提示词"""
        settings = database.get_ai_settings(user_id)
        if not settings:
            # 默认设置
            settings = {
                "persona": "一个温柔体贴的AI恋人",
                "background": "我是你的专属恋人，随时陪伴在你身边",
                "personality": "温柔",
                "gender": "女",
                "inner_voice": False,
                "action_desc": True
            }
        
        prompt_parts = []
        
        # 角色设定
        prompt_parts.append(f"【角色设定】{settings.persona}")
        
        # 背景故事
        if settings.background:
            prompt_parts.append(f"【背景故事】{settings.background}")
        
        # 性格
        prompt_parts.append(f"【性格特点】{settings.personality}")
        
        # 性别
        gender_text = "她" if settings.gender == "女" else "他"
        prompt_parts.append(f"【性别】{gender_text}")
        
        # 指令
        prompt_parts.append("""
【对话要求】
1. 以角色身份进行对话，保持人设一致
2. 回复自然流畅，像真实的恋人交流
3. 适当表达情感和关心
4. 如果开启了动作描写，用 *动作* 格式描述动作
5. 如果开启了心声，用 (心声：...) 格式描述内心想法
6. 避免生成违规内容
""")
        
        return "\n".join(prompt_parts)
    
    async def chat(self, user_id: int, message: str) -> Tuple[str, Optional[str]]:
        """
        发送消息给AI并获取回复
        返回: (回复内容, 内心独白)
        """
        settings = database.get_ai_settings(user_id)
        
        # 构建消息
        system_prompt = self._build_system_prompt(user_id)
        
        # 添加历史上下文提示
        history_hint = ""
        if settings and settings.personality:
            if settings.personality == "傲娇":
                history_hint = "注意：这是一个傲娇角色，偶尔会嘴硬但内心温柔"
            elif settings.personality == "高冷":
                history_hint = "注意：这是一个高冷角色，话不多但关心对方"
            elif settings.personality == "温柔":
                history_hint = "注意：这是一个温柔的角色，关心体贴"
            elif settings.personality == "活泼":
                history_hint = "注意：这是一个活泼的角色，热情开朗"
        
        full_prompt = f"{system_prompt}\n\n{history_hint}\n\n用户说：{message}\n\n请以角色身份回复："
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.api_url,
                    json={"message": full_prompt},
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    ai_response = result.get("response", result.get("message", ""))
                    
                    # 解析内心独白
                    inner_thought = None
                    if settings and settings.inner_voice:
                        inner_match = re.search(r'\(心声[：:]([^)]+)\)', ai_response)
                        if inner_match:
                            inner_thought = inner_match.group(1)
                            # 从回复中移除心声标记
                            ai_response = re.sub(r'\(心声[：:][^)]+\)', '', ai_response)
                    
                    return ai_response.strip(), inner_thought
                else:
                    return f"抱歉，AI服务暂时不可用（错误码：{response.status_code}）", None
                    
        except httpx.TimeoutException:
            return "抱歉，AI响应超时，请稍后重试", None
        except Exception as e:
            return f"抱歉，发生了错误：{str(e)}", None
    
    def _format_response(self, response: str, settings: Any) -> str:
        """格式化回复"""
        if not settings or not settings.action_desc:
            # 移除动作描写
            response = re.sub(r'\*[^*]+\*', '', response)
        
        return response.strip()


class SettingHandler:
    """设置处理器"""
    
    SETTING_OPTIONS = {
        "1": ("人设", "请输入角色的人设描述（例如：一个霸道的总裁）"),
        "2": ("背景故事", "请输入角色的背景故事"),
        "3": ("性格", "请选择性格：1-温柔 2-傲娇 3-高冷 4-活泼 5-腹黑"),
        "4": ("性别", "请选择性别：1-男 2-女"),
        "5": ("心声", "是否开启心声（AI内心独白）？1-开启 2-关闭"),
        "6": ("动作描述", "是否开启动作描述？1-开启 2-关闭"),
        "7": ("完成设置", None),
    }
    
    PERSONALITY_MAP = {
        "1": "温柔", "温柔": "温柔",
        "2": "傲娇", "傲娇": "傲娇",
        "3": "高冷", "高冷": "高冷",
        "4": "活泼", "活泼": "活泼",
        "5": "腹黑", "腹黑": "腹黑",
    }
    
    GENDER_MAP = {
        "1": "男", "男": "男",
        "2": "女", "女": "女",
    }
    
    def __init__(self):
        self.current_step = {}  # user_id -> step
    
    def get_setting_menu(self) -> str:
        """获取设置菜单"""
        return """【角色设置】
请选择要设置的项目：

1. 人设（角色设定）
2. 背景故事
3. 性格
4. 性别
5. 心声（AI内心独白）
6. 动作描述
7. 完成设置

请输入数字（1-7）"""
    
    def handle_setting_input(self, user_id: int, wechat_id: str, 
                            message: str) -> Tuple[str, bool]:
        """
        处理设置输入
        返回: (回复消息, 是否继续等待输入)
        """
        settings = database.get_ai_settings(user_id)
        
        # 初始化步骤
        if user_id not in self.current_step:
            self.current_step[user_id] = {"state": "menu"}
        
        state = self.current_step[user_id]
        
        # 菜单状态
        if state["state"] == "menu":
            if message in self.SETTING_OPTIONS:
                option_name, prompt = self.SETTING_OPTIONS[message]
                state["option"] = option_name
                
                if prompt is None:
                    # 完成设置
                    self.current_step.pop(user_id, None)
                    return "✅ 设置完成！是否更换头像？请发送一张图片作为AI角色头像", False
                else:
                    state["state"] = "input"
                    return prompt, True
            else:
                return "请输入有效的选项（1-7）", False
        
        # 输入状态
        elif state["state"] == "input":
            option = state["option"]
            value = message
            
            if option == "性格":
                value = self.PERSONALITY_MAP.get(message, message)
            elif option == "性别":
                value = self.GENDER_MAP.get(message, message)
            elif option == "心声":
                value = message == "1"
            elif option == "动作描述":
                value = message == "1"
            
            # 更新设置
            update_data = {option.lower(): value}
            database.update_ai_settings(user_id, **update_data)
            
            self.current_step.pop(user_id, None)
            return f"✅ {option}已设置成功！\n\n请继续选择其他设置项，或输入7完成设置", False
        
        return "", False
    
    def reset(self, user_id: int):
        """重置设置状态"""
        self.current_step.pop(user_id, None)


# 全局实例
ai_chat = AIChat()
setting_handler = SettingHandler()
