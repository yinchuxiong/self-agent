"""
SSE 事件编码器 —— 将 ChatEvent 对象转换为 SSE 协议格式的字符串。

SSE（Server-Sent Events）是一种让服务器向浏览器"推送"数据的技术。
与 WebSocket 不同，SSE 是单向的（服务器 → 客户端），但更简单，不需要额外的协议升级。

SSE 协议格式：
    event: <事件类型>\n
    data: <JSON 数据>\n
    \n

本模块只有一个函数：encode_sse()，负责将内部的 ChatEvent 对象
编码为符合 SSE 协议的字符串。

Python 语法要点：
- json.dumps(data, ensure_ascii=False)：将 Python 对象转为 JSON 字符串，
  ensure_ascii=False 保留中文原文，不转义为 \\uXXXX 形式
- event.model_dump(mode="json")：Pydantic v2 的序列化方法，
  将模型转为可 JSON 序列化的 dict（datetime 自动转 ISO 字符串等）
"""

import json

from self_agent.app.core.models import ChatEvent


def encode_sse(event: ChatEvent) -> str:
    """将 ChatEvent 编码为 SSE 协议的文本行。

    Args:
        event: 内部事件对象

    Returns:
        符合 SSE 协议格式的字符串，例如：
        event: agent_started
        data: {"event":"agent_started","trace_id":"...","message":"...","agent":"programming"}

    Python 语法要点：
    - event.model_dump(mode="json")：Pydantic v2 的序列化方法，
      将所有字段转为 JSON 兼容格式（datetime → ISO 字符串，Enum → 值等）
    - json.dumps(..., ensure_ascii=False)：序列化为 JSON 字符串，
      ensure_ascii=False 确保中文不会被转义
    - f-string 中的 \n：换行符，SSE 协议用两个连续的 \n 表示一个事件的结束
    """
    # 将 Pydantic 模型转为字典（确保类型正确转换）
    payload = event.model_dump(mode="json")
    # 构造 SSE 格式的输出：事件类型行 + 数据行 + 空行结束
    return f"event: {event.event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
