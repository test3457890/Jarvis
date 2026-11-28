"""Ears and mouth. Speech-to-text with faster-whisper, text-to-speech with the
built-in Windows voice (or a Piper neural voice). Everything runs locally."""
import collections
import os
import queue
import re
import secrets
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
    if preferences:
        for voice in voices:
            if voice.name.casefold() == preferences[0].casefold() and voice.id != avoid:
                return voice, True
    for preference in preferences:
        for voice in voices:
            if preference in voice.name.lower() and voice.id != avoid:
                return voice, True
    for voice in voices:  # A distinct fallback voice is better than the same one.
        if voice.id != avoid:
            return voice, False
    return (voices[0] if voices else None), False


def installed_voice_names():
    """Read installed system voice names for the local HUD only."""
    try:
        import pyttsx3
        voices = pyttsx3.init().getProperty("voices")
        return list(dict.fromkeys(v.name[:120] for v in voices[:64] if isinstance(v.name, str)))
    except Exception:
        return []


def is_british_voice(name: str) -> bool:
    low = (name or "").lower()
    return any(tok in low for tok in ("united kingdom", "great britain", "en-gb", "en_gb", "george", "hazel", "susan", "ryan"))


def audio_devices() -> dict:
    """List local audio input (microphone) and output (speaker) devices via sounddevice."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default_in, default_out = sd.default.device
        inputs, outputs = [], []
        for idx, dev in enumerate(devices):
            name = str(dev.get("name", f"Device {idx}"))[:120]
            if dev.get("max_input_channels", 0) > 0:
                inputs.append({"index": idx, "name": name, "default": idx == default_in})
            if dev.get("max_output_channels", 0) > 0:
                outputs.append({"index": idx, "name": name, "default": idx == default_out})
        return {"available": True, "inputs": inputs[:40], "outputs": outputs[:40]}
    except Exception:
        return {"available": False, "inputs": [], "outputs": []}


def assistant_voice(voices, cfg, assistant):
    jarvis, matched = pick_voice(voices, voice_profile(cfg, "jarvis")["preferences"])
    if assistant != "tuki":
        return jarvis, matched
    wanted = cfg.get("tuki_sapi_voice_contains", "").lower()
    if wanted:
        # An explicit installed choice can intentionally match Jarvis. Distinct
        # fallback applies only to Automatic or a choice that is unavailable.
        selected, matched = pick_voice(voices, (wanted,))
        if matched:
            return selected, True
    return pick_voice(voices, voice_profile(cfg, "tuki")["preferences"], avoid=jarvis.id if jarvis else None)


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
        voice, _ = assistant_voice(voices, self.cfg, profile["assistant"])
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
        voice, matched = assistant_voice(voices, self.cfg, assistant)
        if voice and matched and self.cfg.get("tuki_sapi_voice_contains"):
            return f"Windows voice {voice.name}"
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
        self.room = collections.deque(maxlen=128)  # bounded, temporary (time, text)
        self.follow_until = 0.0
        self.paused = threading.Event()
        self._generation = 0
        self._audio = queue.Queue(maxsize=64)
        self._stt_lock = threading.Lock()
        self._manual_lock = threading.RLock()
        self._manual = None
        self._last_level_ts = 0.0
        words = tuple(dict.fromkeys([*cfg["wake_words"], "tuki"]))
        self._wake = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b[,.!?]*\s*", re.I)

    def keep_listening_for_follow_up(self):
        seconds = self.cfg.get("follow_up_seconds", 8)
        self.follow_until = time.time() + seconds if seconds and not self.paused.is_set() else 0

    def clear_context(self):
        self.room.clear()

    def pause(self):
        self.paused.set()
        self._generation += 1
        self.cancel_manual()
        self.clear_context()
        self.follow_until = 0

    def resume(self):
        self._generation += 1
        self.paused.clear()

    def begin_manual(self):
        """Capture at most 25 seconds, then preview locally without issuing a command."""
        with self._manual_lock:
            if self.paused.is_set():
                raise ValueError("Resume Mic before recording.")
            if self._manual is not None:
                raise ValueError("A recording or transcription is already active.")
            if self.speaker and self.speaker.speaking.is_set():
                raise ValueError("Use Stop before recording while Jarvis is speaking.")
            self._generation += 1
            self.follow_until = 0
            self.clear_context()
            capture_id = secrets.token_urlsafe(16)
            timer = threading.Timer(25, self._expire_manual, args=(capture_id,))
            timer.daemon = True
            self._manual = {"id": capture_id, "blocks": [], "samples": 0,
                            "generation": self._generation, "timer": timer, "recording": True}
            timer.start()
            self.on_event("dictation", {"state": "recording", "id": capture_id})
            return {"ok": True, "id": capture_id, "limit_seconds": 25}

    def _expire_manual(self, capture_id):
        with self._manual_lock:
            if self._manual and self._manual["id"] == capture_id:
                self.finish_manual(capture_id)

    def cancel_manual(self):
        with self._manual_lock:
            capture, self._manual = self._manual, None
            if capture:
                capture["timer"].cancel()
                capture["blocks"].clear()
                self._generation += 1
                self.on_event("dictation", {"state": "cancelled", "id": capture["id"]})

    def finish_manual(self, capture_id):
        with self._manual_lock:
            capture = self._manual
            if not capture or capture["id"] != capture_id:
                raise ValueError("This recording is no longer active.")
            if not capture["recording"]:
                return {"ok": True}
            capture["recording"] = False
            capture["timer"].cancel()
            blocks, capture["blocks"] = capture["blocks"], []
            self.on_event("dictation", {"state": "transcribing", "id": capture_id})
        threading.Thread(target=self._preview_manual, args=(capture, blocks), daemon=True).start()
        return {"ok": True}

    def _preview_manual(self, capture, blocks):
        text, error = "", ""
        try:
            if capture["samples"] < RATE * 0.4:
                error = "Recording too short. Hold the button while speaking."
            else:
                with self._stt_lock:
                    # A cancelled capture must not start transcription after waiting for the model.
                    if self._manual is not capture or capture["generation"] != self._generation:
                        return
                    segs, _ = self.model.transcribe(np.concatenate(blocks), language="en", beam_size=1,
                                                  vad_filter=False, condition_on_previous_text=False)
                    text = " ".join(s.text for s in segs if s.no_speech_prob < 0.7).strip()[:4000]
                if not text or _HALLUCINATION.fullmatch(text):
                    text, error = "", "No clear speech detected. Try again."
        except Exception:
            error = "Local transcription failed. Check the speech model and microphone."
        finally:
            blocks.clear()
        with self._manual_lock:
            if (self._manual is not capture or capture["generation"] != self._generation
                    or self.paused.is_set()):
                return
            self._manual = None
            self._generation += 1
            self.on_event("dictation", {"state": "preview", "id": capture["id"], "text": text, "error": error})

    def _receive(self, data, *_):
        # The stream is open while paused, but no sample enters a queue or transcription.
        with self._manual_lock:
            if self.paused.is_set() or (self.speaker and self.speaker.speaking.is_set()):
                return
            now = time.monotonic()
            if now - self._last_level_ts >= 0.15:
                self._last_level_ts = now
                try:
                    rms = float(np.sqrt(np.mean(data[:, 0] ** 2)))
                    self.on_event("mic_level", {"level": round(min(1.0, rms * 12.0), 3)})
                except Exception:
                    pass
            if self._manual is not None:
                capture = self._manual
                if capture["recording"] and capture["samples"] < RATE * 25:
                    block = data[:RATE * 25 - capture["samples"], 0].copy()
                    capture["blocks"].append(block)
                    capture["samples"] += len(block)
                return
            if self.cfg.get("voice_input_mode", "wake") == "manual":
                return
            try:
                self._audio.put_nowait((data[:, 0].copy(), self._generation))
            except queue.Full:
                # Dropping stale input is preferable to an unbounded microphone backlog.
                pass

    def room_context(self) -> str:
        seconds = self.cfg.get("room_context_seconds", 120)
        if not seconds or self.paused.is_set():
            self.clear_context()
            return ""
        cutoff = time.time() - seconds
        while self.room and self.room[0][0] < cutoff:
            self.room.popleft()
        return "\n".join(t for _, t in list(self.room)[:-1])

    def run(self):
        import sounddevice as sd
        threading.Thread(target=self._segmenter, daemon=True, name="vad").start()
        mic_device = self.cfg.get("mic_device")
        kwargs = {"samplerate": RATE, "channels": 1, "dtype": "float32", "blocksize": BLOCK, "callback": self._receive}
        if isinstance(mic_device, int) and mic_device >= 0:
            kwargs["device"] = mic_device
        with sd.InputStream(**kwargs):
            self.on_event("status", "listening")
            while True:
                time.sleep(1)

    def _segmenter(self):
        """Simple energy-based voice activity detection with an adaptive noise floor."""
        noise = 0.005
        sens = float(self.cfg.get("mic_sensitivity", 1.0)) or 1.0
        pre = collections.deque(maxlen=10)  # 300 ms of audio before speech starts
        speech, silent_blocks, in_speech = [], 0, False
        segment_generation = self._generation
        while True:
            block, generation = self._audio.get()
            if generation != segment_generation:
                speech, in_speech, silent_blocks = [], False, 0
                pre.clear()
                segment_generation = generation
            if (generation != self._generation or self._manual is not None
                    or self.cfg.get("voice_input_mode", "wake") == "manual"
                    or (self.speaker and self.speaker.speaking.is_set()) or self.paused.is_set()):
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
                    threading.Thread(target=self._handle, args=(audio, generation), daemon=True).start()

    def _handle(self, audio, generation=None):
        if self.paused.is_set() or (generation is not None and generation != self._generation):
            return
        with self._stt_lock:
            segs, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                            condition_on_previous_text=False)
            text = " ".join(s.text for s in segs if s.no_speech_prob < 0.7).strip()
        if self.paused.is_set() or (generation is not None and generation != self._generation):
            return
        command = self.interpret(text, time.time())
        if command is not None:
            self.on_command(command, self.room_context())

    def interpret(self, text, now):
        """Turn one transcribed sentence into a command, or None to ignore it."""
        if self.paused.is_set() or not text or _HALLUCINATION.fullmatch(text):
            return None  # whisper's usual output on silence or noise
        if self.cfg.get("room_context_seconds", 120):
            cutoff = now - self.cfg["room_context_seconds"]
            while self.room and self.room[0][0] < cutoff:
                self.room.popleft()
            self.room.append((now, text))
        m = self._wake.search(text)
        if m:
            # Keep the whole sentence: "what do you think, Jarvis?" still makes sense.
            rest = (text[:m.start()] + " " + text[m.end():]).strip(" ,.!?")
            if _STOP_PHRASE.fullmatch(rest):
                command = "stop"
            elif m[1].casefold() == "tuki":
                command = f"Tuki: {rest}"
            else:
                command = text if rest else ""  # "" = just the name was said
        elif now < self.follow_until:
            command = "stop" if _STOP_PHRASE.fullmatch(text.strip(" ,.!?")) else text
        else:
            return None
        self.on_event("heard", text)
        self.follow_until = 0
        return command


# Whisper often invents these on silence or background noise.
_HALLUCINATION = re.compile(
    r"[\W_]*(?:thank you(?: (?:so much|very much))?|thanks for watching|you|bye|"
    r"please subscribe|subtitles by[\w .-]*|\[(?:music|silence|blank_audio)\])?[\W_]*", re.I)
# "Jarvis, stop" cancels a reply that is still being prepared. Jarvis does not listen while it
# speaks (that avoids hearing itself), so this cannot interrupt speech already playing.
_STOP_PHRASE = re.compile(r"(?:please )?(?:stop|cancel|never ?mind|be quiet|that's enough|enough)(?: please)?", re.I)
