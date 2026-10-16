"""Offline ZeroTTS adapter for VietDub."""
from pathlib import Path
from project.schema import Segment
class ZeroTTSLocal:
    def __init__(self,model_dir="model/ZeroTTS",voices=None,local_only=True):
        self.model_dir=model_dir
        self.voices=voices or {}
        self.local_only=local_only
        self.engine=None
    def _engine(self):
        if self.engine is None:
            if self.local_only and not Path(self.model_dir).is_dir():
                raise RuntimeError("Missing offline ZeroTTS model: "+self.model_dir)
            from zerotts import ZeroTTS
            self.engine=ZeroTTS.from_pretrained(self.model_dir)
        return self.engine
    def synthesize(self,segments,out_dir):
        out_dir=Path(out_dir)
        out_dir.mkdir(parents=True,exist_ok=True)
        engine=self._engine()
        voices=set(engine.list_voices())
        male=("giahuy","huuduc","quangminh","tiendat")
        female=("maichi","baotrang","kimoanh","hamy")
        for seg in segments:
            text=(seg.text_vi or "").strip()
            if not text: raise ValueError("Missing Vietnamese text: "+str(seg.index))
            voice=self.voices.get(str(seg.speaker)) or (female if seg.gender=="female" else male)[seg.speaker%4]
            if voice not in voices: raise RuntimeError("Unavailable ZeroTTS voice: "+voice)
            path=out_dir/("seg_%04d.wav"%seg.index)
            if not path.is_file() or path.stat().st_size<1024:
                audio=engine.synthesize(text,voice=voice)
                engine.save_audio(audio,str(path))
                # ZeroTTS emits 48 kHz; VietDub's timeline mixer expects
                # precisely 44.1 kHz for all sentence WAVs.
                import math
                import numpy as np
                import soundfile as sf
                from scipy.signal import resample_poly
                samples, rate = sf.read(path, dtype="float32")
                if samples.ndim != 1:
                    samples = samples.mean(axis=1)
                if rate != 44100:
                    factor = math.gcd(rate, 44100)
                    samples = resample_poly(samples, 44100 // factor, rate // factor)
                sf.write(path, np.asarray(samples,dtype="float32"), 44100, subtype="PCM_16")
            if not path.is_file() or path.stat().st_size<1024: raise RuntimeError("TTS output missing: "+str(path))
            seg.audio_vi=str(path)
        return segments
