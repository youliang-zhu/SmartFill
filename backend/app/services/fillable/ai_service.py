"""
AI 服务 - 通义千问字段匹配
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, List

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger("app.services.fillable.ai_service")


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
    """通义千问服务实现（OpenAI 兼容模式）"""
    
    # 系统 Prompt：指导 AI 进行字段匹配
    SYSTEM_PROMPT = "你是一个 PDF 表单填写助手，擅长将用户提供的信息准确匹配到表单字段中。"
    
    # 用户 Prompt 模板
    USER_PROMPT_TEMPLATE = """任务：将用户提供的信息匹配到 PDF 表单的字段中。

PDF 表单字段列表：
{fields_json}

用户提供的信息：
{user_info}

要求：
1. 将用户信息准确匹配到对应的字段
2. 只使用上面列出的字段名作为 key
3. 无法匹配的字段，值设为空字符串 ""
4. 直接输出 JSON，不要包含其他文字
5. 所有值都是字符串类型

输出格式示例：
{{"姓名": "张三", "电话": "13800138000", "地址": ""}}"""
    
    def __init__(self, api_key: str, model: str = "qwen-turbo", base_url: str = ""):
        """
        初始化通义千问服务
        
        Args:
            api_key: API 密钥
            model: 模型名称
            base_url: API 基础 URL（OpenAI 兼容模式）
        """
        self.model = model
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
    
    def _build_prompt(self, fields: List[str], user_info: str) -> str:
        """
        构建用户 Prompt
        
        Args:
            fields: 表单字段列表
            user_info: 用户输入信息
        
        Returns:
            格式化后的 Prompt 字符串
        """
        fields_json = json.dumps(fields, ensure_ascii=False, indent=2)
        return self.USER_PROMPT_TEMPLATE.format(
            fields_json=fields_json,
            user_info=user_info,
        )
    
    @staticmethod
    def _parse_response(content: str) -> Dict[str, str]:
        """
        解析 AI 返回的 JSON 内容
        
        尝试直接解析，如果失败则清理 markdown 代码块标记后重试。
        
        Args:
            content: AI 返回的原始文本
        
        Returns:
            解析后的字段映射字典
        
        Raises:
            ValueError: JSON 解析失败
        """
        text = content.strip()
        
        # 尝试直接解析
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return {str(k): str(v) for k, v in result.items()}
        except json.JSONDecodeError:
            pass
        
        # 清理 markdown 代码块标记后重试
        if "```" in text:
            # 移除 ```json ... ``` 或 ``` ... ``` 包裹
            lines = text.split("\n")
            cleaned_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("```"):
                    continue
                cleaned_lines.append(line)
            text = "\n".join(cleaned_lines).strip()
        
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return {str(k): str(v) for k, v in result.items()}
            raise ValueError("AI 返回的不是 JSON 对象")
        except json.JSONDecodeError as e:
            raise ValueError(f"AI 返回格式异常，无法解析 JSON: {e}")
    
    async def match_fields(
        self,
        fields: List[str],
        user_info: str
    ) -> Dict[str, str]:
        """
        使用通义千问进行字段匹配
        
        Args:
            fields: PDF 表单字段名称列表
            user_info: 用户自然语言输入的信息
        
        Returns:
            字段名到填写值的映射
        
        Raises:
            ConnectionError: API 调用失败（网络/认证问题）
            TimeoutError: API 调用超时
            ValueError: AI 返回格式异常
        """
        prompt = self._build_prompt(fields, user_info)
        
        # 记录请求开始和完整输入
        logger.info("=" * 60)
        logger.info(f"[请求开始] 模型: {self.model}，字段数: {len(fields)}")
        logger.info(f"[PDF 字段列表] {json.dumps(fields, ensure_ascii=False)}")
        logger.info(f"[用户输入] {user_info}")
        logger.debug(f"[完整 Prompt]\n{prompt}")
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # 低温度，提高输出一致性
                timeout=30,  # 30 秒超时
            )
        except Exception as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                logger.error(f"[AI 超时] {error_msg}")
                raise TimeoutError("处理超时，请稍后重试")
            logger.error(f"[AI 调用失败] {error_msg}")
            raise ConnectionError(f"AI 服务暂时不可用，请稍后重试: {error_msg}")
        
        # 提取返回内容
        content = response.choices[0].message.content
        if not content:
            logger.error("[AI 输出] 返回内容为空")
            raise ValueError("AI 返回内容为空")
        
        logger.info(f"[AI 原始输出]\n{content}")
        
        # 解析 JSON 结果
        result = self._parse_response(content)
        logger.info(f"[JSON 解析结果] {json.dumps(result, ensure_ascii=False)}")
        
        # 过滤：只保留字段列表中存在的 key
        filtered = {k: v for k, v in result.items() if k in fields}
        
        if len(result) != len(filtered):
            lost_keys = set(result.keys()) - set(filtered.keys())
            logger.warning(f"[过滤丢弃] 以下 key 不在 PDF 字段中被丢弃: {lost_keys}")
        
        logger.info(f"[最终匹配] {len(filtered)}/{len(fields)} 个字段已匹配")
        logger.info(f"[最终映射] {json.dumps(filtered, ensure_ascii=False)}")
        logger.info("=" * 60)
        
        return filtered


# 模块级服务实例（延迟初始化）
_ai_service: QwenService | None = None


def get_ai_service() -> QwenService:
    """
    获取 AI 服务单例
    
    从配置中读取 API Key 和模型信息，首次调用时创建实例。
    
    Returns:
        QwenService 实例
    
    Raises:
        ValueError: API Key 未配置
    """
    global _ai_service
    if _ai_service is None:
        settings = get_settings()
        if not settings.QWEN_API_KEY or settings.QWEN_API_KEY == "your_qwen_api_key_here":
            raise ValueError(
                "通义千问 API Key 未配置，请在 .env 文件中设置 QWEN_API_KEY"
            )
        _ai_service = QwenService(
            api_key=settings.QWEN_API_KEY,
            model=settings.QWEN_MODEL,
            base_url=settings.QWEN_BASE_URL,
        )
    return _ai_service
