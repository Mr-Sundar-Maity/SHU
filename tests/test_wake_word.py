import numpy as np
import pytest

from app.voice.wake_word import WakeActivationGate, WakeWordListener


def test_wake_word_threshold_and_debounce():
    gate = WakeActivationGate(threshold=0.6, debounce_seconds=2)

    assert not gate.should_activate({"hey_shu": 0.59}, 0.0)
    assert not gate.should_activate({"hey_shu": float("nan")}, 0.0)
    assert gate.should_activate({"hey_shu": 0.8}, 0.0)
    assert not gate.should_activate({"hey_shu": 0.9}, 1.0)
    assert gate.should_activate({"hey_shu": 0.9}, 2.1)


def test_wake_word_requires_custom_model(tmp_path):
    try:
        WakeWordListener(tmp_path / "missing.onnx")
    except FileNotFoundError as error:
        assert "trained Hey SHU" in str(error)
    else:
        raise AssertionError("Missing wake-word model should be rejected")


@pytest.mark.parametrize("stop_during_inference", [True, False])
def test_wake_word_listener_drops_detection_after_mute_or_stop(tmp_path, monkeypatch, stop_during_inference):
    from threading import Event

    from app.voice import wake_word

    model_path = tmp_path / "test.onnx"
    model_path.write_bytes(b"fixture")
    muted = Event()
    detected = []
    listener = WakeWordListener(model_path, on_detected=lambda: detected.append(True), mute_event=muted)

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            listener.stop()

        def read(self, frames):
            return np.zeros((frames, 1), dtype=np.int16), False

    class Model:
        def predict(self, frame):
            assert frame.shape == (wake_word.WAKE_BLOCK_SAMPLES,)
            if stop_during_inference:
                listener.stop()
            else:
                muted.set()
            return {"fixture": 0.9}

    monkeypatch.setattr(wake_word.sd, "InputStream", lambda **_options: Stream())
    monkeypatch.setattr(wake_word, "load_wake_word_model", lambda _path: Model())
    listener.run()
    assert detected == []
