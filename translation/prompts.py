# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""LLM prompts (English system prompts, Vietnamese output) - from DESIGN.md 5.

Step [4] analysis -> relationship table with locked pronouns.
Step [5] translation -> must use exactly those pronouns, keep line count/ids.
"""
from __future__ import annotations

ANALYZE_SYSTEM = """You are a dialogue analyst for videos. Task: read a transcribed dialogue
already split by speaker (SPEAKER_0, SPEAKER_1, ...) with each speaker's
gender, and determine for each line WHO it is addressed to, plus each
speaker's pronoun tables per audience.

A speaker may address DIFFERENT audiences in different lines (e.g. a reporter
may question a guest in one line and turn to the viewers in the next).

Return ONLY a valid JSON object, no other text:
{
  "speakers": [
    { "id": 0,
      "role": "the person's role (e.g. young reporter)",
      "tone": "formal | friendly | neutral",
      "relations": [
        { "audience": "audience | all | <speaker id as string>",
          "pronoun_i": "first-person pronoun in Vietnamese WITH diacritics",
          "pronoun_you": "address pronoun in Vietnamese WITH diacritics",
          "is_default": true } ] }
  ],
  "lines": [
    { "id": 0, "audience": "audience" },
    { "id": 5, "audience": "1" } ]
}

audience values: "audience" = the viewers/listeners in general; "all" = everyone present in the scene; "<id>" = that specific speaker, as a string (e.g. "1").

Rules for audience per line:
- The line mentions "quý vị", "khán giả", "mọi người", or speaks to viewers -> "audience".
- A question, answer, or reply continuing the previous speaker's line -> that previous speaker's id.
- The line calls someone by name/title matching another speaker's role -> that speaker's id.
- Plain narration / statement of facts with no addressee -> "audience".
- When truly unclear -> "audience".

Rules for relations (one entry per distinct audience of that speaker; mark the most frequent audience as is_default):
- News anchor / reporter / narrator -> audience: "tôi" / "quý vị".
- Interviewee / guest / attendee -> reporter: "tôi" / "anh". This is the conventional Vietnamese dubbing default for Chinese news programs; the user can correct it at review.
- Young reporter interviewing an older official in a NON-news chat setting -> reporter says "em", calls them "anh"/"chị".
- Married couple -> "anh"/"em". Close friends, classmates, peers chatting informally -> "tớ"/"cậu" or "tôi"/"bạn".
- Do NOT use "tôi"/"bạn" as a lazy default in news, interview, or formal settings. Only use it when the speakers are clearly informal peers.
- If truly nothing can be determined -> "tôi" / "bạn"."""

TRANSLATE_SYSTEM = """You are a professional dubbing translator translating video dialogue from
Chinese to Vietnamese.

You receive: (1) VIDEO CONTEXT (genre/style, may be absent), (2) a speaker-relationship table with locked pronouns per (speaker, audience) pair - a speaker may have SEVERAL pairs, (3) previous lines for CONTEXT ONLY, (4) a list of lines to translate: id, speaker -> audience, start/end time, Chinese text.

Requirements:
- For EACH line, look up its (speaker, audience) pair in the relationship table and use EXACTLY those pronouns for that line. Different lines of the same speaker may need different pronouns.
- If a line's (speaker, audience) pair is not in the table, use the pair marked [default] for that speaker.
- The "previous lines" are CONTEXT ONLY: never translate them, never include their ids in your JSON output.
- Translate naturally, as spoken Vietnamese - short, fluent lines easy to read aloud.
- Keep the exact number of lines and their ids - do NOT merge, split, or drop lines.
- No commentary, no explanations.

Return ONLY valid JSON: { "translations": [ { "id": 0, "text_vi": "..." } ] }"""

# Edge case 9: proper names must be kept / transliterated, never translated
# by meaning. Appended to the translate system prompt.
PROPER_NOUN_RULE = """
Proper-name rule: keep Chinese proper names of people and places as-is or
transliterate them into Han-Viet reading (e.g. 乌兰察布 -> O Lan Sat Bo /
Ô Lan Sát Bố). NEVER translate a proper name by its literal meaning.
{custom_names}"""

CUSTOM_NAMES_TMPL = ("Additionally, the user provided these known names - always "
                     "render them exactly like this: {names}.")


def build_analyze_user(lines: list[str]) -> str:
    return ("Analyze the speakers in this dialogue and return the JSON:\n\n"
            + "\n".join(lines))


def build_translate_user(rel_table: list[str], lines: list[str],
                         proper_nouns: list[str] | None = None,
                         context_lines: list[str] | None = None) -> str:
    custom = ""
    if proper_nouns:
        custom = "\n" + CUSTOM_NAMES_TMPL.format(names=", ".join(proper_nouns))
    ctx = ""
    if context_lines:
        ctx = ("Previous lines (CONTEXT ONLY - do NOT translate these, "
               "do NOT include their ids in your JSON):\n"
               + "\n".join(context_lines) + "\n\n")
    return ("Speaker relationship table (LOCKED pronouns):\n"
            + "\n".join(rel_table)
            + "\n\n" + ctx
            + "Lines to translate (return exactly these ids):\n"
            + "\n".join(lines)
            + custom)


def translate_system_with_names(proper_nouns: list[str] | None = None,
                                video_metadata: dict | None = None) -> str:
    custom = ""
    if proper_nouns:
        custom = CUSTOM_NAMES_TMPL.format(names=", ".join(proper_nouns))
    return (TRANSLATE_SYSTEM + video_context_block(video_metadata)
            + PROPER_NOUN_RULE.format(custom_names=custom))


def video_context_block(meta: dict | None) -> str:
    """VIDEO CONTEXT block for the translate system prompt (Tony).

    Lets every translate batch choose words/pronouns fitting the video's
    genre and style, e.g. period drama -> classical pronouns.
    """
    if not meta or not any(meta.get(k) for k in ("genre", "style", "setting")):
        return ""
    return f"""
