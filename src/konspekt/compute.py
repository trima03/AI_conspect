"""Serialize model inference in this process to bound memory use on the desktop."""
import threading

MODEL_LOCK = threading.Lock()
