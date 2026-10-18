#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only OR PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 天川澪 (Coko_Iya). Part of MioVRCA: https://github.com/CokoIya/MioVRC_AssetManager (terms in LICENSE.md)
"""收录一个议题（issue）。由 .github/workflows/accept.yml 运行，也可以手动运行：

    python scripts/accept_issue.py --event <GitHub 事件 JSON 文件>
    python scripts/accept_issue.py --text <议题正文文件> --number 12 --user 名字 [--title 标题] [--reviewed]

议题里的分享码：
- 方案（MIOVRCA-RECIPE-1:）存入 recipes/ 并加入 index.json；实测数据（MIOVRCA-FIT-1:）存入 fits/ 并重新汇总
  fits.json。维护者加上「收录」标签时收录。
- 创作者名片（MIOVRCA-PROFILE-1:）存入 profiles/<用户名>.json，头像重新绘制为 avatars/<用户名>.jpg，重建
  creators.json。名片属于提交议题的 GitHub 账号（不看分享码里写的）。仓库变量 AUTO_PROFILES 不是 false 时自动收录，
  否则等「收录」标签。
- 作品（MIOVRCA-WORK-1:）存入 works/w<号>.json，封面重新绘制为 covers/w<号>.jpg，重建 works.json。维护者加上
  「收录」标签时收录；仓库变量 AUTO_WORKS 为 true 且作品没有网盘链接时自动收录。replace: w<号> 更新自己的作品。
- 删除作品（remove.yml 表单）：作者本人提交时自动删除。

议题的内容都来自提交的人：这里只读取、检查，不执行其中任何东西，也不放进命令行。结果（或没能收录的原因）写入
--result 指定的文件，要做的事（close：已收录，回复并关闭；reply：只回复；none：什么都不做）写入 --outcome 指定的
文件，由工作流回复到议题里。没能收录时退出码为 1。
"""
import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules  # noqa: E402
from miovrca_code import CodeError, find  # noqa: E402
from rebuild import ROOT, file_info, load_index, now, read_json, rebuild_creators, rebuild_fits, rebuild_works, write_json  # noqa: E402

KINDS = {"素体", "衣服", "头发", "皮肤", "表情", "配饰", "道具", "光影", "互动", "面捕", "其他"}
ITEM_KINDS = {"outfit", "part", "toggle", "strip", "skin", "install"}
RECIPE_KEYS = {"format", "schema", "id", "name", "note", "created", "app", "plugin", "base", "hierarchy", "assets", "menus", "imported", "from",
               "author", "links"}
ASSET_KEYS = {"key", "name", "boothId", "url", "prefab", "kind", "version", "object", "place", "active"}
MENU_KEYS = {"root", "parameter", "items"}
ITEM_KEYS = {"kind", "path", "label", "objects", "default", "show", "parameter", "materialsFrom", "materials"}
FIT_KEYS = {"at", "base", "asset", "prefab", "clip", "after", "shapes", "cutter", "hint", "ok", "shared"}
RE_SHOP = re.compile(r"^(gr_)?[A-Za-z0-9_-]{1,40}$")
RE_SHOP_URL = re.compile(r"^https://([a-z0-9-]+\.)*(booth\.pm|gumroad\.com)(/[^\s]*)?$", re.I)

REVIEW = "收录"  # 维护者加的标签
AVATAR_SIZE = (256, 256)
COVER_SIZE = (640, 360)
PICTURE_PIXELS = 40_000_000  # 解码前就拒绝的图片大小（像素）
BANNED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banned.txt")


class Refused(Exception):
    pass


