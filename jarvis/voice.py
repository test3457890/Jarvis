"""Ears and mouth. Speech-to-text with faster-whisper, text-to-speech with the
built-in Windows voice (or a Piper neural voice). Everything runs locally."""
import collections
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np

RATE = 16000
BLOCK = 480  # 30 ms


# ============================================================ mouth
JARVIS_VOICES = ("george", "ryan", "united kingdom", "great britain")
# TUKI prefers a clearly different installed voice. Windows names include the language.
TUKI_VOICES = ("zira", "aria", "jenny", "hazel", "susan", "david", "mark", "united states")


def voice_profile(cfg, assistant="jarvis"):
    """Describe which engine and voice preferences to use for an assistant."""
    if assistant == "tuki":
        choice = cfg.get("tuki_voice_choice", "auto")
        piper = cfg.get("tuki_piper_model", "")
        wanted = cfg.get("tuki_sapi_voice_contains", "").lower()
        return {"assistant": "tuki", "piper_model": piper if choice in ("auto", "piper") else "",
                "preferences": tuple(filter(None, (wanted,) + TUKI_VOICES)),
                "rate": int(cfg.get("tuki_speech_rate", 200)), "avoid_jarvis": True}
    choice = cfg.get("voice_choice", "auto")
    use_piper = cfg.get("piper_model") and (choice == "piper" or (choice == "auto" and cfg.get("tts") == "piper"))
    wanted = cfg.get("sapi_voice_contains", "").lower()
    return {"assistant": "jarvis", "piper_model": cfg.get("piper_model", "") if use_piper else "",
            "preferences": tuple(filter(None, (wanted,) + JARVIS_VOICES)),
            "rate": int(cfg.get("speech_rate", 185)), "avoid_jarvis": False}


def pick_voice(voices, preferences, avoid=None):
    """Return (voice, matched) from installed voices. voices have .id and .name."""
    for preference in preferences:
        for voice in voices:
            if preference in voice.name.lower() and voice.id != avoid:
                return voice, True
    for voice in voices:  # A distinct fallback voice is better than the same one.
        if voice.id != avoid:
            return voice, False
    return (voices[0] if voices else None), False


