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
      "role": "a concrete inferred role, such as football interviewee",
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
- Interviewee / guest / attendee -> reporter: "tôi" / "anh". This is a conventional Vietnamese dubbing default for news programs; the user can correct it at review.
- Young reporter interviewing an older official in a NON-news chat setting -> reporter says "em", calls them "anh"/"chị".
- Married couple -> "anh"/"em". Close friends, classmates, peers chatting informally -> "tớ"/"cậu" or "tôi"/"bạn".
- Do NOT use "tôi"/"bạn" as a lazy default in news, interview, or formal settings. Only use it when the speakers are clearly informal peers.
- If truly nothing can be determined -> "tôi" / "bạn"."""

TRANSLATE_SYSTEM = """You are a professional audiovisual translator. Translate the ORIGINAL
source-language speech into natural spoken VIETNAMESE for dubbing.

Input contains VIDEO CONTEXT (only a hint), a locked speaker/audience pronoun
table, CONTEXT ONLY previous lines, and lines with exact source IDs to translate.
The transcript may be noisy, disfluent, cut across segments, or multilingual.

MANDATORY TRANSLATION RULES (in priority order):
1. The original source utterance is the authority. Translate EVERY meaningful
   clause into Vietnamese. Do not omit qualifiers, actions, subjects, negation,
   modality, comparisons, dates, numbers, identities, or cause and effect.
   Do not reverse who did what to whom. Do not invent missing words or facts.
2. OUTPUT LANGUAGE: The text_vi field MUST be fluent Vietnamese, not a mix of
   Vietnamese and the original script. Never copy Hanzi, Chinese/Japanese kana,
   Korean Hangul or other non-Vietnamese source-script fragments into text_vi.
   Never invent non-Latin characters even when the source is entirely English.
   Translate the meaning of each such fragment. For names, use a known Vietnamese
   rendering or a Latin-letter transliteration, NOT source-script characters.
   Preserve exact Latin-script proper names when appropriate.
3. Every requested source ID maps to ONE Vietnamese string with that SAME ID.
   Never merge/split/drop an utterance, duplicate the previous translation, use
   contextual lines as translated output, or invent an answer to a question.
4. Preserve the original communicative intent: question stays a question,
   answer stays an answer, request stays a request, and rhetorical or indirect
   questions keep their meaning. ASR punctuation may be unreliable; prioritize
   the spoken wording and surrounding dialogue over punctuation alone.
5. Use exactly the locked (speaker, audience) pronoun pair for each source line.
   If absent, use that speaker's default pair. Avoid adding extra pronouns or
   dialogue the source did not contain.
6. Be concise and natural enough to speak within each line's start/end times.
   Condense filler and repetitions, NOT important source facts. Do not truncate
   sentences simply to shorten dubbing. An interrupted utterance should remain
   a natural, faithful fragment without invented completion.
7. Before returning JSON, check EACH line for leftover source script, omitted
   source meaning, wrong identities, changed negation, changed question/answer
   intent, duplicated target text for unrelated sources, and incorrect IDs.

Return ONLY a valid JSON object, without markdown or commentary:
{"translations":[{"id":0,"text_vi":"Bản dịch hoàn toàn bằng tiếng Việt."}]}
Replace the example ID 0 with each ACTUAL requested source ID; include all and
only those IDs exactly once."""

# Small local LLMs may fail or loop when a large video-level translation
# prompt is reused for ONE failed/repeated line. This is a dedicated fallback
# that still preserves the source-ID and locked speaker-pronoun contract.
SINGLE_LINE_TRANSLATE_SYSTEM = """Translate EXACTLY ONE source-language
video dialogue utterance into natural spoken Vietnamese.
Use the original utterance in 'Lines to translate' as the authority.
Use the locked speaker/audience pronouns from the input. Other lines are
context only, not output. Do not invent, drop or repeat speech.
Preserve questions, negations, people, numbers, names, actions and intent.
text_vi MUST be entirely Vietnamese: translate Chinese Hanzi, Japanese kana
and Korean Hangul into Vietnamese; proper names can use Latin letters.
Keep the phrase concise for its subtitle/dubbing interval.
Return ONLY JSON {"translations":[{"id":ACTUAL_ID,"text_vi":"..."}]}.
Replace ACTUAL_ID with the exact requested ID. No notes, extra lines or markdown.
"""


# Edge case 9: proper names must be kept / transliterated, never translated
# by meaning. Appended to the translate system prompt.
PROPER_NOUN_RULE = """
Proper-name rule: NEVER translate a proper name by its literal meaning.
Keep consistent character and location name spellings across scenes.
For Chinese source: interpret Simplified and Traditional Chinese and choose a
consistent customary Vietnamese name or Latin-letter transliteration.
Never leave Hanzi inside the Vietnamese target field even for proper names.
For English/other sources: preserve established names and avoid invented
translations of names or cultural references.
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
            + "SOURCE UTTERANCES (return exactly these ids): translate all and ONLY these IDs into "
              "fluent Vietnamese, with NO untranslated source-script words:\n"
            + "\n".join(lines)
            + "\nReturn JSON translations with these exact IDs and no others."
            + custom)


