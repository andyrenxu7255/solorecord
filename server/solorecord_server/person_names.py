import re


PSEUDO_PERSON_NAMES = {
    "给",
    "包括",
    "比如",
    "如果",
    "还是",
    "不是",
    "但是",
    "要不",
    "假如",
    "其实",
    "就是",
    "这个是",
    "一般用户",
    "开始",
    "点击",
    "然后",
    "还有就是",
    "到时候",
    "到时候大家",
    "第三个呢是",
    "在我底下",
    "对我",
    "嗯让他",
    "这个是用",
    "清理",
    "我大概",
    "你肯定能",
    "就刚刚或者",
    "就等于",
    "呃事实上就等于",
    "还有一个",
    "还有一点",
    "第一点",
    "第二点",
    "第三点",
    "第四点",
    "这个问题",
    "这个功能",
    "这个版本",
    "那块内容",
    "这块内容",
    "相关负责人",
    "前端开发",
    "UI讨论者",
    "主持人",
}


def is_pseudo_person_name(value: str) -> bool:
    """Return True when ASR/diarization text is clearly not a person or role."""
    name = re.sub(r"\s+", "", str(value or "").strip())
    if not name:
        return True
    if name in PSEUDO_PERSON_NAMES:
        return True
    if len(name) == 1 and name not in {"法", "销"}:
        return True
    if name in {"模型", "数据", "系统", "客户", "问题", "功能", "页面", "版本", "任务", "时间", "会议"}:
        return True
    if re.search(r"(比如|如果|假如|还是|不是|但是|就是|包括|到时候|然后|其实|刚刚|等于|这边|那边|那个|这个|要不|开始|点击|相关|负责)", name):
        return True
    if re.search(r"(我|你|他|她|它|咱|大家)", name) and len(name) <= 6:
        return True
    if re.search(r"(问题|功能|页面|版本|任务|时间|会议|分段|录音|模型|数据|系统)$", name) and len(name) <= 8:
        return True
    return False
