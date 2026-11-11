"""订单编号确认闭环（服务端强制，跨轮）。

为什么需要：语音识别可能把订单号读成“B H一千零一”，模型也可能按工具描述样例把它猜成
“PH1001”。仅靠提示词无法保证不查询错误编号，所以真正的执行约束放在 TurnTools 里：
- 模型请求的订单号若不能按用户原话中连续写出的“字母+四位数字”无歧义核对（字母分写、
  中文数字、空格或前缀不同都算有疑义），就不执行查询，返回确认问题，并在会话里记下候选编号。
- 下一轮用户明确回答“是/对/没错”等，才允许按该候选编号查询；回答“不是/不对/错了”
  则本轮把该候选记为已否认，不把旧候选当确认；用户更正的新编号仍须能从其话中读出。
- 状态按 session_id 隔离，新会话没有旧会话的待确认状态。

这里只做状态与文本判断，不执行网络请求；执行拦截在 tool_dialogue.TurnTools。
"""
from __future__ import annotations

import re
import unicodedata

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_RUN = re.compile(r"[零〇一二两三四五六七八九十百千]+")
# 只在用户原话里连续写出“字母+四位数字”时才算无歧义；中间夹空格/中文数字（B H一千零一）一律先复述确认。
_EXPLICIT_ORDER_ID = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,4}\s*\d{4}(?![A-Za-z0-9])")
# 仅在订单工具已选用时用于生成本轮动态提示；不是全局意图分类器。
_ORDER_INTENT = re.compile(r"(?:订单|单号|order|发货|物流)", re.I)

# 订单号本身就是“字母前缀 + 数字”，用户原话常带空格、横杠、全角或中文数字。
_UNCERTAIN = re.compile(r"(?:应该|可能|大概|也许|或许|好像|似乎|不确定|不清楚|记不清|不知道|吧|吗|呢)")
_WAIT = re.compile(r"(?:再想想|再想|我想想|我看看|看一下|等我|稍等|再说|考虑|商量|查一下|问一下|核对一下|核对下|确认一下|另一个|另一个订单|别的订单|其他订单)")
_QUOTE = re.compile(r"(?:资料|文档|里面|提到|引用|写着|记录|原文)")
_YES = re.compile(r"^(?:嗯+|是(?!否|不)|对(?!不对)|好|可以|没错|正确|确认|没问题|没毛病|就这个|就是这个|按这个)")
_NO = re.compile(r"(?<!是)不是|不对(?!对)|错了|说错|不正确|不要|不用|不查|别查")


def _cn_run_to_digits(match: re.Match[str]) -> str:
    """把订单号上下文里的中文数字转成阿拉伯数字。

    只在紧邻 ASCII 字母/数字时转换（如 PH一零零一、B H一千零一），避免把“查一下”
    里的“一”当成订单号数字；没有字母前缀的中文数字无法确认前缀，保留原样让调用方
    走“请用户确认”而不是猜成 PH。
    """
    text = match.string
    index = match.start() - 1
    while index >= 0 and text[index] in " \t\r\n-—－/":
        index -= 1
    previous = text[index] if index >= 0 else ""
    if not (previous.isascii() and previous.isalnum()):
        return match.group(0)
    token = match.group(0)
    if any(unit in token for unit in _CN_UNITS):
        total = num = 0
        seen = False
        for char in token:
            if char in _CN_DIGITS:
                num, seen = _CN_DIGITS[char], True
            elif char in _CN_UNITS:
                total += (num or 1) * _CN_UNITS[char]
                num, seen = 0, True
            else:
                return token
        return str(total + num) if seen else token
    digits = "".join(str(_CN_DIGITS[char]) for char in token if char in _CN_DIGITS)
    return digits or token


def normalize_order_text(text: str) -> str:
    """订单号/用户话的归一化：全角转半角、中文数字转阿拉伯、只保留 a-z0-9。"""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = _CN_RUN.sub(_cn_run_to_digits, normalized)
    return "".join(char.lower() for char in normalized if char.isascii() and char.isalnum())


def is_grounded(question: str, order_id: str) -> bool:
    """订单号是否能在用户当前这句话中直接读出（去空格/符号、中文数字转阿拉伯后的宽松判断）。"""
    candidate = normalize_order_text(order_id)
    if not candidate:
        return False
    text = normalize_order_text(question)
    # 完整 token 匹配：PH1001 不能从 PH10010 或 XPH1001 中“截”出来。
    return re.search(r"(?<![a-z0-9])" + re.escape(candidate) + r"(?![a-z0-9])", text) is not None