def text(v, most, what, lines=False, need=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise Refused(what + "应为文字")
    if need and not v.strip():
        raise Refused("缺少" + what)
    if len(v) > most:
        raise Refused("%s过长（最多 %d 个字）" % (what, most))
    for c in v:
        if (ord(c) < 0x20 and not (lines and c in "\n\t")) or ord(c) == 0x7F:
            raise Refused(what + "含有无法显示的字符")
    return v


def project_path(p, ext, what):
    text(p, 260, what, need=True)
    if not p.startswith("Assets/") or "\\" in p or "//" in p or not p.lower().endswith(ext):
        raise Refused(what + "不是有效的工程内路径")
    if any(s in ("", ".", "..") for s in p.split("/")):
        raise Refused(what + "不是有效的工程内路径")


def only(d, keys, what):
    if not isinstance(d, dict):
        raise Refused(what + "的格式有误")
    extra = set(d) - keys
    if extra:
        raise Refused("%s中有无法识别的内容：%s" % (what, "、".join(sorted(extra))))


def check_recipe(r):
    """方案的形式和大小（MioVRCA 导入时还会再完整检查一次）。返回菜单项数和方案带的链接。"""
    only(r, RECIPE_KEYS, "方案")
    if r.get("format") != "miovrca-recipe" or r.get("schema") != 1:
        raise Refused("不是第 1 版的 MioVRCA 装配方案")
    text(r.get("name"), 60, "方案名称", need=True)
    text(r.get("note"), 500, "方案备注", lines=True)
    base = r.get("base") or {}
    only(base, {"prefab", "name"}, "素体")
    if base.get("prefab"):
        project_path(base["prefab"], ".prefab", "素体 prefab")
    text(base.get("name"), 60, "素体名称")
    assets, menus = r.get("assets") or [], r.get("menus") or []
    if not isinstance(assets, list) or not isinstance(menus, list):
        raise Refused("方案的格式有误")
    if not assets and not menus:
        raise Refused("方案中没有素材，也没有菜单")
    if len(assets) > 60 or len(menus) > 24:
        raise Refused("方案中的素材或菜单过多")
    for i, a in enumerate(assets):
        what = "第 %d 个素材" % (i + 1)
        only(a, ASSET_KEYS, what)
        project_path(a.get("prefab"), ".prefab", what + "的 prefab")
        text(a.get("name"), 120, what + "的名称", need=True)
        if a.get("kind") not in KINDS:
            raise Refused(what + "的类别无效")
        if a.get("boothId") and not RE_SHOP.match(str(a["boothId"])):
            raise Refused(what + "的商品编号无效")
        if a.get("url") and not RE_SHOP_URL.match(str(a["url"])):
            raise Refused(what + "的链接不是 Booth 或 Gumroad 的商品页")
        obj = text(a.get("object"), 260, what + "的物体名", need=True)
        if "/" in obj:
            raise Refused(what + "的物体名无效")
    items = 0
    for m in menus:
        only(m, MENU_KEYS, "菜单")
        its = m.get("items") or []
        if not isinstance(its, list) or not its:
            raise Refused("方案中有空的菜单计划")
        items += len(its)
        for it in its:
            only(it, ITEM_KEYS, "菜单项")
            if it.get("kind") not in ITEM_KINDS:
                raise Refused("菜单项的类型无效")
            text(it.get("label"), 60, "菜单项名称", need=True)
    if items > 400:
        raise Refused("方案中的菜单项过多")
    if r.get("author"):
        try:
            rules.norm_login(r["author"])
        except rules.RuleError:
            raise Refused("方案的作者不是有效的 GitHub 用户名")
    try:
        links = rules.check_links(r.get("links"), rules.WORK_LINKS)
    except rules.RuleError as e:
        raise Refused("方案的链接无效：%s" % e)
    return items, links


def check_fits(data):
    if not isinstance(data, dict) or data.get("format") != "miovrca-fits" or data.get("schema") != 1:
        raise Refused("不是第 1 版的 MioVRCA 实测数据")
    recs = data.get("records")
    if not isinstance(recs, list) or not recs or len(recs) > 1000:
        raise Refused("实测数据为空，或条数过多")
    out = []
    for i, r in enumerate(recs):
        what = "第 %d 条实测数据" % (i + 1)
        only(r, FIT_KEYS, what)
        a = r.get("asset") or {}
        only(a, {"name", "boothId", "kind"}, what + "的衣服")
        if not RE_SHOP.match(str(a.get("boothId") or "")):
            raise Refused(what + "缺少有效的商品编号")
        text(a.get("name"), 120, what + "的衣服名称", need=True)
        text(r.get("base"), 60, what + "的素体", need=True)
        text(r.get("prefab"), 120, what + "的 prefab")
        for k in ("clip", "after", "at"):
            if not isinstance(r.get(k, 0), int) or not 0 <= r.get(k, 0) < 10 ** 11:
                raise Refused(what + "的数值无效")
        shapes = r.get("shapes") or []
        if not isinstance(shapes, list) or len(shapes) > 64:
            raise Refused(what + "的形态键无效")
        for s in shapes:
            text(s, 100, what + "的形态键名", need=True)
        if r.get("hint", "") not in ("", "author", "local", "community"):
            raise Refused(what + "的来源无效")
        out.append({"at": r.get("at", 0), "base": r["base"], "asset": {"name": a["name"], "boothId": a["boothId"], "kind": a.get("kind", "")},
                    "prefab": r.get("prefab", ""), "clip": r.get("clip", 0), "after": r.get("after", 0), "shapes": shapes,
                    "cutter": bool(r.get("cutter")), "hint": r.get("hint", ""), "ok": bool(r.get("ok"))})
    return out


def form(body):
    """议题表单的各栏：### 标题 → 内容（没填的是 _No response_）。"""
    out = {}
    for m in re.finditer(r"^###\s+(.+?)\s*$\n(.*?)(?=^###\s|\Z)", body, re.M | re.S):
        v = m.group(2).strip()
        v = re.sub(r"^```\w*\n?|\n?```$", "", v).strip()
        out[m.group(1).strip()] = "" if v == "_No response_" else v
    return out


def decoded(body, kind, what):
    """分享码中的 JSON。"""
    try:
        raw = find(body, kind)
    except CodeError as e:
        raise Refused(str(e))
    try:
        return raw, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Refused("分享码中的%s不是有效的 JSON" % what)


def checked(f, value):
    """rules.py 的检查：拒绝时说明原因。"""
    try:
        return f(value)
    except rules.RuleError as e:
        raise Refused(str(e))


def no_banned(*texts):
    words = rules.banned_words(BANNED)
    if words:
        checked(lambda t: rules.check_banned(t, words), [t for t in texts if t])


def path_of(*parts):
    return os.path.join(ROOT, *parts)


def remove_file(p):
    try:
        os.remove(p)
    except FileNotFoundError:
        pass


# ---------- 图片：重新绘制，只留画面 ----------
def redraw(b64, size, dest):
    """把 base64 的 JPEG 重新绘制成 size 大小（居中裁剪）的 JPEG（质量 85，不带任何附加信息），存为 dest。"""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise Refused("工作流缺少 Pillow，无法处理图片（请维护者检查 Actions 的设置）")
    try:
        data = base64.b64decode(b64.replace("\r", "").replace("\n", ""), validate=True)
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "JPEG" or im.width * im.height > PICTURE_PIXELS:
                raise Refused(rules.MESSAGES[rules.ERR_BAD_IMAGE])
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = ImageOps.fit(im, size, Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, "JPEG", quality=85, optimize=True)
    except Refused:
        raise
    except Exception:  # （Pillow 对坏图片会抛出各种异常）
        raise Refused(rules.MESSAGES[rules.ERR_BAD_IMAGE])
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(out.getvalue())
    os.replace(tmp, dest)


# ---------- 方案、实测数据 ----------
def accept_recipe(body, number, user):
    raw, r = decoded(body, "recipe", "方案")
    items, links = check_recipe(r)
    f = form(body)
    name = " ".join((f.get("方案名称") or r["name"]).split())
    note = (f.get("说明") or r.get("note") or "").replace("\r\n", "\n").replace("\r", "\n").strip()  # （网页的多行文字可能带 \r）
    base = " ".join((f.get("适用素体") or (r.get("base") or {}).get("name") or "").split())
    author = " ".join((f.get("署名（选填）") or user or "").split())
    text(name, 60, "方案名称", need=True)
    text(note, 500, "说明", lines=True)
    text(base, 60, "适用素体")
    author = author[:40]
    no_banned(name, note, base, author)
    for k in ("id", "imported", "from", "author", "links"):  # （作者和链接写在列表里：1.8.1 之前的 MioVRCA 读不了带它们的方案文件）
        r.pop(k, None)
    r["name"], r["note"] = name, note
    if not note:
        r.pop("note")
    rid = "issue-%d" % number if number else "r-" + hashlib.sha256(raw).hexdigest()[:12]
    rel = "recipes/%s.json" % rid
    os.makedirs(path_of("recipes"), exist_ok=True)
    write_json(path_of(rel), r)
    sha, size = file_info(path_of(rel))
    entry = {"id": rid, "name": name, "note": note, "base": base, "author": author, "login": login_of(user), "links": links,
             "added": datetime.date.today().isoformat(), "file": rel, "sha256": sha, "size": size, "items": items,
             "assets": [{k: v for k, v in (("name", a["name"]), ("kind", a.get("kind", "")), ("boothId", a.get("boothId", ""))) if v} for a in r.get("assets") or []]}
    entry = {k: v for k, v in entry.items() if v not in ("", None, [])}
    idx = load_index()
    idx["recipes"] = [e for e in idx["recipes"] if e.get("id") != rid]
    idx["recipes"].insert(0, entry)
    idx["updated"] = now()
    write_json(path_of("index.json"), idx)
    rebuild_creators()  # （创作者的方案数）
    return "已收录方案「%s」（编号 %s）。几分钟后，大家就能在 MioVRCA 的「装配方案 → 社区方案」中看到它。谢谢分享！" % (name, rid)


def accept_fits(body, number, user):
    raw, data = decoded(body, "fit", "实测数据")
    recs = check_fits(data)
    os.makedirs(path_of("fits"), exist_ok=True)
    name = "issue-%d.json" % number if number else "manual-%s.json" % now().replace(":", "")
    write_json(path_of("fits", name), {"issue": number, "author": user or "", "at": now(), "records": recs})
    groups = rebuild_fits()
    sha, size = file_info(path_of("fits.json"))
    idx = load_index()
    idx["fits"] = {"file": "fits.json", "sha256": sha, "size": size}
    idx["updated"] = now()
    write_json(path_of("index.json"), idx)
    return "已收录 %d 条实测数据（现在共有 %d 组衣服 × 素体）。其他玩家装配这些衣服时，MioVRCA 会参考它们。谢谢分享！" % (len(recs), groups)


def login_of(user):
    try:
        return rules.norm_login(user or "")
    except rules.RuleError:
        return ""


def need_login(user):
    l = login_of(user)
    if not l:
        raise Refused("无法确认提交者的 GitHub 账号")
    return l


# ---------- 创作者名片 ----------
def accept_profile(body, number, user):
    login = need_login(user)
    _, req = decoded(body, "profile", "名片")
    c = checked(rules.check_card, req)
    no_banned(c["nickname"], c.get("bio"), *(c.get("bases") or []), *(l.get("label") for l in c.get("links") or []))
    card = {"login": login}
    for k in ("nickname", "bio", "langs", "vrchat", "links", "bases", "birthday", "following", "showcase"):
        if k in c:
            card[k] = c[k]
    if "following" in card:
        card["following"] = [f for f in card["following"] if f != login]
        if not card["following"]:
            card.pop("following")
    pic = path_of("avatars", login + ".jpg")
    if c.get("avatar"):
        redraw(c["avatar"], AVATAR_SIZE, pic)
        card["avatar"] = "avatars/%s.jpg" % login
    else:
        remove_file(pic)  # （换回 GitHub 头像）
    card["issue"], card["updated"] = number, now()
    os.makedirs(path_of("profiles"), exist_ok=True)
    write_json(path_of("profiles", login + ".json"), card)
    rebuild_creators()
    return "名片已更新：「%s」（@%s）。几分钟后，它就会出现在 MioVRCA 的「社区（实验性）→ 创作者」中。要修改，在 MioVRCA 中编辑后再提交一次即可。" % (card["nickname"], login)


# ---------- 作品 ----------
def work_request(body):
    _, req = decoded(body, "work", "作品")
    return checked(rules.check_work, req)


def accept_work(body, number, user, created):
    login = need_login(user)
    w = work_request(body)
    no_banned(w["title"], w.get("desc"), w.get("base"), *(a["name"] for a in w.get("assets") or []), *(l.get("label") for l in w.get("links") or []))
    if w.get("replace"):
        wid = w["replace"]
        old = read_json(path_of("works", wid + ".json"), None)
        if not old:
            raise Refused("要更新的作品 %s 不在社区中" % wid)
        if old.get("author") != login:
            raise Refused("只能更新自己的作品（%s 不是 @%s 的作品）" % (wid, login))
        issue, first = old.get("issue") or 0, old.get("created") or created
    else:
        wid, issue, first = "w%d" % number, number, created
        old = read_json(path_of("works", wid + ".json"), None)
        if old and old.get("author") != login:
            raise Refused("作品 %s 已属于其他账号" % wid)
    if w.get("based_on") == wid:
        raise Refused(str(rules.fail(rules.ERR_BAD_REQUEST, "参考的作品编号无效，或与当前作品相同")))
    work = {"id": wid, "author": login}
    for k in ("title", "desc", "video", "base", "assets", "links", "recipe", "based_on"):
        if k in w:
            work[k] = w[k]
    pic = path_of("covers", wid + ".jpg")
    if w.get("cover"):
        redraw(w["cover"], COVER_SIZE, pic)
        work["cover"] = "covers/%s.jpg" % wid
    else:
        remove_file(pic)
    work["issue"], work["created"] = issue, first
    if old or w.get("replace"):
        work["updated"] = now()
    os.makedirs(path_of("works"), exist_ok=True)
    write_json(path_of("works", wid + ".json"), work)
    rebuild_works()
    rebuild_creators()
    if w.get("replace"):
        return "已更新作品 %s「%s」。点赞仍记在原来的议题上。" % (wid, work["title"])
    return "已发布作品 %s「%s」。几分钟后，大家就能在 MioVRCA 的「社区（实验性）→ 作品」中看到它；在这个议题上点 👍 就是点赞。谢谢分享！" % (wid, work["title"])


def accept_remove(body, number, user):
    login = need_login(user)
    wid = (form(body).get("作品编号") or "").strip().lower()
    if not rules.work_id_ok(wid):
        raise Refused("作品编号无效（应为 w 加数字，例如 w12）")
    old = read_json(path_of("works", wid + ".json"), None)
    if not old:
        raise Refused("社区中没有作品 %s" % wid)
    if old.get("author") != login:
        raise Refused("只能删除自己的作品（%s 不是 @%s 的作品）" % (wid, login))
    remove_file(path_of("works", wid + ".json"))
    remove_file(path_of("covers", wid + ".jpg"))
    rebuild_works()
    rebuild_creators()
    return "已删除作品 %s「%s」。" % (wid, old.get("title", ""))


# ---------- 一个议题 ----------
def kind_of(body, title, labels):
    if "作品" in labels and (title.startswith("[删除作品]") or "### 作品编号" in body) and not re.search(r"MIOVRCA-WORK-", body, re.I):
        return "remove"
    for k, name in (("profile", "PROFILE"), ("work", "WORK"), ("recipe", "RECIPE"), ("fit", "FIT")):
        if re.search(r"MIOVRCA-" + name + "-", body, re.I):
            return k
    return ""


def flag(v, default):
    v = (v or "").strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    if v in ("false", "0", "no", "off"):
        return False
    return default


def handle(issue, action, label="", auto_profiles=True, auto_works=False):
    """一个议题该怎样处理：(要做的事, 回复)。没能收录时抛出 Refused。

    action：opened / edited / labeled（GitHub 的事件），或 sweep（定时任务补上漏掉的）。"""
    body = issue.get("body") or ""
    number = int(issue.get("number") or 0)
    user = (issue.get("user") or {}).get("login", "")
    title = issue.get("title") or ""
    labels = {l.get("name") if isinstance(l, dict) else l for l in issue.get("labels") or []}
    if issue.get("state", "open") != "open" and action != "labeled":
        return "none", ""
    reviewed = action == "labeled" and label == REVIEW
    new = action in ("opened", "edited", "sweep")
    created = issue.get("created_at") or now()
    k = kind_of(body, title, labels)
    if k in ("recipe", "fit"):
        if not reviewed:
            return "none", ""
        return "close", accept_recipe(body, number, user) if k == "recipe" else accept_fits(body, number, user)
    if k == "profile":
        if reviewed or new and auto_profiles:
            return "close", accept_profile(body, number, user)
        if action == "opened":
            return "reply", "已收到名片，维护者查看后会收录。"
        return "none", ""
    if k == "work":
        if reviewed:
            return "close", accept_work(body, number, user, created)
        w = work_request(body)  # （先检查：有问题时马上说明）
        if new and auto_works and not rules.has_netdisk(w.get("links") or []):
            return "close", accept_work(body, number, user, created)
        if action == "opened":
            return "reply", "已收到作品，内容检查通过。维护者查看后会发布到社区（届时会在这里回复）。"
        return "none", ""
    if k == "remove":
        if reviewed or new:
            return "close", accept_remove(body, number, user)
        return "none", ""
    if reviewed:
        raise Refused("议题中没有找到分享码（以 MIOVRCA-RECIPE-1:、MIOVRCA-FIT-1:、MIOVRCA-PROFILE-1: 或 MIOVRCA-WORK-1: 开头）")
    return "none", ""


def refusal(e):
    return "没能收录：%s\n\n请修改后重新提交（或编辑这个议题），或在议题里说明情况。" % e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", help="GitHub 事件 JSON 文件（$GITHUB_EVENT_PATH）")
    ap.add_argument("--text", help="议题正文文件")
    ap.add_argument("--number", type=int, default=0)
    ap.add_argument("--user", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--reviewed", action="store_true", help="手动运行时：当作维护者已加上「收录」标签")
    ap.add_argument("--result", default="result.md", help="结果写到这里")
    ap.add_argument("--outcome", default="", help="要做的事（close / reply / none）写到这里")
    a = ap.parse_args()
    auto_profiles, auto_works = flag(os.environ.get("AUTO_PROFILES"), True), flag(os.environ.get("AUTO_WORKS"), False)
    if a.event:
        with open(a.event, encoding="utf-8") as f:
            ev = json.load(f)
        issue, action, label = ev.get("issue") or {}, ev.get("action") or "", (ev.get("label") or {}).get("name", "")
    elif a.text:
        with open(a.text, encoding="utf-8") as f:
            body = f.read()
        issue = {"body": body, "number": a.number, "user": {"login": a.user}, "title": a.title, "labels": ["作品"] if "### 作品编号" in body else []}
        action, label = ("labeled", REVIEW) if a.reviewed else ("opened", "")
    else:
        ap.error("请给出 --event 或 --text")
    try:
        outcome, msg = handle(issue, action, label, auto_profiles, auto_works)
    except Refused as e:
        with open(a.result, "w", encoding="utf-8") as f:
            f.write(refusal(e))
        if a.outcome:
            with open(a.outcome, "w", encoding="utf-8") as f:
                f.write("reply")
        print("没能收录：%s" % e, file=sys.stderr)
        sys.exit(1)
    with open(a.result, "w", encoding="utf-8") as f:
        f.write(msg + "\n" if msg else "")
    if a.outcome:
        with open(a.outcome, "w", encoding="utf-8") as f:
            f.write(outcome)
    print(outcome + ("：" + msg if msg else ""))


if __name__ == "__main__":
    main()
