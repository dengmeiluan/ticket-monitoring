# -*- coding: utf-8 -*-
"""r368: hash task deep link must let a fresh browser reopen open tickets."""
import webui


def test_hash_task_deep_link_seeds_local_task_and_switches_search():
    src = webui.PAGE
    assert "const _hq=location.hash.slice(1)" in src
    assert "const _tid=_hq.slice(5).trim()" in src
    assert "localStorage.setItem('jpsrx_task',_tid)" in src
    seed = src.index("localStorage.setItem('jpsrx_task',_tid)")
    switch = src.index("if(typeof switchView==='function')switchView('search',false)", seed)
    assert switch > seed


def test_task_resume_still_reads_query_for_future_routes():
    src = webui.PAGE
    assert "new URLSearchParams(location.search).get('task')" in src
    i = src.index("function srxTaskResume()")
    j = src.index("if(!id)return;", i)
    k = src.index("URLSearchParams(location.search).get('task')", i)
    assert k < j
