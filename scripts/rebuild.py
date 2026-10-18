#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only OR PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 天川澪 (Coko_Iya). Part of MioVRCA: https://github.com/CokoIya/MioVRC_AssetManager (terms in LICENSE.md)
"""重新整理列表。手动删改了文件之后运行一次：

    python scripts/rebuild.py

- index.json：每个方案的校验值和大小按 recipes/ 中的文件重算（文件已删除的方案从列表去掉）；
- fits.json：按 fits/ 中的全部实测数据重新汇总；
- creators.json：按 profiles/ 中的名片重建（关注人数只算公开了关注列表的名片）；
- works.json：按 works/ 中的作品重建，同时读取作品议题的点赞数。
"""
import datetime
import glob
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_MAX = 50


def api(path):
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "MioVRCA-community"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(base + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def issues(label, state):
    """Read issue reaction summaries in pages of 100, excluding pull requests."""
    repo = os.environ["GITHUB_REPOSITORY"]
    out = []
    for page in range(1, PAGES_MAX + 1):
        items = api("/repos/%s/issues?%s" % (repo, urllib.parse.urlencode({"labels": label, "state": state, "per_page": 100, "page": page})))
        out += [it for it in items if "pull_request" not in it]
        if len(items) < 100:
            break
    return out


def count_likes():
    """Refresh likes for original work issues; a replacement keeps its original issue."""
    thumbs = {it["number"]: max(0, int((it.get("reactions") or {}).get("+1", 0))) for it in issues("作品", "all")}
    likes = {w["id"]: thumbs.get(w.get("issue"), 0) for w in load_works()}
    if likes != read_json(os.path.join(ROOT, "likes.json"), {}):
        write_json(os.path.join(ROOT, "likes.json"), likes)
    return sum(likes.values())


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path, empty):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return empty


def write_json(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def file_info(path):
    with open(path, "rb") as f:
        b = f.read()
    return hashlib.sha256(b).hexdigest(), len(b)


def load_index():
    idx = read_json(os.path.join(ROOT, "index.json"), {})
    idx.setdefault("format", "miovrca-community")
    idx.setdefault("schema", 1)
    idx.setdefault("recipes", [])
    return idx


def rebuild_fits():
    """fits/ 中的实测数据汇总成 fits.json：同一位玩家对同一件衣服、同一个素体只算最新的一条。"""
    latest = {}  # (玩家, 衣服|素体|prefab) → 记录
    for path in sorted(glob.glob(os.path.join(ROOT, "fits", "*.json"))):
        sub = read_json(path, {})
        who = str(sub.get("author") or os.path.basename(path))
        for r in sub.get("records") or []:
            key = "%s|%s|%s" % (r["asset"]["boothId"], r["base"].strip().lower(), (r.get("prefab") or "").lower())
            old = latest.get((who, key))
            if old is None or r.get("at", 0) >= old.get("at", 0):
                latest[(who, key)] = r
    fits = {}
    for (_, key), r in sorted(latest.items()):
        f = fits.setdefault(key, {"n": 0, "ok": 0, "clean": 0})
        f["n"] += 1
        if r.get("ok"):
            f["ok"] += 1
        if r.get("clip", 0) == 0:
            f["clean"] += 1
        for s in r.get("shapes") or []:
            f.setdefault("shapes", {})
            f["shapes"][s] = f["shapes"].get(s, 0) + 1
        if r.get("cutter"):
            f["cutter"] = f.get("cutter", 0) + 1
    write_json(os.path.join(ROOT, "fits.json"), {"format": "miovrca-community-fits", "schema": 1, "updated": now(), "fits": fits})
    return len(fits)


def load_cards():
    """profiles/ 中的名片：用户名 → 名片（文件名与名片中的用户名不一致的不算）。"""
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "profiles", "*.json"))):
        c = read_json(path, None)
        login = os.path.basename(path)[:-5]
        if isinstance(c, dict) and c.get("login") == login and c.get("nickname"):
            out[login] = c
    return out


