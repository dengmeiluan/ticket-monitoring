# -*- coding: utf-8 -*-
"""r357 config UX: eager watch hydration, in-place route swap, calmer surfaces."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
STYLE = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)


def _between(start, end):
    return SRC[SRC.index(start):SRC.index(end, SRC.index(start))]


def test_watch_data_is_prefetched_on_config_entry():
    assert "loading:false,loadedOnce:false" in SRC
    load_cfg = _between("async function loadCfg(){", "/* ===== r351")
    assert "try{loadCfgWatch()}catch(e){}" in load_cfg
    switch = _between("function switchView(v,hist){", "/* URL 深链恢复视图")
    assert "if(v==='cfg'&&CFG){try{loadCfgWatch()}catch(e){}}" in switch
    watch = _between("async function loadCfgWatch(force){", "/* 未保存草稿守卫")
    for needle in ("CFG_WATCH.loading=true", "CFG_WATCH.loadedOnce=true",
                   "navN-watch", "cfgwatch-skel", "正在读取关注航班"):
        assert needle in watch, needle


def test_route_swap_is_in_place_and_keeps_copy_reverse_path_clear():
    assert "function swapRouteEnds(i,j,btn){" in SRC
    assert 'onclick="swapRouteEnds(${i},${j},this)"' in SRC
    assert "交换起降" in SRC
    assert 'onclick="reverseRoute(${i},${j},this)"' not in SRC
    assert "复制该航线全部配置为同方向新航线" in SRC
    fn = _between("function swapRouteEnds(i,j,btn){", "function reverseRoute(i,j,btn){")
    for needle in ("r.from=to", "r.from_name=tn", "r.to=from", "r.to_name=fn",
                   "openConfirm('交换起降？'", "保存后生效"):
        assert needle in fn, needle


def test_config_surface_pass_removes_nested_heavy_borders():
    for needle in (
        "#cfgview .lgcard{border-color:transparent",
        "#cfgview .ucard .ucard{border:0",
        "#cfgview .cnav{border-color:transparent",
        "#cfgview .cnavst{border:0",
        "#cfgview .cfgdeck{border:0",
        "#cfgview .seclab .secicon{width:auto;height:auto;background:transparent;border:0",
        "#cfgview .lggrid{gap:10px",
        "#cfgview .uhead{padding-bottom:11px;margin-bottom:13px;border-bottom",
    ):
        assert needle in STYLE, needle
