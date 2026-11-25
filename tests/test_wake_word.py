from app.voice.wake_word import WakeWordListener


def test_wake_word_threshold_and_debounce(tmp_path):
    model_path = tmp_path / "hey_shu.onnx"
    model_path.write_bytes(b"test-only-not-a-model")
    listener = WakeWordListener(model_path, threshold=0.6, debounce_seconds=2)

    assert not listener._should_activate({"hey_shu": 0.59}, 10.0)
    assert listener._should_activate({"hey_shu": 0.8}, 10.0)
    assert not listener._should_activate({"hey_shu": 0.9}, 11.0)
    assert listener._should_activate({"hey_shu": 0.9}, 12.1)


def test_wake_word_requires_custom_model(tmp_path):
    try:
        WakeWordListener(tmp_path / "missing.onnx")
    except FileNotFoundError as error:
        assert "trained Hey SHU" in str(error)
    else:
        raise AssertionError("Missing wake-word model should be rejected")
