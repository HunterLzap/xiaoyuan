"""统一系统提示构造。

顺序固定：助手提示词 -> 内置规则(当前时间+诚实 / 语音朗读规范 / 工具规则) -> 本轮状态。
内置规则放后面只是“优先级与可读性”更好，并不构成对模型的硬约束；
权限、真实执行、设备回读、当前时间等仍由代码强制，不依赖模型遵守提示。
"""
from __future__ import annotations

from .prompt_context import context_instruction, now_context_line
from .speech_text import SPEECH_OUTPUT_INSTRUCTION
from .tool_dialogue import BUILTIN_TOOL_NAMES, build_tool_instructions


def build_system_prompt(settings, channel="text", tool_names=None, turn_state=None,
                        assistant_prompt=None, compact=False) -> str:
    """拼一条完整系统提示。

    channel: "voice" 追加语音朗读规范；"text" 不追加。
    tool_names: 本轮工具名称范围；按实际能力追加规则，空集合明确禁止工具调用。
    turn_state: 本轮附加状态（控制历史/所需工具等）。
    assistant_prompt: 覆盖助手提示词（默认取 settings.system_prompt）。
    """
    parts = []
    compact = compact and channel == "text" and set(tool_names or ()) <= BUILTIN_TOOL_NAMES
    base = assistant_prompt if assistant_prompt is not None else (getattr(settings, "system_prompt", "") or "")
    if base:
        parts.append(base)
    profile = (getattr(settings, "agent_profile", "") or "").strip() if settings is not None else ""
    if profile:
        parts.append("\n个人工作档案与偏好：\n" + profile)
    parts.append(
        "\n" + now_context_line() +
        "\n时效事实只依据本轮成功工具结果并说明数据时间；缺依据就说明无法获取，不猜数值。"
        "日期时间直接用上述北京时间，非实时常识正常回答。"
        if compact else context_instruction())
    if channel == "voice":
        parts.append(SPEECH_OUTPUT_INSTRUCTION)
    parts.append(build_tool_instructions(tool_names, channel, compact=compact))
    if tool_names is not None and not compact:
        parts.append("\n再次强调：结合当前问题和有效对话上下文，判断用户是否有具体的查询或控制需求；"
                     "遇到省略式追问（如“明天呢？”“发货了吗？”）要结合上一轮意图判断，不要当成闲聊。")
        if channel != "voice":
            parts.append("纯寒暄、闲聊、情绪表达不为找话题而自行调用工具。")
    if turn_state:
        state = str(turn_state)
        parts.append(state if state.startswith("\n") else "\n" + state)
    return "".join(parts)
