import json
import logging
import re

from .llm import ProviderError
from .tool_dialogue import DESKTOP_TOOL_NAMES, TOOL_LOADING_NAME, control_plan
from .tools import ToolRegistry, ToolSpec

DESKTOP_INTENT_RE = re.compile(
    r"打开.{0,14}(?:应用|软件|程序|网页|网站|链接|飞书|微信|企业微信|钉钉|腾讯会议|浏览器|chrome|safari|vscode|wps|剪映|终端|备忘录|计算器|访达|finder|音乐|网盘)|"
    r"(?:飞书|微信|钉钉|企业微信).{0,16}(?:找|发|聊|联系|对话框|消息|群|搜索)|"
    r"电脑|桌面|屏幕|截图|看.{0,4}屏|界面|窗口|点[一一下]?[击下]|双击|右键|快捷键|剪贴板|终端|命令行|文件夹|目录|mac|windows|pc|desktop|screen",
    re.I,
)


def is_desktop_task_turn(question: str, history: list | tuple = ()) -> bool:
    if DESKTOP_INTENT_RE.search(question or ""):
        return True
    for message in reversed(history):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if role == "assistant":
            calls = message.get("tool_calls", []) if isinstance(message, dict) else (getattr(message, "tool_calls", None) or [])
            if any((call.get("tool_name") in DESKTOP_TOOL_NAMES) for call in calls):
                return True
            pa = message.get("pending_approval") if isinstance(message, dict) else getattr(message, "pending_approval", None)
            if isinstance(pa, dict) and pa.get("tool_name") in DESKTOP_TOOL_NAMES:
                return True
            break
        if role == "user":
            break
    return False


logger = logging.getLogger(__name__)

TOOL_PURPOSES = {
    "get_weather": "天气、预报、气象出行建议",
    "web_search": "联网搜索实时新闻、价格、百科与公开网页资料",
    "search_m5stack": "M5Stack官方硬件、引脚、SDK资料",
    "search_personal_knowledge": "用户上传的个人资料和知识库",
    "get_device_status": "当前设备音量、亮度、连接状态",
    "set_device_volume": "按用户要求调设备音量",
    "set_speech_rate": "按用户要求调语速",
    "set_speech_pitch": "按用户要求调音调",
    "search_conversation_history": "回查本会话未带入上下文的旧原话",
    "desktop_list_nodes": "查看已连接的 Windows / Mac 电脑节点",
    "desktop_inspect_screen": "截取并观察电脑当前屏幕画面及坐标",
    "desktop_clipboard": "读取电脑剪贴板内容",
    "desktop_list_dir": "列出电脑目录中的文件",
    "desktop_read_file": "读取电脑非敏感文本文件",
    "desktop_set_clipboard": "设置电脑剪贴板文本",
    "desktop_open": "在电脑上打开应用、文件或网址",
    "desktop_gui_action": "执行电脑点击、输入、快捷键与滚轮控制",
    "desktop_run_command": "在电脑终端执行命令",
}


