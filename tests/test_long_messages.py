import time

import pytest


@pytest.fixture
def run(vault, mod):
    handle = mod("commands").handle
    for number in range(60):
        handle(f'save "Person Number{number}" likes tea', platform="cli", vault=vault)
    handle("save Priya likes jam", platform="cli", vault=vault)
    return lambda text: handle(text, platform="cli", vault=vault)


def _timed(run, text):
    run(text)
    started = time.perf_counter()
    reply = run(text)
    return reply, time.perf_counter() - started


def test_400_words_with_no_name_is_fast(run):
    reply, seconds = _timed(run, " ".join(f"word{i}" for i in range(400)))
    print(f"\n400 words, no name: {seconds * 1000:.1f} ms")
    assert reply == "No one called word0 yet."
    assert seconds < 0.1


def test_400_words_with_near_names_is_fast(run):
    reply, seconds = _timed(run, " ".join(f"persn numbr{i}" for i in range(200)))
    print(f"\n400 words, near names: {seconds * 1000:.1f} ms")
    assert seconds < 0.1


def test_name_within_twelve_words_still_found(run):
    assert "likes jam" in run("so tell me again what does priya like to eat jam")
