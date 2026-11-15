"""语音朗读文本规范化。

把任何要“读出来”的文本整理成适合朗读的口语稿：
- 破折号 ——/— → 停顿；波浪号 ~/～ 去掉；/ → “或”；_ → 空格；
- 去掉 [ ] 【 】 ( ) # * ` 等符号；
- 日期 YYYY-MM-DD → YYYY年M月D日；区间 a-b → a到b；百分比 N% → 百分之N；
- 小数用中文口语（1.4 → 一点四）。

只做“朗读副本”，不改动原始结构化数据：工具返回值交给模型时，
原始字段保持原样，另附 speech_text 规范化副本供朗读。
"""
from __future__ import annotations

import json
import re

_CN_DIGITS = "零一二三四五六七八九"

# 强化播报指令：realtime 与非实时文本/TTS 共用。
SPEECH_OUTPUT_INSTRUCTION = (
    "\n语音播报规范：你的回答会被直接朗读，必须是适合朗读的口语。"
    "回答文本里不要出现破折号、波浪号、斜杠、下划线、方括号、星号、反引号、井号等符号字符"
    "（—— — ~ ～ / _ [ ] 【 】 # * ` 都不许出现），需要停顿就用逗号或句号。"
    "也不要在口中念出“横杠、破折号、波浪号、斜杠、下划线、方括号、星号”等任何符号名称。"
    "日期读作“X年X月X日”，区间用“到”，百分比读作“百分之X”，小数和数字用自然中文口语。"
    "即使角色设定里带有～等符号，输出文本和朗读时都不要出现或念出该符号。"
    "\n回答完成要求：简短、口语化是表达方式，不是省略用户要求的正文。"
    "首句承接之后，必须在同一次回答中紧接实际内容，不等待用户再叫名字或说继续。"
    "讲故事、报数或朗读时，用正文开头作为首响，第一句直接交付内容，不另说稍后开始。"
    "用户要求讲故事时直接讲完整故事，有开头、经过和结尾；要求约一分钟时按该长度展开。"
    "要求报数或朗读时按要求的范围连续完成，不能只说好呀、这就开始或给你讲一个故事后结束。"
    "同一次回答只承接一次；长内容分句继续，不重新开场、不从头重复。用户插话时立即停止旧内容。"
)


def _int_to_cn(n: int) -> str:
    if n < 0:
        return "负" + _int_to_cn(-n)
    if n == 0:
        return "零"
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n - 10] if n > 10 else "")
    if n < 100:
        tens, ones = divmod(n, 10)
        return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = _CN_DIGITS[hundreds] + "百"
        if rest == 0:
            return head
        if rest < 10:
            return head + "零" + _CN_DIGITS[rest]
        return head + _int_to_cn(rest)
    if n < 10000:
        thousands, rest = divmod(n, 1000)
        head = _CN_DIGITS[thousands] + "千"
        if rest == 0:
            return head
        return head + ("零" if rest < 100 else "") + _int_to_cn(rest)
    ten_thousands, rest = divmod(n, 10000)
    head = _int_to_cn(ten_thousands) + "万"
    if rest == 0:
        return head
    return head + ("零" if rest < 1000 else "") + _int_to_cn(rest)


def _num_to_cn(token: str) -> str:
    """'80' -> 八十；'1.4' -> 一点四；'100' -> 一百。"""
    token = token.strip()
    if "." in token:
        whole, frac = token.split(".", 1)
        whole_part = _int_to_cn(int(whole)) if whole else "零"
        return whole_part + "点" + "".join(_CN_DIGITS[int(d)] for d in frac if d.isdigit())
    return _int_to_cn(int(token))


def _percent(match: "re.Match[str]") -> str:
    token = match.group(1)
    try:
        if float(token) == 100:
            return "百分之百"
    except ValueError:
        pass
    return "百分之" + _num_to_cn(token)


def normalize_for_speech(text: str) -> str:
    """把文本整理成可直接朗读的口语稿。空输入原样返回。"""
    if not text:
        return text
    t = str(text)

    # 0) 朗读稿不念链接：先去掉 http(s) 链接
    t = re.sub(r"https?://\S+", "", t)

    # 1) 日期：YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD -> YYYY年M月D日（先于区间处理）
    t = re.sub(
        r"(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})",
        lambda m: f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日",
        t,
    )

    # 2) 区间：a-b / a~b / a—b -> a到b（在两个数字之间）
    t = re.sub(r"(\d+(?:\.\d+)?)\s*[-–—~～]\s*(\d+(?:\.\d+)?)", r"\1到\2", t)

    # 3) 百分比：百分之N / N% -> 百分之N（中文）
    t = re.sub(r"百分之\s*(\d+(?:\.\d+)?)", _percent, t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*[%％]", _percent, t)

    # 4) 破折号 -> 停顿
    t = re.sub(r"[—–]{1,}", "，", t)
    t = t.replace("--", "，")

    # 5) 波浪号去掉
    t = re.sub(r"[~～]+", "", t)

    # 6) 斜杠 -> 或
    t = t.replace("/", "或")

    # 7) 下划线 -> 空格
    t = t.replace("_", " ")

    # 8) 去掉成对/装饰符号（保留其中的文字）
    t = re.sub(r"[\[\]【】()（）<>{}\\#*`|^]", "", t)

    # 9) 字母之间的连字符（如 e-mail、GPT-4）去掉，避免念成“横杠”；不影响数字/负数
    t = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z0-9])", "", t)

    # 10) 其余小数用中文口语（1.4 -> 一点四），不影响版本号形式 1.4.0
    t = re.sub(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])", lambda m: _num_to_cn(m.group(0)), t)

    # 11) 空白与标点收尾
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    t = re.sub(r"([，。！？；：、])\s+", r"\1", t)
    return t.strip()


def tool_output_speech_copy(output) -> str | None:
    """从工具返回值中抽取“可朗读”的正文，返回规范化副本；没有可读正文时返回 None。

    只抽取知识库命中的 excerpt / m5stack 参考正文等，不读文档ID、版本、链接等内部字段。
    """
    if not isinstance(output, dict):
        return None
    parts: list[str] = []
    for match in output.get("matches") or []:
        if not isinstance(match, dict):
            continue
        excerpt = match.get("excerpt") or match.get("text") or match.get("content")
        if isinstance(excerpt, str) and excerpt.strip():
            parts.append(excerpt.strip())
    reference = output.get("reference_data")
    if isinstance(reference, dict):
        for key in ("answer", "content", "text", "summary", "description", "型号", "说明"):
            value = reference.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    if not parts:
        return None
    return normalize_for_speech("\n".join(parts))


def function_call_output_payload(output) -> str:
    """组装发给模型的 function_call_output 字符串。

    原始数据字段原样保留；只在有可读正文时额外附加 speech_text 朗读副本，
    并提示模型朗读时以 speech_text 为准，避免日期/数字/符号读错。
    """
    if not isinstance(output, dict):
        return json.dumps(output, ensure_ascii=False)
    payload = dict(output)
    speech = tool_output_speech_copy(output)
    if speech:
        payload["speech_text"] = speech
        payload["speech_hint"] = ("朗读工具结果时以 speech_text 为准：日期按年月日、区间用‘到’、"
                                  "百分比读‘百分之X’、数字用中文口语，不要念出任何符号。")
    return json.dumps(payload, ensure_ascii=False)
