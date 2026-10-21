"""Rules for untrusted tool content; evidence contains references, never raw text."""

import json
import re
import unicodedata

from agentguard.contracts import SecurityFinding, ToolResultEvent
from agentguard.contracts.models import _json_snapshot

_DIRECTIVES = tuple(
    re.compile(pattern, re.I | re.M)
    for pattern in (
        r"^\s*(?:\[/?(?:system|developer)\]|(?:system|developer)\s*:|<\|im_start\|>\s*(?:system|developer))",
        r"^\s*(?:ignore|disregard|forget)\b[^\n.]{0,100}\b(?:instructions|rules|prompts)\b",
        r"\b(?:you must|you should|please|now)\s+(?:ignore|disregard)"
        r"\b[^\n.]{0,100}\binstructions\b",
        r"^\s*(?:user|human|assistant)\s*:\s*(?:ignore|call|run|execute|send|read|write)\b",
        r"\b(?:send|upload|exfiltrate)\b[^\n]{0,160}"
        r"\b(?:secrets?|credentials?|api[_ -]?keys?|passwords?)\b",
        r"\b(?:secrets?|credentials?|api[_ -]?keys?|passwords?)\b[^\n]{0,120}(?:https?://|attacker)",
        r"^\s*(?:忽略(?:之前|以上|所有|原有)|无视.{0,30}指令|系统(?:消息|指令)\s*[:：]|你现在必须)",
    )
)
_NEGATED_EXFILTRATION = re.compile(
    r"\b(?:never|do not|don't)\s+(?:send|upload|exfiltrate)\s+(?:your\s+)?"
    r"(?:secrets?|credentials?|api[_ -]?keys?|passwords?)"
    r"(?:\s+to\s+(?:an?\s+)?attacker)?\b",
    re.I,
)


def strings(value):
    if type(value) is str:
        yield value
    elif type(value) is dict:
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif type(value) is list:
        for item in value:
            yield from strings(item)


def _role_payload(value):
    if type(value) is dict:
        if (
            str(value.get("role", "")).lower() in {"system", "developer", "user"}
            and "content" in value
        ):
            return True
        return any(_role_payload(item) for item in value.values())
    if type(value) is list:
        return any(_role_payload(item) for item in value)
    return False


class RuleResultDetector:
    detector_id = "detector.result.rules"

    def detect(self, event, context):
        if type(event) is not ToolResultEvent:
            raise ValueError("Result event required")
        content = event.content
        if type(content) is str and content.lstrip().startswith(("{", "[")):
            try:
                decoded = json.loads(content)
            except json.JSONDecodeError:
                pass
            else:
                content = _json_snapshot(decoded, limit=64 * 1024)
        if has_instructions(content):
            return (
                SecurityFinding(
                    code="result.instruction",
                    severity="high",
                    evidence_ref=event.event_id,
                    detector_id=self.detector_id,
                ),
            )
        return ()


def has_instructions(content):
    return _role_payload(content) or any(_instruction_text(text) for text in strings(content))


