"""Speaker V2 tests: verified source evidence never becomes global cluster approval."""
import pytest
from core import checkpoint as cp
from project.schema import Segment
from speaker.verification import SpeakerVerification, line_key, clear_identity


def setup_job(tmp_path, name="job", audio=b"original-audio"):
    job = tmp_path / name
    job.mkdir()
    wav = job / "speech.wav"
    wav.write_bytes(audio)
    segments = [
        Segment(index=0, start=1, end=3, speaker=0, text_src="Hello", source_lang="en"),
        Segment(index=1, start=5, end=7, speaker=0, text_src="Hi", source_lang="en"),
        Segment(index=2, start=7, end=9, speaker=1, text_src="你好", source_lang="zh"),
    ]
    manifest = {"clusters": ["S00", "S01"], "candidates": [
        {"candidate_id": "a", "cluster": "S00", "start": 1, "end": 2,
         "source_asr_ids": [0], "file": "clips/a.wav"},
        {"candidate_id": "b", "cluster": "S00", "start": 5, "end": 6,
         "source_asr_ids": [1], "file": "clips/b.wav"},
    ]}
    return job, wav, segments, manifest


def test_verified_anchor_never_approves_whole_cluster(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    v = SpeakerVerification(job, lines, wav, man)
    v.verify_anchor("a", "Maddie", heard_audio=True, checked_video=True)
    assert v.suggest(0)["status"] == "SUGGESTION_ONLY"
    assert v.suggest(1)["status"] == "NO_DIRECT_REFERENCE"
    assert v.anchor_decisions["a"]["cluster_wide_approval"] is False
    assert [x.speaker for x in lines] == [0, 0, 1]
    assert v.summary()["verified_lines"] == 0
    assert v.summary()["translation_approved"] is False


def test_anchor_conflict_never_assumed_same_character(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    man["candidates"][1]["start"] = 1
    man["candidates"][1]["end"] = 2.5
    v = SpeakerVerification(job, lines, wav, man)
    v.verify_anchor("a", "Maddie", heard_audio=True, checked_video=True)
    v.verify_anchor("b", "Ethan", heard_audio=True, checked_video=True)
    assert v.suggest(0)["status"] == "CONFLICT"
    assert all(x.identity_status == "UNVERIFIED" for x in lines)


def test_audio_and_video_are_required_for_each_manual_approval(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    v = SpeakerVerification(job, lines, wav, man)
    with pytest.raises(ValueError, match="audio GỐC"):
        v.verify_line(0, "A", heard_audio=True, checked_video=False)
    with pytest.raises(ValueError, match="audio GỐC"):
        v.verify_anchor("a", "A", heard_audio=False, checked_video=True)
    assert not v.characters and not v.line_decisions


def test_exact_line_only_maps_to_unique_canonical_speaker(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    v = SpeakerVerification(job, lines, wav, man)
    v.verify_line(0, "Maddie", heard_audio=True, checked_video=True)
    assert lines[0].identity_status == "VERIFIED"
    assert lines[0].character_name == "Maddie"
    assert lines[0].detected_speaker == 0
    assert lines[0].speaker > 1
    assert lines[1].speaker == 0 and lines[1].identity_status == "UNVERIFIED"
    assert not lines[0].needs_review  # identity approval never changes ASR quality
    v.verify_line(1, "Ethan", heard_audio=True, checked_video=True)
    assert lines[0].speaker != lines[1].speaker
    assert v.ensure_character("maddie") == "CHAR_001"
    assert len(v.characters) == 2


def test_changed_text_or_timestamp_invalidates_saved_identity(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    v = SpeakerVerification(job, lines, wav, man)
    key = line_key(lines[0])
    v.verify_line(0, "Maddie", heard_audio=True, checked_video=True)
    lines[0].text_src = "Actually no"
    v.apply_verified_lines()
    assert lines[0].speaker == 0
    assert lines[0].identity_status == "UNVERIFIED"
    assert lines[0].needs_review
    assert key in v.line_decisions  # historical review event remains, not applied


def test_revoke_does_not_change_other_line_or_anchor(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    v = SpeakerVerification(job, lines, wav, man)
    v.verify_anchor("a", "Maddie", heard_audio=True, checked_video=True)
    v.verify_line(0, "Maddie", heard_audio=True, checked_video=True)
    v.verify_line(1, "Ethan", heard_audio=True, checked_video=True)
    v.revoke_anchor("a")
    v.revoke_line(0)
    assert lines[0].speaker == 0 and lines[0].identity_status == "UNVERIFIED"
    assert lines[1].identity_status == "VERIFIED"
    assert v.summary()["verified_anchors"] == 0


def test_restart_persists_only_same_video_and_exact_source(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    v = SpeakerVerification(job, lines, wav, man)
    v.verify_line(0, "A", heard_audio=True, checked_video=True)
    v.save()
    fresh = [
        Segment(index=s.index, start=s.start, end=s.end,
                speaker=s.detected_speaker if s.detected_speaker is not None else s.speaker,
                text_src=s.text_src) for s in lines
    ]
    again = SpeakerVerification(job, fresh, wav, man)
    assert again.summary()["verified_lines"] == 1
    assert fresh[0].identity_status == "VERIFIED"
    assert cp.load_step(job, "speaker_verification")["translation_approved"] is False
    wav.write_bytes(b"different-video-source")
    with pytest.raises(ValueError, match="thay đổi"):
        SpeakerVerification(job, fresh, wav, man)


def test_other_job_with_same_transcript_cannot_inherit_characters(tmp_path):
    job, wav, lines, man = setup_job(tmp_path, "one")
    v = SpeakerVerification(job, lines, wav, man)
    v.verify_line(0, "A", heard_audio=True, checked_video=True)
    v.save()
    other, wav2, fresh, _ = setup_job(tmp_path, "two")
    independent = SpeakerVerification(other, fresh, wav2, man)
    assert independent.summary()["verified_lines"] == 0
    assert independent.characters == {}


def test_funasr_without_pyannote_allows_manual_per_line_review(tmp_path):
    job, wav, lines, _ = setup_job(tmp_path)
    v = SpeakerVerification(job, lines, wav)
    v.verify_line(2, "Phóng viên", heard_audio=True, checked_video=True)
    assert v.summary()["verified_lines"] == 1
    assert v.summary()["verified_anchors"] == 0


def test_unknown_reference_and_empty_name_are_rejected(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    v = SpeakerVerification(job, lines, wav, man)
    with pytest.raises(KeyError):
        v.verify_anchor("foreign", "A", heard_audio=True, checked_video=True)
    with pytest.raises(ValueError):
        v.verify_line(0, "  ", heard_audio=True, checked_video=True)
    assert v.characters == {}


def test_speaker_and_project_metadata_roundtrip():
    from project.schema import Speaker
    person = Speaker(id=14, role="actor", identity_verified=True,
                     character_name="Ethan")
    assert Speaker.from_dict(person.to_dict()).character_name == "Ethan"
    s = Segment(index=0, start=1, end=2, speaker=14,
                detected_speaker=2, character_id="CHAR_001",
                character_name="Ethan", identity_status="VERIFIED")
    assert Segment.from_dict(s.to_dict()).detected_speaker == 2


def test_saved_speaker_identity_is_bound_to_original_video_not_just_audio(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    original_video = job / "movie.mp4"
    original_video.write_bytes(b"actual original visuals")
    verifier = SpeakerVerification(
        job, lines, wav, man, source_video=original_video)
    verifier.verify_line(0, "Maddie", heard_audio=True, checked_video=True)
    verifier.save()
    clean_lines = [
        Segment(index=seg.index, start=seg.start, end=seg.end,
                speaker=(seg.detected_speaker if seg.detected_speaker is not None
                         else seg.speaker), text_src=seg.text_src)
        for seg in lines
    ]
    same = SpeakerVerification(
        job, clean_lines, wav, man, source_video=original_video)
    assert same.summary()["verified_lines"] == 1
    original_video.write_bytes(b"swapped video SAME sound")
    with pytest.raises(ValueError, match="Video GỐC"):
        SpeakerVerification(
            job, clean_lines, wav, man, source_video=original_video)


def test_replacing_voice_anchor_manifest_revokes_checkpoint_reuse(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    video = job / "movie.mp4"
    video.write_bytes(b"scene video for original voices")
    state = SpeakerVerification(job, lines, wav, man, source_video=video)
    state.verify_anchor("a", "Maddie", heard_audio=True, checked_video=True)
    state.save()
    changed = {
        **man,
        "candidates": [dict(item) for item in man["candidates"]],
    }
    changed["candidates"][0]["start"] = .5
    with pytest.raises(ValueError, match="Mẫu giọng"):
        SpeakerVerification(job, lines, wav, changed, source_video=video)


def test_old_audio_only_checkpoint_does_not_revalidate_video_identity(tmp_path):
    job, wav, lines, man = setup_job(tmp_path)
    old = SpeakerVerification(job, lines, wav, man)
    old.verify_line(0, "Maddie", heard_audio=True, checked_video=True)
    old.save()
    film = job / "original.mp4"
    film.write_bytes(b"source movie pictures")
    with pytest.raises(ValueError, match="video GỐC|Video GỐC"):
        SpeakerVerification(job, lines, wav, man, source_video=film)
