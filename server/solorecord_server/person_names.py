import re


PSEUDO_PERSON_NAMES = {
    "给",
    "包括",
    "比如",
    "如果",
    "还是",
    "不是",
    "假如",
    "其实",
    "就是",
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
    if re.search(r"(比如|如果|假如|还是|不是|就是|包括|到时候|然后|其实|刚刚|等于|这边|那个)", name):
        return True
    if re.search(r"(我|你|他|她|它|咱|大家)", name) and len(name) <= 6:
        return True
    return False