def load_works():
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "works", "*.json"))):
        w = read_json(path, None)
        if isinstance(w, dict) and w.get("id") == os.path.basename(path)[:-5] and rules.work_id_ok(w.get("id")):
            out.append(w)
    return out


def rebuild_creators():
    """creators.json：每张名片一行（昵称、头像、常用素体、语言、公开的生日、关注人数、作品数、方案数）。"""
    cards, works = load_cards(), load_works()
    followers, n_works, n_recipes = {}, {}, {}
    for login, c in cards.items():
        for f in set(c.get("following") or []):
            if f != login:
                followers[f] = followers.get(f, 0) + 1
    for w in works:
        n_works[w.get("author")] = n_works.get(w.get("author"), 0) + 1
    for e in load_index()["recipes"]:
        if e.get("login"):
            n_recipes[e["login"]] = n_recipes.get(e["login"], 0) + 1
    rows = []
    for login, c in sorted(cards.items()):
        row = {"login": login, "nickname": c["nickname"]}
        for k in ("avatar", "bases", "langs", "birthday"):
            if c.get(k):
                row[k] = c[k]
        row["followers"], row["works"] = followers.get(login, 0), n_works.get(login, 0)
        if n_recipes.get(login):
            row["recipes"] = n_recipes[login]
        row["updated"] = c.get("updated") or now()
        rows.append(row)
    write_json(os.path.join(ROOT, "creators.json"), {"version": 1, "updated": now(), "creators": rows})
    return len(rows)


def rebuild_works(refresh_likes=True):
    """Rebuild works, refreshing reactions when a GitHub repository is configured."""
    if refresh_likes and os.environ.get("GITHUB_REPOSITORY"):
        count_likes()
    likes = read_json(os.path.join(ROOT, "likes.json"), {})
    rows = []
    for w in load_works():
        row = {"id": w["id"], "author": w.get("author", ""), "title": w.get("title", "")}
        if w.get("cover"):
            row["cover"] = w["cover"]
        if w.get("base"):
            row["base"] = w["base"]
        if w.get("based_on"):
            row["based_on"] = w["based_on"]
        vk = rules.video_kind(w.get("video") or "")
        if vk:
            row["video_kind"] = vk
        if w.get("recipe"):
            row["has_recipe"] = True
        row["likes"] = int(likes.get(w["id"], 0)) if isinstance(likes, dict) else 0
        row["issue"], row["created"] = w.get("issue", 0), w.get("created", "")
        if w.get("updated"):
            row["updated"] = w["updated"]
        rows.append(row)
    rows.sort(key=lambda r: (r["created"], r["id"]), reverse=True)
    write_json(os.path.join(ROOT, "works.json"), {"version": 1, "updated": now(), "works": rows})
    return len(rows)


def rebuild():
    idx = load_index()
    keep = []
    for e in idx["recipes"]:
        path = os.path.join(ROOT, e.get("file") or "")
        if not os.path.isfile(path):
            print("列表中的 %s 没有文件，已从列表去掉" % e.get("id"))
            continue
        e["sha256"], e["size"] = file_info(path)
        keep.append(e)
    keep.sort(key=lambda e: (e.get("added") or "", e["id"]), reverse=True)
    idx["recipes"] = keep
    n = rebuild_fits()
    sha, size = file_info(os.path.join(ROOT, "fits.json"))
    idx["fits"] = {"file": "fits.json", "sha256": sha, "size": size}
    idx["updated"] = now()
    write_json(os.path.join(ROOT, "index.json"), idx)
    return len(keep), n, rebuild_creators(), rebuild_works()


if __name__ == "__main__":
    os.environ.setdefault("GITHUB_REPOSITORY", "CokoIya/MioVRCA-community")
    recipes, fits, creators, works = rebuild()
    print("方案 %d 个，实测数据 %d 组，创作者 %d 位，作品 %d 个" % (recipes, fits, creators, works))
