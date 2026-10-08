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
gender, and determine their roles and relationships.

Return ONLY a valid JSON object, no other text:
{
  "speakers": [
    { "id": 0,
      "role": "the person's role (e.g. young reporter)",
      "speaking_to": "who they are talking to (e.g. the audience)",
      "pronoun_i": "first-person pronoun they use for themselves, in Vietnamese WITH diacritics (e.g. tôi)",
      "pronoun_you": "pronoun they use to address the other party, in Vietnamese WITH diacritics (e.g. quý vị)",
      "tone": "formal | friendly | neutral" }
  ]
}

Rules for choosing Vietnamese pronouns:
- Base it on role, estimated age, and relationship (senior/junior, strangers, family...).
- Young reporter interviewing an older official -> reporter says "em", calls them "anh"/"chị".
- Speaking to a crowd/audience -> "tôi" / "quý vị".
- Married couple -> "anh"/"em". Close friends -> "tớ"/"cậu".
- If information is insufficient -> safe default: "tôi" / "bạn"."""

TRANSLATE_SYSTEM = """You are a professional dubbing translator translating video dialogue from
Chinese to Vietnamese.

You receive: (1) a speaker-relationship table with locked pronouns - you MUST
use exactly these pronouns, (2) a list of lines: id, speaker, start/end time,
Chinese text.

Requirements:
- Translate naturally, as spoken Vietnamese - short, fluent lines that are easy
  to read aloud for dubbing.
- You MUST use the pronouns from the relationship table. Never change them.
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
                         proper_nouns: list[str] | None = None) -> str:
    custom = ""
    if proper_nouns:
        custom = "\n" + CUSTOM_NAMES_TMPL.format(names=", ".join(proper_nouns))
    return ("Speaker relationship table (LOCKED pronouns):\n"
            + "\n".join(rel_table)
            + "\n\nLines to translate:\n"
            + "\n".join(lines)
            + custom)


def translate_system_with_names(proper_nouns: list[str] | None = None) -> str:
    custom = ""
    if proper_nouns:
        custom = CUSTOM_NAMES_TMPL.format(names=", ".join(proper_nouns))
    return TRANSLATE_SYSTEM + PROPER_NOUN_RULE.format(custom_names=custom)
