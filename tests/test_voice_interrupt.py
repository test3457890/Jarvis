import importlib.util
import queue
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_stop_drains_speech_queue_and_interrupts_worker(monkeypatch):
    # Load the voice module with native/audio imports stubbed so the real worker
    # control flow can be exercised on both CI operating systems.
    monkeypatch.setitem(sys.modules,'winsound',MagicMock())
    monkeypatch.setitem(sys.modules,'numpy',MagicMock())
    spec=importlib.util.spec_from_file_location('voice_under_test',Path(__file__).parents[1]/'jarvis'/'voice.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.threading,'Thread',MagicMock())
    speaker=module.Speaker({})
    speaker.say('First sentence.')
    speaker.say('Second sentence.')
    speaker.stop()
    assert speaker._q.empty() and speaker._q.unfinished_tasks==0
    speaker.say('New sentence.')
    engine=MagicMock()
    engine.isBusy.return_value=True
    engine.iterate.side_effect=lambda: speaker.stop()
    speaker._windows_voice=lambda:engine
    original=speaker._q.get
    count=0
    def get():
        nonlocal count
        count+=1
        if count>1:
            raise StopIteration
        return original()
    speaker._q.get=get
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    import pytest
    with pytest.raises(StopIteration):
        speaker._worker()
    engine.stop.assert_called_once()
    engine.endLoop.assert_called_once()
    assert speaker._q.unfinished_tasks==0
