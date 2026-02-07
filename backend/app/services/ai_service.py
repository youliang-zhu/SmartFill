"""
AI 服务抽象接口（预留）
"""
from abc import ABC, abstractmethod
from typing import Dict, List


class AIService(ABC):
    """AI 服务抽象基类"""
    
    @abstractmethod
    async def match_fields(
        self,
        fields: List[str],
        user_info: str
    ) -> Dict[str, str]:
        """
        将用户信息与表单字段进行匹配
        
        Args:
            fields: 表单字段列表
            user_info: 用户输入的信息
        
        Returns:
            字段名到值的映射
        """
        pass


class QwenService(AIService):
    """通义千问服务实现（预留）"""
    
    def __init__(self, api_key: str, model: str = "qwen-plus"):
        self.api_key = api_key
        self.model = model
    
    async def match_fields(
        self,
        fields: List[str],
        user_info: str
    ) -> Dict[str, str]:
        """
        使用通义千问进行字段匹配
        
        TODO: 在后续版本实现
        """
        # 预留实现
        raise NotImplementedError("AI 服务将在后续版本实现")


# 工厂函数
def get_ai_service(api_key: str, model: str = "qwen-plus") -> AIService:
    """获取 AI 服务实例"""
    return QwenService(api_key=api_key, model=model)
