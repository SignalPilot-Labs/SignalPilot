import threading
import time
from concurrent.futures import ThreadPoolExecutor

from signalpilot._server.session_locks import SessionConnectionLocks


def test_same_file_connections_are_serialized() -> None:
    locks = SessionConnectionLocks()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first() -> None:
        with locks.hold("notebooks/intro.py"):
            first_entered.set()
            assert release_first.wait(timeout=1)

    def second() -> None:
        assert first_entered.wait(timeout=1)
        with locks.hold("notebooks/intro.py"):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first)
        second_future = executor.submit(second)
        assert first_entered.wait(timeout=1)
        time.sleep(0.05)
        assert not second_entered.is_set()
        release_first.set()
        first_future.result(timeout=1)
        second_future.result(timeout=1)

    assert second_entered.is_set()


def test_different_file_connections_are_independent() -> None:
    locks = SessionConnectionLocks()
    second_entered = threading.Event()

    def enter_second() -> None:
        with locks.hold("notebooks/charting.py"):
            second_entered.set()

    with locks.hold("notebooks/intro.py"):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(enter_second)
            assert second_entered.wait(timeout=1)
            future.result(timeout=1)
