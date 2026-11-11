"""会话实时语境：把服务器当前北京时间与“无实时数据不编造”的诚实规则注入系统提示。

每次构造系统提示时调用，日期时间按当下实时计算，不写死。
中国无夏令时，用固定 UTC+8，不依赖 zoneinfo/tzdata。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_BEIJING = timezone(timedelta(hours=8))
_WEEKDAYS = "一二三四五六日"  # Monday=0 .. Sunday=6

# 没有实时数据来源时的诚实约束。
HONESTY_INSTRUCTION = (
    "\n诚实与实时数据规则：天气、空气质量、新闻、股价、比分、汇率等时效信息，"
    "只有本轮已成功调用的工具提供相应地点、日期及数据依据时才能据实回答，并说明数据时间。"
    "没有可用工具或调用未取得有效结果时，必须明确说明当前无法获取该实时数据；"
    "绝不凭模型记忆、角色设定、历史回复或猜测给出实时数值。"
    "被问到日期或时间，以上面提供的当前北京时间为准直接回答，不要回答不知道。"
    "常识性、非实时的问题正常回答即可。"
)


def beijing_now(now: datetime | None = None) -> datetime:
    return now.astimezone(_BEIJING) if now is not None else datetime.now(_BEIJING)


def now_context_line(now: datetime | None = None) -> str:
    moment = beijing_now(now)
    weekday = _WEEKDAYS[moment.weekday()]
    return (f"现在是北京时间{moment.year}年{moment.month}月{moment.day}日 "
            f"星期{weekday} {moment.hour:02d}:{moment.minute:02d}。")


def context_instruction(now: datetime | None = None) -> str:
    """当前时间 + 诚实规则，供各系统提示拼接。"""
    return "\n" + now_context_line(now) + HONESTY_INSTRUCTION