class TextToolSelection:
    def __init__(self, context, *, exclude=()):
        self.context = context
        self.base_registry = context.registry
        self.base_current_registry = context.current_registry
        excluded = set(exclude or ())
        self.catalog = {item["name"]: item for item in context.definitions(compact=True) if item["name"] not in excluded}
        self.loaded = self._initial_tools() & self.catalog.keys()
        if self.catalog:
            loader = TaskToolLoader(self)
            context.registry = self.base_registry.with_tool(loader)
            context.current_registry = lambda: self.current_registry().with_tool(loader)
            context.allowed.add(TOOL_LOADING_NAME)
        self.log("initial")

    def current_registry(self):
        registry = self.base_current_registry() if self.base_current_registry else self.base_registry
        return registry if registry is not None else ToolRegistry([])

    def _initial_tools(self):
        question = self.context.question or ""
        names = set()
        actions = control_plan(question, self.context.history)
        names.update(action["tool"] for action in actions)
        if any(action["tool"] == "set_device_volume" and action["kind"] == "relative" for action in actions):
            names.add("get_device_status")
        for pattern, tools in [
            (r"搜索|搜一下|查一下|网上|联网|新闻|资讯|热搜|价格|金价|股价|汇率|上映|比分|百科|官网|最新消息|是什么时候", {"web_search"}),
            (r"天气|气温|预报|降雨|下雨|下雪|带伞|穿衣|防晒|空气质量", {"get_weather"}),
            (r"m5|atoms3|atom\s*s3|esp32|k147|gpio|引脚|接线|sdk|arduino", {"search_m5stack"}),
            (r"知识库|我的资料|上传|个人资料|文档|文件|资料里|资料中", {"search_personal_knowledge"}),
            (r"之前|刚才|最早|最初|一开始|前面|记得|说过", {"search_conversation_history"}),
            (r"(?:设备|机器人).{0,8}(?:状态|连接|在线)|(?:音量|亮度).{0,4}(?:多少|多大)", {"get_device_status"}),
            (DESKTOP_INTENT_RE.pattern,
             {"desktop_list_nodes", "desktop_inspect_screen", "desktop_clipboard", "desktop_list_dir",
              "desktop_read_file", "desktop_set_clipboard", "desktop_open", "desktop_gui_action", "desktop_run_command"}),
        ]:
            if re.search(pattern, question, re.I):
                names.update(tools)
        for message in reversed(self.context.history):
            role = message.get("role") if isinstance(message, dict) else message.role
            if role == "assistant":
                calls = message.get("tool_calls", []) if isinstance(message, dict) else message.tool_calls
                names.update(call.get("tool_name") for call in calls
                             if call.get("status") in ("ok", "error") and call.get("tool_name") != TOOL_LOADING_NAME)
                break
            if role == "user":
                break
        return names

    def available(self):
        gateway = getattr(self.context, "tool_gateway", None)
        registry = self.current_registry()
        if gateway is not None:
            enabled = {item["name"] for item in gateway.definitions(registry, include_side_effects=True)}
        else:
            enabled = {item["name"] for item in registry.definitions()}
        return self.catalog.keys() & enabled

    def active_names(self):
        return sorted(self.loaded & self.available())

    def definitions(self, nested=False):
        active = set(self.active_names())
        definitions = self.context.definitions(nested=nested, compact=True)
        deferred = self.available() - active
        return [item for item in definitions
                if item.get("function", item)["name"] in active
                or deferred and item.get("function", item)["name"] == TOOL_LOADING_NAME]

    def instructions(self):
        if not self.available() - self.loaded:
            return ""
        return (
            "\n未加载不等于没有能力。需要目录中的其他工具时，先调用_load_task_tools加载，"
            "再用真实业务工具取结果；加载本身未执行查询或控制。"
            "复合任务可一次加载多个；结合对话理解追问，不因工具未加载而拒答。")

    async def load(self, names):
        if not set(names) <= self.available():
            raise ProviderError(403, "tool_not_allowed", "所请求工具已停用或不在本轮可用范围。")
        added = set(names) - self.loaded
        if not added:
            raise ProviderError(409, "tools_already_loaded", "这些工具已经提供，请直接调用实际业务工具。")
        self.loaded.update(added)
        self.log("loaded")
        return {"loaded_tools": sorted(added),
                "parameters": {name: self.catalog[name]["parameters"] for name in sorted(added)},
                "executed": False,
                "instruction": "工具定义已提供，参数名和约束以此处及本次函数定义为准，不得自行改名。"
                               "请实际调用对应工具完成用户任务，不能把加载说成查询或控制成功。"}

    def log(self, phase):
        logger.info("text_tool_selection %s", json.dumps({
            "session_id": str(self.context.session_id), "turn_id": str(self.context.turn_id),
            "phase": phase, "active": self.active_names(),
            "deferred_count": len(self.available() - self.loaded),
        }, ensure_ascii=False))


class TaskToolLoader:
    def __init__(self, selection):
        self.selection = selection
        catalog = "；".join(
            name + "=" + TOOL_PURPOSES.get(name, item.get("description", ""))
            for name, item in selection.catalog.items())
        self.spec = ToolSpec(
            TOOL_LOADING_NAME,
            "按当前任务加载尚未提供的工具定义，可一次选多个；仅加载，不执行业务。目录：" + catalog,
            {"type": "object", "properties": {
                "names": {"type": "array", "items": {"type": "string", "enum": sorted(selection.catalog)},
                          "minItems": 1, "maxItems": len(selection.catalog), "uniqueItems": True}},
             "required": ["names"], "additionalProperties": False},
        )

    async def run(self, arguments, *, trace=None):
        return await self.selection.load(arguments["names"])
