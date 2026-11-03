# Mandarin E2E: existing VietDub LLM analysis and translation

The full-video regression downloads a real Mandarin interview from Commons,
runs FunASR AutoModel, groups source utterances (preserving 45 original IDs),
then executes the EXISTING translation.BaseTranslator.analyze and .translate
through OllamaTranslator. In CI, a local Qwen2.5:3b Ollama model runs
without an external translation API. This is deliberately an LLM test,
not a separate MarianMT translation pipeline.

LLM analysis results: video metadata (genre, style, setting), locked
speaker-to-audience relationship/pronoun table, source-line audience tags.
The actual LLM translation receives those outputs. Counters of real
provider chat completions are persisted in QA so mock runs cannot appear
as real LLM evidence. Empty/source-echo lines fail closed before Edge-TTS.

The rendered MP4 is still named UNAPPROVED. An LLM does not verify actor
identity or original audio transcript, and the same LLM cannot be an
independent semantic correctness judge. A glossary-style Chinese->Vietnamese
terminology check flags potential mistranslation without calling that an
accuracy score. Compare it against human-transcribed source lines and
human-translated reference before accepting film quality.

For an existing user-configured 9Router provider, invoke the identical
script with '--llm-provider 9router --llm-model MODEL' and set
VIETDUB_9ROUTER_KEY in the execution environment. The E2E deliberately
does not bypass authentication or silently switch to Google Translate.
