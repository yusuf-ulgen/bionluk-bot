import pytest
from src.single_instance import SingleInstanceLock


def test_single_instance_lock():
    lock1 = SingleInstanceLock(port=49991)
    lock2 = SingleInstanceLock(port=49991)

    # 1. kilit başarılı olmalı
    assert lock1.acquire() is True

    # 2. kilit aynı portta kilit alamaz
    assert lock2.acquire() is False

    # 1. kilit bırakıldığında
    lock1.release()

    # 2. kilit artık alabilir
    assert lock2.acquire() is True
    lock2.release()