class Speaker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.speaking = threading.Event()
        self._q = queue.Queue()
        self._generation = 0
        self._guard = threading.Lock()
        threading.Thread(target=self._worker, daemon=True, name="tts").start()

    def say(self, text: str, assistant: str = "jarvis"):
        text = re.sub(r"[*#`_>|]", "", text).strip()
        if text:
            with self._guard:
                self._q.put((self._generation, text, assistant if assistant in ("jarvis", "tuki") else "jarvis"))

    def stop(self):
        with self._guard:
            self._generation += 1
            while True:
                try:
                    self._q.get_nowait()
                    self._q.task_done()
                except queue.Empty:
                    break

    def _stopped(self, generation):
        return generation != self._generation

    def wait(self):
        self._q.join()

    def _worker(self):
        engine = None
        while True:
            generation, text, assistant = self._q.get()
            if self._stopped(generation):
                self._q.task_done()
                continue
            self.speaking.set()
            try:
                profile = voice_profile(self.cfg, assistant)
                if profile["piper_model"]:
                    try:
                        self._piper(text, generation, profile["piper_model"])
                        continue
                    except (OSError, subprocess.SubprocessError) as error:
                        print(f"[voice] Piper unavailable, trying the Windows voice: {type(error).__name__}")
                if engine is None:
                    engine = self._windows_voice()
                self._apply_profile(engine, profile)
                if self._stopped(generation):
                    continue
                engine.say(text)
                engine.startLoop(False)
                try:
                    while engine.isBusy() and not self._stopped(generation):
                        engine.iterate()
                        time.sleep(0.01)
                    if self._stopped(generation):
                        engine.stop()
                finally:
                    engine.endLoop()
            except Exception as e:
                print(f"[voice] Speech failed: {e}")
                engine = None
            finally:
                time.sleep(0.25)  # let the room echo die before listening again
                self.speaking.clear()
                self._q.task_done()

    def _windows_voice(self):
        import pyttsx3

        return pyttsx3.init()

    def _apply_profile(self, engine, profile):
        voices = engine.getProperty("voices")
        jarvis, _ = pick_voice(voices, voice_profile(self.cfg, "jarvis")["preferences"])
        if profile["avoid_jarvis"]:
            voice, _ = pick_voice(voices, profile["preferences"], avoid=jarvis.id if jarvis else None)
        else:
            voice = jarvis
        if voice is not None:
            engine.setProperty("voice", voice.id)
        engine.setProperty("rate", profile["rate"])

    def describe(self, assistant="jarvis"):
        """Name the voice an assistant will use, for the HUD preview."""
        profile = voice_profile(self.cfg, assistant)
        if profile["piper_model"]:
            return f"Piper voice {os.path.basename(profile['piper_model'])}"
        try:
            import pyttsx3
            voices = pyttsx3.init().getProperty("voices")
        except Exception:
            return "Windows voice"
        jarvis, _ = pick_voice(voices, voice_profile(self.cfg, "jarvis")["preferences"])
        if assistant != "tuki":
            return f"Windows voice {jarvis.name}" if jarvis else "Windows voice"
        voice, matched = pick_voice(voices, profile["preferences"], avoid=jarvis.id if jarvis else None)
        if voice is None or (jarvis and voice.id == jarvis.id):
            return "the Jarvis voice at a different speed, because only one Windows voice is installed"
        return f"Windows voice {voice.name}" + ("" if matched else " (the closest available)")

    def _piper(self, text, generation, model=None):
        fd, wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with subprocess.Popen([self.cfg.get("piper_exe", "piper"), "--model", model or self.cfg["piper_model"],
                                   "--output_file", wav], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
                deadline = time.monotonic() + 30
                first = True
                while True:
                    if self._stopped(generation) or time.monotonic() > deadline:
                        process.kill()
                        process.communicate()
                        return
                    try:
                        process.communicate(input=text if first else None, timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        first = False
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, process.args)
            if self._stopped(generation):
                return
            with wave.open(wav, 'rb') as audio:
                duration = audio.getnframes() / audio.getframerate()
            import winsound
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline and not self._stopped(generation):
                time.sleep(0.02)
            winsound.PlaySound(None, 0)
        finally:
            try:
                os.remove(wav)
            except OSError:
                pass


# ============================================================ ears
def load_whisper(cfg):
    from faster_whisper import WhisperModel
    name = cfg.get("whisper_model", "small.en")
    device = cfg.get("whisper_device", "auto")
    tries = [("cuda", "float16"), ("cpu", "int8")] if device == "auto" else \
        [(device, "float16" if device == "cuda" else "int8")]
    last = None
    for dev, ctype in tries:
        try:
            model = WhisperModel(name, device=dev, compute_type=ctype)
            # GPU problems (missing CUDA DLLs) only show up on first use, so test now.
            list(model.transcribe(np.zeros(RATE // 2, dtype=np.float32), language="en")[0])
            print(f"[voice] Speech recognition: whisper {name} on {dev}")
            return model
        except Exception as e:
            last = e
    raise RuntimeError(f"Could not load speech recognition: {last}")


class Listener:
    """Always-on listening. Keeps a short rolling transcript of the room so Jarvis can
    join a conversation, and fires on_command when someone says the wake word."""

    def __init__(self, cfg, speaker: Speaker, on_command, on_event=lambda *a: None):
        self.cfg = cfg
        self.speaker = speaker
        self.on_command = on_command
        self.on_event = on_event
        self.model = load_whisper(cfg)
        self.room = collections.deque()  # (time, text)
        self.follow_until = 0.0
        self.paused = threading.Event()
        self._audio = queue.Queue()
        self._stt_lock = threading.Lock()
        words = tuple(dict.fromkeys([*cfg["wake_words"], "tuki"]))
        self._wake = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b[,.!?]*\s*", re.I)

    def keep_listening_for_follow_up(self):
        self.follow_until = time.time() + self.cfg.get("follow_up_seconds", 8)

    def room_context(self) -> str:
        cutoff = time.time() - self.cfg.get("room_context_seconds", 120)
        while self.room and self.room[0][0] < cutoff:
            self.room.popleft()
        return "\n".join(t for _, t in list(self.room)[:-1])

    def run(self):
        import sounddevice as sd
        threading.Thread(target=self._segmenter, daemon=True, name="vad").start()
        with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK,
                            callback=lambda data, *_: self._audio.put(data[:, 0].copy())):
            self.on_event("status", "listening")
            while True:
                time.sleep(1)

    def _segmenter(self):
        """Simple energy-based voice activity detection with an adaptive noise floor."""
        noise = 0.005
        sens = float(self.cfg.get("mic_sensitivity", 1.0)) or 1.0
        pre = collections.deque(maxlen=10)  # 300 ms of audio before speech starts
        speech, silent_blocks, in_speech = [], 0, False
        while True:
            block = self._audio.get()
            if (self.speaker and self.speaker.speaking.is_set()) or self.paused.is_set():
                speech, in_speech, silent_blocks = [], False, 0
                pre.clear()
                continue
            level = float(np.sqrt(np.mean(block ** 2)))
            start_thr = max(noise * 3.0, 0.012) / sens
            if not in_speech:
                noise = 0.97 * noise + 0.03 * min(level, 0.05)
                pre.append(block)
                if level > start_thr:
                    in_speech, speech, silent_blocks = True, list(pre), 0
                continue
            speech.append(block)
            silent_blocks = silent_blocks + 1 if level < start_thr * 0.6 else 0
            too_long = len(speech) * BLOCK > RATE * 25
            if silent_blocks > 27 or too_long:  # ~0.8 s of quiet ends the sentence
                audio = np.concatenate(speech)
                in_speech, speech = False, []
                pre.clear()
                if len(audio) > RATE * 0.4:
                    threading.Thread(target=self._handle, args=(audio,), daemon=True).start()

    def _handle(self, audio):
        with self._stt_lock:
            segs, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                            condition_on_previous_text=False)
            text = " ".join(s.text for s in segs if s.no_speech_prob < 0.7).strip()
        if not text or re.fullmatch(r"[\W_]*(thank you|thanks for watching|you)?[\W_]*", text, re.I):
            return  # whisper's usual hallucinations on silence
        now = time.time()
        self.room.append((now, text))
        self.on_event("heard", text)
        m = self._wake.search(text)
        if m:
            # Keep the whole sentence: "what do you think, Jarvis?" still makes sense.
            rest = (text[:m.start()] + " " + text[m.end():]).strip(" ,.!?")
            if m[1].casefold() == "tuki":
                command = f"Tuki: {rest}"
            else:
                command = text if rest else ""  # "" = just the name was said
        elif now < self.follow_until:
            command = text
        else:
            return
        self.follow_until = 0
        self.on_command(command, self.room_context())