# Compositional intent rules, NOT a general semantic model. A directive/request
# must co-occur with an action and a relevant target; reporting and negation are
# scoped per clause, never used as a whole-document allowlist.
_QUOTES = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_REPORT = re.compile(
    r"^\s*(?:(?:the|this) (?:paper|report|article|study)|本(?:文|报告|研究)|该(?:论文|报告))", re.I
)
_ADVICE_LABEL = re.compile(
    r"^\s*(?:安全(?:建议|提示|提醒)|safety (?:advice|tips?))\s*[:：]\s*", re.I
)
_DEFENSE = re.compile(
    r"^\s*(?:(?:please\s+)?(?:never|do not|don't|avoid)\s+"
    r"(?:read|open|fetch|send|upload|transfer|invoke|call|execute|disclose)\b"
    r"|(?:请|你应该)?(?:不要|勿|别|切勿|禁止|不得|不应)(?:读取|打开|上传|发送|调用|执行|导出|泄露))",
    re.I,
)
_NEXT_DIRECTIVE = (
    r"(?:(?:please|kindly|now|first|next|never|do not|don't|you (?:must|should)|"
    r"read|open|fetch|retrieve|obtain|collect|extract|load|send|upload|transfer|relay|forward|"
    r"post|paste|print|include|reveal|return|show|attach|copy|call|invoke|execute|run|use|"
    r"ignore|disregard|forget)\b|(?:system|developer)\s*:|"
    r"(?:请|务必|立即|现在|接下来|下一步|不要|禁止|不得|切勿|需要你|你必须|"
    r"读取|打开|发送|上传|调用|执行|运行|提取|获取)|"
    r"(?:系统|开发者|管理员)(?:消息|指令|通知)\s*[:：])"
)
_CLAUSES = re.compile(
    r"[\n;；。！？]|(?<=[.!?])\s+|\b(?:but|however|instead|then)\b|但是|不过|而是|然而"
    r"|但(?=\s*" + _NEXT_DIRECTIVE + ")",
    re.I,
)
_NEGATION_BOUNDARY = re.compile(
    r"(?:[,，:：]\s*(?:(?:and|or)\b\s*|(?:同时|并且|并|以及|也))?"
    r"|\band\b\s*|(?:同时|并且|并))\s*(?=" + _NEXT_DIRECTIVE + ")",
    re.I,
)
_REQUEST = re.compile(
    r"(?:^\s*|[:,，：]\s*)(?:(?:please|kindly|first|next|now|simply)\s+)*"
    r"(?:read|open|fetch|retrieve|obtain|collect|extract|load|send|upload|transfer|relay|forward|"
    r"post|paste|print|include|reproduce|reveal|return|show|attach|copy|call|invoke|execute|run|use)\b"
    r"|\b(?:you (?:must|should|need to|are required to)|"
    r"your (?:next )?(?:reply|response) (?:must|should)|would you|we need you to|"
    r"(?:the )?next (?:step|action) (?:is|requires)|it is (?:necessary|required) to|"
    r"(?:verification|completion) (?:requires|needs)|to (?:finish|complete|continue))\b"
    r"|(?:请|务必|立即|现在|接下来|下一步|先|再|把|将|需要你|你(?:应该|需要|必须)|前提是|为了.{0,30}(?:请|先))",
    re.I,
)
_READ = re.compile(
    r"\b(?:read|open|fetch|retrieve|obtain|collect|extract|load)\b"
    r"|读取|打开|查看|导出|提取|获取|搜集|收集|加载|调取",
    re.I,
)
_SECRET = re.compile(
    r"(?:\.env\b|id_rsa|\.ssh\b|/etc/shadow|private[_ -]?keys?|api[_ -]?keys?|"
    r"access[_ -]?tokens?|credentials?|passwords?|secrets?|"
    r"私钥|密钥|令牌|凭据|密码|机密|敏感(?:文件|数据))",
    re.I,
)
_EXPORT = re.compile(
    r"\b(?:send|upload|transfer|relay|forward|post|paste|print|include|reproduce|"
    r"reveal|return|show|attach|copy)\b|发送|上传|外传|转发|提交|贴出|显示|附上|回传|传给|转交",
    re.I,
)
_DATA = re.compile(
    r"\b(?:file|document|contents?|output|conversation|history|result)\b|文件|文档|内容|结果|对话|记录",
    re.I,
)
_DESTINATION = re.compile(
    r"https?://|\b(?:endpoint|webhook|remote|external|attacker)\b|外部|远端|服务器|收集端|接收端",
    re.I,
)
_TOOL = re.compile(r"\b(?:call|invoke|execute|run|use)\b|调用|执行|运行|使用", re.I)
_TOOL_TARGET = re.compile(
    r"\b(?:read_file|write_note|run_command|send_email|shell|tool|function)\b|工具|函数|命令", re.I
)
_CONTROL = re.compile(
    r"\b(?:set aside|supersedes?|overrides?|takes? precedence over)\b.{0,100}"
    r"\b(?:brief|task|instructions?|rules?|request)\b"
    r"|(?:以(?:本段|本文|这条消息)为准|原任务作废|取代.{0,20}(?:任务|指令)|优先服从.{0,20}(?:消息|指令))",
    re.I,
)
_AUTHORITY = re.compile(
    r"^\s*(?:\[?(?:系统|开发者|管理员|用户)(?:消息|指令|通知)\]?\s*[:：]|"
    r"(?:本消息来自|我是|我代表).{0,16}(?:系统|开发者|管理员))"
    r"|\b(?:i am your |this (?:message|notice) (?:comes|is) from (?:the )?)"
    r"(?:system|developer|administrator)\b",
    re.I,
)


def _instruction_text(text):
    normalized = "".join(
        char for char in unicodedata.normalize("NFKC", text) if unicodedata.category(char) != "Cf"
    )
    for clause in _CLAUSES.split(normalized):
        if _REPORT.search(clause):
            clause = _QUOTES.sub("[quoted research sample]", clause)
        # A bounded advisory label is context, never permission to ignore content.
        # Removing it exposes both negative advice and affirmative instructions.
        clause = _ADVICE_LABEL.sub("", clause, count=1)
        # A negative prefix covers its own action, not later independent requests.
        # Keep plain target lists and `or read ...` coordination inside the negative
        # scope; a new imperative after punctuation/`and` is checked separately.
        while defense := _DEFENSE.match(clause):
            boundary = _NEGATION_BOUNDARY.search(clause, defense.end())
            clause = clause[boundary.end() :] if boundary else ""
        if _CONTROL.search(clause) or _AUTHORITY.search(clause):
            return True
        defensive = _NEGATED_EXFILTRATION.sub("[defensive advice]", clause)
        if any(pattern.search(defensive) for pattern in _DIRECTIVES):
            return True
        if not (
            _REQUEST.search(clause)
            or re.match(r"^\s*(?:读取|打开|发送|上传|调用|执行|运行|提取|获取)", clause)
        ):
            continue
        secret = _SECRET.search(clause)
        if (
            (_READ.search(clause) and secret)
            or (
                _EXPORT.search(clause)
                and (secret or (_DATA.search(clause) and _DESTINATION.search(clause)))
            )
            or (_TOOL.search(clause) and _TOOL_TARGET.search(clause))
        ):
            return True
    return False
