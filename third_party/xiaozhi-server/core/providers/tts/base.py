from typing import Optional
from core.utils import textUtils


class TTSProviderBase:
    def __init__(self):
        self.tts_text_buff = []
        self.processed_chars = 0
        self.is_first_sentence = True
        self.tts_stop_request = False
        self.punctuations = tuple("。！？!?；;：\n")
        self.first_sentence_punctuations = tuple("，,、~") + self.punctuations

    def feed(self, text):
        self.tts_text_buff.append(text)
        ready = []
        while self.processed_chars < len("".join(self.tts_text_buff)):
            previous = self.processed_chars
            segment = self._get_segment_text()
            if segment:
                ready.append(segment)
            if self.processed_chars == previous:
                break
        return ready

    def flush(self):
        self.tts_stop_request = True
        remainder = self._get_segment_text()
        self.processed_chars = len("".join(self.tts_text_buff))
        return [remainder] if remainder and remainder.strip() else []

    _QUOTE_PAIRS = (
        ("「", "」"),
        ("『", "』"),
        ("“", "”"),
        ('"', '"'),
        ("（", "）"),
        ("《", "》"),
        ("«", "»"),
        ("„", "“"),
        ("【", "】"),
        ("〈", "〉"),
        ("［", "］"),
        ("[", "]"),
    )

    _CLOSERS = '」』”》）"»“】〉］]'

    _QUOTE_CHARS = "".join(ch for pair in _QUOTE_PAIRS for ch in pair)

    @classmethod
    def _quote_safe_cut(cls, text: str, pos: int, punctuations) -> int:
        """避免在引号内切分（如 「わぁ！」って / “好！”他说）。

        候选位置之后紧跟的右引号和句末标点一并带走；若候选位于未闭合的引号内，
        或右引号后句子还在继续，则顺延到下一个标点；都不安全时返回 -1，等待更多文本。
        """
        if not any(ch in cls._QUOTE_CHARS for ch in text):
            # 全文不含引号/括号：不存在未闭合引号，右引号也无需携带，候选位置必然安全
            return pos
        candidates = [pos] + [
            i for i, ch in enumerate(text) if i > pos and ch in punctuations
        ]
        for candidate in candidates:
            end = candidate + 1
            carried_closer = False
            while end < len(text) and (
                text[end] in cls._CLOSERS or text[end] in punctuations
            ):
                if text[end] in cls._CLOSERS:
                    carried_closer = True
                end += 1
            segment = text[:end]
            # 前后配对的引号（「」等）用计数差检测；前后同符的引号（"）用奇偶检测
            balanced = True
            for opener, closer in cls._QUOTE_PAIRS:
                n_open = segment.count(opener)
                if opener == closer:
                    if n_open % 2:
                        balanced = False
                        break
                elif n_open > segment.count(closer):
                    balanced = False
                    break
            if not balanced:
                continue
            if carried_closer and (end == len(text) or not text[end].isspace()):
                # 右引号之后句子还在继续（「…」って、“…”他说），或暂时看不到后文
                continue
            return end - 1
        return -1

    def _get_segment_text(self) -> Optional[str]:
        # 合并当前全部文本并处理未分割部分
        full_text = "".join(self.tts_text_buff)
        current_text = full_text[self.processed_chars :]  # 从未处理的位置开始
        last_punct_pos = -1

        # 根据是否是第一句话选择不同的标点符号集合
        punctuations_to_use = (
            self.first_sentence_punctuations
            if self.is_first_sentence
            else self.punctuations
        )

        # 取每种标点最后出现位置的最早者作为切分点（与逐个 rfind 再取最小值等价）
        last_seen = {}
        for i, ch in enumerate(current_text):
            if ch in punctuations_to_use:
                last_seen[ch] = i
        last_punct_pos = min(last_seen.values(), default=-1)

        cut_pos = -1
        if last_punct_pos != -1:
            cut_pos = self._quote_safe_cut(
                current_text, last_punct_pos, punctuations_to_use
            )
        if cut_pos != -1:
            segment_text_raw = current_text[: cut_pos + 1]
            segment_text = textUtils.get_string_no_punctuation_or_emoji(
                segment_text_raw
            )
            self.processed_chars += len(segment_text_raw)  # 更新已处理字符位置

            # 如果是第一句话，在找到第一个逗号后，将标志设置为False
            if self.is_first_sentence:
                self.is_first_sentence = False

            return segment_text
        elif self.tts_stop_request and current_text:
            segment_text = current_text
            self.is_first_sentence = True  # 重置标志
            return segment_text
        else:
            return None