def explicit_order_tokens(text: str) -> set[str]:
    """用户原话里连续写出的“字母+四位数字”订单号 token（不做中文数字/分写归一）。"""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return {normalize_order_text(match.group(0)) for match in _EXPLICIT_ORDER_ID.finditer(normalized)}


def is_explicit_order_id(question: str, order_id: str) -> bool:
    """无歧义直查条件：用户原话恰好明确写出一个与候选一致的订单号。

    像“B H 一千零一”这种字母分写、中文数字或中间有空格的情况不满足，必须走复述确认，
    不能靠把 B 猜成 P 或把中文数字当已确认来直接查询。
    """
    candidate = normalize_order_text(order_id)
    if not candidate:
        return False
    tokens = explicit_order_tokens(question)
    return len(tokens) == 1 and tokens == {candidate}


def classify_reply(text: str) -> str:
    """把用户对确认问题的回答分成 confirm / deny / other。"""
    normalized = re.sub(r"[\s。.!！，,、~～…]", "", str(text or ""))
    if not normalized:
        return "other"
    # 犹豫/不确定修饰优先于“嗯/是”前缀：例如“嗯……应该是吧”“可能是”“不是吗”都不放行。
    if _UNCERTAIN.search(normalized):
        return "other"
    if _WAIT.search(normalized):
        return "other"
    if _QUOTE.search(normalized):
        return "other"
    if normalized in {"否", "不"} or _NO.search(normalized):
        return "deny"
    if _YES.search(normalized):
        return "confirm"
    return "other"


def order_like_tokens(text: str) -> set[str]:
    """从用户话里提取疑似订单号 token（字母前缀 + 至少三位数字）。"""
    return set(re.findall(r"[a-z]{1,3}\d{3,}", normalize_order_text(text)))


def order_related(text: str) -> bool:
    """本轮问题是否落在订单查询语义内；只用于订单工具已选用的动态提示。"""
    raw = str(text or "")
    return bool(_ORDER_INTENT.search(raw)) or bool(order_like_tokens(raw))


def choose_order_candidate(question: str, model_candidate: str) -> tuple[str, str]:
    """绑定候选来源：用户原话恰有一个订单 token 时优先用它，而不是模型的猜测。

    返回 (display, source)：source 为 user_token / model_candidate / multiple_user_tokens。
    display 不做 B→P 之类的改写；用户说 bh1001 就显示 BH1001。
    """
    tokens = sorted(order_like_tokens(question))
    explicit = explicit_order_tokens(question)
    if len(tokens) == 1 and (not explicit or tokens[0] == normalize_order_text(model_candidate)):
        return tokens[0].upper(), "user_token"
    normalized = normalize_order_text(model_candidate)
    display = (normalized or str(model_candidate or "").strip()).upper()
    return display, ("multiple_user_tokens" if tokens else "model_candidate")


def should_guard_order(question: str, allowed_tools) -> bool:
    """实时语音首响应 guard 的进入条件：订单工具已选 + 订单语义 + 无单一显式完整编号。"""
    names = set(allowed_tools or ())
    if "retail_query_recent_order" not in names:
        return False
    if not order_related(question):
        return False
    return len(explicit_order_tokens(question)) != 1


class RealtimeOrderGuard:
    """实时语音订单首响应 guard 的纯状态。

    active 时，首响应的文字/音频先进入 RealtimeTurn 的 held_text/pending_audio；
    blocked/denied 丢弃这段错误首响应，ok/无工具调用按原序释放。不产生模型请求。
    """

    def __init__(self):
        self.active = False
        self.early_output = False
        self.discarded = False
        self.discarded_text_chars = 0
        self.discarded_audio_bytes = 0

    def reset_turn(self):
        self.active = False
        self.early_output = False
        self.discarded = False
        self.discarded_text_chars = 0
        self.discarded_audio_bytes = 0

    def begin(self, question: str, allowed_tools) -> bool:
        self.active = should_guard_order(question, allowed_tools)
        return self.active

    def note_early_output(self):
        """转写完成前已有输出；记录，不能追回，不静默。"""
        self.early_output = True

    def mark_discarded(self, text_chars: int, audio_bytes: int) -> None:
        self.discarded = True
        self.discarded_text_chars += max(0, int(text_chars))
        self.discarded_audio_bytes += max(0, int(audio_bytes))

    def finish_tool_outputs(self, outputs) -> str:
        if not self.active:
            return "none"
        blocked = any(isinstance(item, dict) and item.get("error") in
                      ("order_confirmation_required", "order_confirmation_denied")
                      for item in outputs)
        self.active = False
        self.discarded = blocked
        return "discard" if blocked else "release"

    def finish_without_tools(self) -> str:
        if not self.active:
            return "none"
        self.active = False
        return "release"


