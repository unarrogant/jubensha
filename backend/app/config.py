import os

from dotenv import load_dotenv


load_dotenv()


def get_deepseek_config() -> dict[str, str]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")

    return {
        "api_key": api_key,
        "base_url": os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        ),
        "model": os.getenv(
            "DEEPSEEK_MODEL",
            "deepseek-v4-pro",
        ),
        "public_model": os.getenv(
            "DEEPSEEK_PUBLIC_MODEL",
            "deepseek-chat",
        ),
        # DeepSeek 思考模式会要求后续请求完整回传 reasoning_content。
        # 当前 LangGraph 历史消息不保证保留该字段，因此默认关闭，
        # 避免连续私聊或工具调用时触发 400。
        "thinking": os.getenv(
            "DEEPSEEK_THINKING",
            "disabled",
        ),
    }


def get_storage_config() -> dict[str, str]:
    """Read the required hybrid storage URLs from environment variables."""
    return {
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
        "mysql_url": os.getenv("MYSQL_URL", "").strip(),
    }
