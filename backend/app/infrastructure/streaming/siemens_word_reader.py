from threading import Event, Thread
from time import monotonic

from app.domain.value_objects.stream_trigger_config import SiemensWord


class SiemensWordReader:
    def __init__(self, address: SiemensWord) -> None:
        self.address = address
        self._sample = ("waiting", 0.0)
        self._stop = Event()
        Thread(target=self._poll, daemon=True, name="siemens-word-reader").start()

    @property
    def state(self) -> str:
        state, expires = self._sample
        if state in {"on", "off", "invalid"} and monotonic() >= expires:
            return "unavailable"
        return state

    def close(self) -> None:
        self._stop.set()

    def _poll(self) -> None:
        try:
            from snap7.client import Client
        except ImportError:
            self._sample = ("missing_driver", 0.0)
            return

        address = self.address
        states = {address.on_value: "on", address.off_value: "off"}
        while not self._stop.is_set():
            client = None
            try:
                client = Client()
                client.connect(address.host, address.rack, address.slot, address.port)
                while not self._stop.is_set():
                    started = monotonic()
                    data = client.db_read(address.db_number, address.byte_offset, 2)
                    if len(data) != 2:
                        raise ValueError("Incomplete Siemens WORD")
                    value = int.from_bytes(data, "big")
                    state = states.get(value, "invalid")
                    self._sample = (state, started + 0.75)
                    self._stop.wait(0.2)
            except Exception:
                self._sample = ("unavailable", 0.0)
            finally:
                if client is not None:
                    client.disconnect()
            self._stop.wait(2)
