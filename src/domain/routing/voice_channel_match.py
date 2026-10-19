"""按频道 ID 或房间名找到一个语音频道。"""

from __future__ import annotations


def match_voice_channel(rows: list[dict], query: str) -> tuple[dict | None, str]:
    """命中返回 (频道, "")。多个同名时返回说明，让调用方把名单发回去。"""
    text = str(query or "").strip()
    if not text:
        return None, "请写出房间名或频道 ID"
    exact_id = [row for row in rows if str(row.get("id") or "") == text]
    if len(exact_id) == 1:
        return exact_id[0], ""
    exact_name = [row for row in rows if str(row.get("name") or "") == text]
    if len(exact_name) == 1:
        return exact_name[0], ""
    if len(exact_name) > 1:
        return None, _ambiguous(exact_name)
    folded = text.casefold()
    partial = [
        row for row in rows
        if folded in str(row.get("name") or "").casefold()
    ]
    if len(partial) == 1:
        return partial[0], ""
    if len(partial) > 1:
        return None, _ambiguous(partial)
    return None, f"没有找到语音频道：{text}"


def _ambiguous(rows: list[dict]) -> str:
    names = "、".join(str(row.get("name") or row.get("id") or "") for row in rows[:8])
    return f"匹配到多个语音频道，请写得更具体：{names}"
