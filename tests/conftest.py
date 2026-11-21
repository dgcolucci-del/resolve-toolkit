import pytest


@pytest.fixture(autouse=True)
def video_presente(monkeypatch, request):
    """I render finti dei test sono file vuoti: di default fingiamo che abbiano la traccia video.
    I test con il marcatore `senza_video` vedono il controllo vero."""
    if request.node.get_closest_marker("senza_video"):
        return
    from resolve_toolkit import operazioni
    monkeypatch.setattr(operazioni.audio, "formato", lambda path: {"codec_video": "h264"})