def _previous_assistant_candidate(history) -> str | None:
    """仅从紧邻的上一轮助手消息里取出“明确确认问句”的候选订单号。

    收紧条件（避免任意历史含订单号或模型自编记录被当成真确认）：
    - history 最后一条必须是 assistant（即上一轮真实发给用户的回答）；
    - 整条回答必须是确认问句，而不是长文里顺带提到订单号；
    - 问句必须以问号结尾，候选格式为字母前缀+至少三位数字。
    """
    messages = list(history or ())
    if not messages:
        return None
    last = messages[-1]
    role = last.get("role") if isinstance(last, dict) else getattr(last, "role", None)
    if role != "assistant":
        return None
    content = (last.get("content") if isinstance(last, dict) else getattr(last, "content", "")) or ""
    match = re.fullmatch(
        r"\s*(?:(?:好的|嗯|请问|请确认|请核对)[，,：:\s]*)?(?:你说的)?订单号\s*(?:是不是|是否为)\s*"
        r"([A-Za-z]{1,4}\s*\d{3,})\s*(?:这样)?\s*[？?]\s*[。！!]?\s*",
        content)
    return match.group(1).strip() if match else None


class OrderConfirmationStore:
    """按会话保存待确认订单号；跨轮有效，新会话隔离。"""

    def __init__(self):
        self._pending: dict[str, str] = {}
        self._last_turn: dict[str, str] = {}
        self._turn_confirmed: dict[str, str] = {}
        self._turn_denied: dict[str, dict[str, str]] = {}

    @staticmethod
    def _key(session_id, turn_id) -> str:
        return f"{session_id}|{turn_id}"

    def begin_turn(self, session_id, turn_id, question: str, history=None) -> dict:
        """开启新一轮：消化上一轮留下的待确认候选（确认/否认/过期）。"""
        sid, tid = str(session_id), str(turn_id)
        if self._last_turn.get(sid) == tid:
            return self.turn_state(sid, tid)
        self._last_turn[sid] = tid
        pending = self._pending.pop(sid, None)
        if pending is None and history:
            # 模型自己先问了“订单号是不是 PH1001？”，待确认状态不在内存时从上一轮助手问句恢复；
            # 只接受“是/不是”这类明确回答，避免把普通对话误当作确认。
            if classify_reply(question) in ("confirm", "deny"):
                pending = _previous_assistant_candidate(history)
        if pending:
            reply = classify_reply(question)
            pending_norm = normalize_order_text(pending)
            supplied = order_like_tokens(question)
            if reply == "confirm" and supplied and pending_norm not in supplied:
                # “是 PH1002”这类带新编号的回答是更正，不是确认旧候选。
                reply = "other"
            if reply == "confirm":
                self._turn_confirmed[self._key(sid, tid)] = pending
            elif reply == "deny":
                # 否认只约束当轮：下一轮用户明确说出旧编号仍可按原话查询。
                self._turn_denied[self._key(sid, tid)] = {pending_norm: pending}
        return self.turn_state(sid, tid)

    def turn_state(self, session_id, turn_id) -> dict:
        sid, tid = str(session_id), str(turn_id)
        denied = self._turn_denied.get(self._key(sid, tid), {})
        return {"confirmed": self._turn_confirmed.get(self._key(sid, tid)),
                "denied": list(denied.values()), "denied_norm": set(denied)}

    def authorize(self, session_id, turn_id, order_id: str, question: str) -> str:
        """返回 ok / ask / denied。ask 时已记下候选，下一轮等待用户确认。"""
        candidate = normalize_order_text(order_id)
        original = str(order_id).strip()
        state = self.turn_state(session_id, turn_id)
        if not candidate:
            return "ask"
        confirmed = state["confirmed"]
        if confirmed and normalize_order_text(confirmed) == candidate:
            return "ok"
        if candidate in state["denied_norm"]:
            return "denied"
        if is_explicit_order_id(question, order_id):
            return "ok"
        self._pending[str(session_id)] = original
        return "ask"

    def clear_session(self, session_id) -> None:
        sid = str(session_id)
        self._pending.pop(sid, None)
        self._last_turn.pop(sid, None)
        for key in [key for key in self._turn_confirmed if key.startswith(sid + "|")]:
            self._turn_confirmed.pop(key, None)
        for key in [key for key in self._turn_denied if key.startswith(sid + "|")]:
            self._turn_denied.pop(key, None)
