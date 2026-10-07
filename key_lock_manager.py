import threading


class KeyLockManager:
    """
    Allows only one holder per string key.
    """

    def __init__(self):
        self._active_keys = set()
        self._lock = threading.Lock()

    def acquire(self, key: str | None) -> bool:
        """
        Attempt to acquire a key.
        Returns True if successful.
        Returns False if the key is already checked out.
        """

        if not key:
            return True

        with self._lock:
            if key in self._active_keys:
                return False

            self._active_keys.add(key)
            return True

    def release(self, key: str | None):
        """
        Release a previously acquired key.
        """

        if not key:
            return

        with self._lock:
            self._active_keys.discard(key)