# -*- coding: utf-8 -*-
"""出口历史：重播后「IP 到底变没变」要能自证。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402


def test_exit_history_roundtrip_and_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert webui._exit_history() == []
    for i in range(13):
        webui._exit_history_push("10.0.0.%d" % i)
    hist = webui._exit_history()
    assert len(hist) == 10
    assert hist[-1] == "10.0.0.12"


def test_exit_history_survives_broken_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)
    with open(os.path.join("data", "exit_history.json"), "w",
              encoding="utf-8") as f:
        f.write("{not json")
    assert webui._exit_history() == []
    webui._exit_history_push("1.2.3.4")
    assert webui._exit_history() == ["1.2.3.4"]