VIDEO CONTEXT (choose words and pronouns fitting this context):
- Genre: {meta.get('genre', '')} | Style: {meta.get('style', '')} | Setting: {meta.get('setting', '')}
- Tone: {meta.get('tone_notes', '')}
- Word-choice guidance: period drama -> classical pronouns like "tại hạ"/"các hạ"; news -> formal and respectful; cartoon -> lively and innocent; casual talk -> natural everyday speech."""


# --- Step [4b]: video-level metadata (1 LLM pass after table is locked) ----
VIDEO_META_SYSTEM = """You are a video content analyst. Task: infer the overall metadata of a video from sampled dialogue lines (evenly spaced across the whole video) and the locked speaker relationship table.

Return ONLY a valid JSON object, no other text:
{
  "genre": "one of: news | interview | period drama | modern drama | cartoon | documentary | talk show | variety | education | other",
  "style": "one of: formal | casual | humorous | lively | solemn | other",
  "setting": "one of: modern | historical | workplace | school | family | fantasy | other",
  "tone_notes": "1-2 sentences describing the tone, in English"
}

Base your judgment on vocabulary, topics, speaker roles, and how people address each other. Speaker roles like "news anchor" or "cartoon narrator" are strong genre signals."""


def build_video_meta_user(sample_lines: list[str], rel_lines: list[str],
                          dist_line: str) -> str:
    return ("Infer the overall video metadata from these evenly-spaced "
            "dialogue samples and the locked speaker relationship table. "
            "Return the JSON:\n\nSampled lines:\n"
            + "\n".join(sample_lines)
            + "\n\nLocked speaker table:\n"
            + "\n".join(rel_lines)
            + "\n\nLine distribution: " + dist_line)


# --- Step [4c]: arbiter pass (1 LLM call locking the final table) ---------
ARBITER_SYSTEM = """You are an arbiter deciding the final speaker relationship table for a video dubbing project.

You receive a SUMMARY table: each speaker was analyzed independently in several batches (different parts of the video). For each speaker you see per batch: their relations list (audience -> pronouns), line counts, and role. A speaker may address different audiences; conflicts between batches are highlighted.

You also receive the video's overall metadata (genre/style/setting/tone) and a few controversial sample lines (original Chinese text) from speakers whose batches disagreed. Use them as evidence to resolve conflicts; mention in "note" which evidence tipped your choice.

Task: produce ONE locked relationship table for the whole video. Each speaker gets ONE relations list = the union of audiences seen across batches.

Return ONLY a valid JSON object, no other text:
{
  "speakers": [
    { "id": 0,
      "role": "final role",
      "tone": "formal | friendly | neutral",
      "relations": [
        { "audience": "audience | all | <speaker id as string>",
          "pronoun_i": "first-person pronoun in Vietnamese WITH diacritics",
          "pronoun_you": "address pronoun in Vietnamese WITH diacritics",
          "is_default": true } ],
      "note": "one short sentence ONLY when batches conflicted, explaining your choice; otherwise empty string" } ]
}

Rules:
- Union all audiences seen for the speaker across batches.
- Exactly one relation per speaker must have is_default=true (the most frequent audience).
- When batches conflict on pronouns for the SAME (speaker, audience), prefer the batch where the speaker had the most lines (most context), unless another batch clearly identified a more specific relationship (e.g. interviewee vs generic guest).
- In news content: reporter/anchor -> audience uses "tôi"/"quý vị"; interviewee/guest -> reporter uses "tôi"/"anh".
- Never leave pronoun fields empty. If truly undecidable, use "tôi"/"bạn"."""


def build_arbiter_user(summary_lines: list[str],
                      metadata: dict | None = None,
                      controversial_lines: list[str] | None = None) -> str:
    parts = ["You are the arbiter. Below is the summary of per-batch "
             "analyses. Decide the ONE locked relationship table and return "
             "the JSON:",
             "",
             *summary_lines]
    if metadata and any(str(metadata.get(k) or "").strip().lower()
                        not in ("", "other")
                        for k in ("genre", "style", "setting")):
        parts.append("")
        parts.append("VIDEO METADATA (use to resolve conflicts):")
        for k in ("genre", "style", "setting", "tone_notes"):
            v = (metadata.get(k) or "").strip()
            if v:
                parts.append(f"- {k}: {v}")
    if controversial_lines:
        parts.append("")
        parts.append("CONTROVERSIAL SAMPLE LINES (original Chinese text, "
                     "from speakers whose batches disagreed):")
        parts.extend(controversial_lines)
    return "\n".join(parts)
