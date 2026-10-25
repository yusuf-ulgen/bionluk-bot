import sys
import pytest
from src.autostart import is_autostart_enabled, set_autostart, is_windows


@pytest.mark.skipif(not is_windows(), reason="Windows registry testi yalnızca Windows'ta çalışır")
def test_autostart_toggle():
    initial_state = is_autostart_enabled()

    try:
        # 1. Etkinleştir
        ok_enable = set_autostart(True)
        assert ok_enable is True
        assert is_autostart_enabled() is True

        # 2. Kaldır
        ok_disable = set_autostart(False)
        assert ok_disable is True
        assert is_autostart_enabled() is False
    finally:
        # Test sonrası önceki durumuna geri al
        set_autostart(initial_state)