def translate_system_with_names(proper_nouns: list[str] | None = None,
                                video_metadata: dict | None = None) -> str:
    custom = ""
    if proper_nouns:
        custom = CUSTOM_NAMES_TMPL.format(names=", ".join(proper_nouns))
    from asr.source_language import LANGUAGE_NAMES, normalize_language
    source = normalize_language((video_metadata or {}).get("source_language", "und"))
    label = LANGUAGE_NAMES.get(source, source)
    mixed = bool((video_metadata or {}).get("language_review_required", False))
    language_guide = (
        "\nSOURCE LANGUAGE: " + label + " (" + source + "). "
        "Use the [lang=...] marker on each dialogue line when present. "
        "Never assume the source language is Chinese or English. "
        "Translate idioms, titles, kinship terms and local context accurately. "
        "If code-switching or names are ambiguous, preserve evidence for review.\n"
    )
    chinese_guide = (
        "\nCHINESE-SPECIFIC: handle Simplified and Traditional Chinese, "
        "idioms, names, honorifics, particles, time expressions and "
        "implicit subjects accurately. Ground entities and terminology in "
        "THIS video's source transcript and context. Preserve negation, "
        "causality, numbers, and roles. Never import names or assumptions "
        "from an unrelated video. Translate every Chinese phrase into natural "
        "Vietnamese, including proper nouns using Latin/Vietnamese writing. "
        "Never copy Hanzi as-is into text_vi, even when the input sentence is "
        "fragmented or the earlier Vietnamese draft contains Hanzi.\n"
    ) if source == "zh" or mixed else ""
    return (TRANSLATE_SYSTEM + language_guide + chinese_guide
            + video_context_block(video_metadata)
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

Base your judgment on vocabulary, topics, speaker roles, and how people address each other. Speaker roles like "news anchor" or "cartoon narrator" are strong genre signals. A football interview talking about school education is an interview FORMAT, not a classroom education video. Never output template placeholders as actual roles."""


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

You also receive the video's overall metadata (genre/style/setting/tone) and a few controversial sample lines (original-language text) from speakers whose batches disagreed. Use them as evidence to resolve conflicts; mention in "note" which evidence tipped your choice.

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
        parts.append("CONTROVERSIAL SAMPLE LINES (original-language text, "
                     "from speakers whose batches disagreed):")
        parts.extend(controversial_lines)
    return "\n".join(parts)


# --- Video-independent repair prompts for small multilingual LLMs ----------

def repair_system_prompt(line_id: int, *, source_script_remains: bool = False,
                         concise_retry: bool = False) -> str:
    """Focused one-line revision instructions; no video/topic-specific terms."""
    # The second attempt reduces instruction overhead for Qwen2.5 3B.
    # A concise source-only retry is less likely to copy a broken draft or
    # trigger Ollama's token repetition limit. Never reduce ID/QA guards.
    if concise_retry:
        task = ("FULL RETRANSLATION " if source_script_remains else
                "SOURCE-GROUNDED CORRECTION ")
        return (
            task + "of ONE original speech utterance into spoken Vietnamese. "
            "Translate the WHOLE original sentence, not the failed draft. "
            "Output ONLY Vietnamese words and Latin-script proper names; "
            "no Hanzi, kana, Hangul, or original-language phrases. "
            "Do not drop question intent, negation, names, numbers or events. "
            "Do not invent a reply or context. Short, natural dubbing text. "
            f'Return ONLY JSON {{"id":{line_id},"text_vi":"..."}} with id exactly '
            f'{line_id}. No extra lines or explanation.'
        )
    common = (
        "You are correcting ONE Vietnamese dubbing translation. "
        "The original source-language utterance is the ground truth; "
        "neighboring utterances provide context ONLY, not output text. "
        "Retain all source facts, speaker, entities, negation, questions, "
        "actions and relations. Do not add answers, explanations or dialogue. "
        "If the transcript is noisy, do not invent unsupported content. "
        "Translate naturally and concisely for spoken Vietnamese. "
        "Return ONLY a valid JSON object with EXACTLY two keys: "
        '"id" (integer) and "text_vi" (Vietnamese string). '
        f'The id MUST be {line_id}, not 0 or a neighboring id. '
        f'Exact response shape: {{"id":{line_id},"text_vi":"..."}}. '
        "No markdown, source quotations or any other text."
    )
    if source_script_remains:
        return (
            "TASK: FULL RETRANSLATION FROM THE ORIGINAL SOURCE, not a partial "
            "word replacement or a continuation of the previous draft. "
            "The previous Vietnamese draft contains untranslated foreign-script "
            "words. It is WRONG; use the original utterance, not the draft, "
            "to translate the COMPLETE meaningful line. "
            "Write 100% natural Vietnamese in text_vi. Zero Hanzi/Chinese "
            "characters, Japanese kana or Hangul are allowed in text_vi. "
            "Translate foreign phrases, including the highlighted leftovers, "
            "into Vietnamese words. For proper names, use conventional "
            "Vietnamese forms or Latin-letter transliteration, never Hanzi. "
            "Preserve the sentence's question or statement meaning, all "
            "negation, numbers and relationships. "
            + common
        )
    return (
        "TASK: Correct the exact semantic or structural mistakes listed "
        "by QA against the ORIGINAL utterance. Translate any foreign-script "
        "fragments into Vietnamese, preserve question intent and all "
        "source facts. Keep the resulting sentence short enough to dub. "
        + common
    )
