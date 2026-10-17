"""Source-grounded Chinese->Vietnamese meaning guards.

These guards detect clear factual contradictions, not arbitrary translation
accuracy. Other sentences can be wrong even if no rule fires.
"""
def source_semantic_issues(segments):
    all_issues = {}
    for i, seg in enumerate(segments):
        text = seg.text_src or ""
        vi = (seg.text_vi or "").casefold()
        issues = []
        previous = segments[i - 1] if i > 0 else None
        cross_line_china = bool(
            previous is not None and seg.speaker == previous.speaker
            and 0 <= seg.start - previous.end <= 1.5
            and "中国" in (previous.text_src or "")[-12:]
            and text.lstrip("。！？!?,，、 ").startswith("女足")
        )
        chinese_team = "中国女足" in text or cross_line_china
        if chinese_team and "越南" not in text:
            if "trung quốc" not in vi:
                issues.append("CHINA_TEAM_NAME_MISSING")
            if "việt nam" in vi:
                issues.append("COUNTRY_CONTRADICTION:中国女足")
        if "不一定" in text and not any(w in vi for w in (
            "không nhất thiết", "không có nghĩa", "không đồng nghĩa",
            "chưa chắc", "không hẳn", "không phải cứ", "không phải vì",
            "không thể khẳng định", "không chắc")):
            issues.append("NEGATION_SCOPE_LOST:不一定")
        if "顶级" in text and not any(w in vi for w in (
            "hàng đầu", "đỉnh cao", "đẳng cấp cao nhất", "top đầu",
            "tốp đầu", "dẫn đầu", "đỉnh thế giới")):
            issues.append("TOP_LEVEL_RANKING_MISSING:顶级")
        if issues:
            all_issues[seg.index] = issues
    return all_issues
