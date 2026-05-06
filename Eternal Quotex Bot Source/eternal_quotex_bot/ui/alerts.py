import winsound
import threading
import os
from pathlib import Path

def play_alert_sound(enabled: bool):
    if not enabled:
        return
    
    def _play():
        # Using built-in system sound for simplicity and reliability
        try:
            winsound.Beep(880, 500) # Frequency, Duration
        except Exception:
            pass
            
    threading.Thread(target=_play, daemon=True).start()
