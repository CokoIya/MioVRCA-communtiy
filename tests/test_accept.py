# SPDX-License-Identifier: GPL-3.0-only OR PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 天川澪 (Coko_Iya). Part of MioVRCA: https://github.com/CokoIya/MioVRC_AssetManager (terms in LICENSE.md)
"""收录脚本（accept_issue.py、rebuild.py、sweep.py）在一个临时的仓库副本上运行：

    python3 -m unittest discover community/tests

没有 Pillow 时，涉及图片的部分跳过。
"""
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(TEMPLATE, "scripts"))
import accept_issue  # noqa: E402
import miovrca_code  # noqa: E402
import rebuild  # noqa: E402
import sweep  # noqa: E402

try:
    from PIL import Image
except ImportError:
    Image = None


def jpeg_b64(w=300, h=200):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 100, 50)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def code(kind, obj):
    return miovrca_code.encode(json.dumps(obj, ensure_ascii=False).encode("utf-8"), kind)


def body_of(kind, obj, **fields):
    """议题表单的正文，像 GitHub 显示的那样"""
    parts = ["### %s\n\n%s" % (k, v) for k, v in fields.items()]
    if obj is not None:
        label = {"profile": "名片分享码", "work": "作品分享码", "recipe": "分享码"}[kind]
        parts.append("### %s\n\n```text\n%s\n```" % (label, code(kind, obj)))
    parts.append("### 确认\n\n- [X] 同意")
    return "\n\n".join(parts)


def issue(number, user, body, labels, title="", state="open"):
    return {"number": number, "user": {"login": user}, "body": body, "labels": [{"name": l} for l in labels], "title": title, "state": state,
            "created_at": "2026-10-10T00:00:00Z"}


class Repo(unittest.TestCase):
    """一个临时的社区仓库（模板的副本）"""

    def setUp(self):
        env = mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "", "GITHUB_TOKEN": "", "GITHUB_API_URL": "http://127.0.0.1:1"})
        env.start()
        self.addCleanup(env.stop)
        self.dir = tempfile.mkdtemp()
        self.root = os.path.join(self.dir, "community")
        shutil.copytree(TEMPLATE, self.root, ignore=shutil.ignore_patterns("__pycache__", "tests", ".github"))
        for m in (accept_issue, rebuild, sweep):
            p = mock.patch.object(m, "ROOT", self.root)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(accept_issue, "BANNED", os.path.join(self.root, "scripts", "banned.txt"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.dir)

    def read(self, *parts, empty=None):
        return rebuild.read_json(os.path.join(self.root, *parts), empty)

    def exists(self, *parts):
        return os.path.exists(os.path.join(self.root, *parts))


class Profiles(Repo):
    def test_showcase_publish_replace_and_refuse(self):
        items = [{"booth_id": "123", "name": " Dress ", "shop": " Shop "}]
        accept_issue.accept_profile(code("profile", {"nickname": "Mio", "showcase": items}), 10, "mio")
        self.assertEqual(self.read("profiles", "mio.json")["showcase"],
                         [{"booth_id": "123", "name": "Dress", "shop": "Shop"}])
        before = self.read("profiles", "mio.json")
        for bad in (items * 2, [{"booth_id": "../1", "name": "x"}], items * 61):
            with self.subTest(showcase=bad[:2]):
                with self.assertRaises(accept_issue.Refused):
                    accept_issue.accept_profile(code("profile", {"nickname": "Mio", "showcase": bad}), 11, "mio")
                self.assertEqual(self.read("profiles", "mio.json"), before)
        accept_issue.accept_profile(code("profile", {"nickname": "Mio"}), 12, "mio")
        self.assertNotIn("showcase", self.read("profiles", "mio.json"))

    def test_work_references_survive_rebuild_and_update(self):
        accept_issue.accept_work(code("work", {"title": "Original"}), 10, "mio", "2026-10-10T00:00:00Z")
        accept_issue.accept_work(code("work", {"title": "Derived", "based_on": "w10"}), 11, "sora", "2026-10-11T00:00:00Z")
        self.assertEqual(self.read("works", "w11.json")["based_on"], "w10")
        self.assertEqual(self.read("works.json")["works"][0]["based_on"], "w10")
        accept_issue.accept_work(code("work", {"title": "Updated", "replace": "w11", "based_on": "w999"}), 12, "sora", "2026-10-12T00:00:00Z")
        self.assertEqual(self.read("works", "w11.json")["based_on"], "w999")
        before = self.read("works", "w11.json")
        with self.assertRaises(accept_issue.Refused):
            accept_issue.accept_work(code("work", {"title": "Self", "replace": "w11", "based_on": "w11"}), 13, "sora", "2026-10-12T00:00:00Z")
        self.assertEqual(self.read("works", "w11.json"), before)
        with self.assertRaises(accept_issue.Refused):
            accept_issue.accept_work(code("work", {"title": "Self", "based_on": "w14"}), 14, "sora", "2026-10-12T00:00:00Z")
        self.assertFalse(self.exists("works", "w14.json"))
        accept_issue.accept_work(code("work", {"title": "Cleared", "replace": "w11"}), 15, "sora", "2026-10-12T00:00:00Z")
        self.assertNotIn("based_on", self.read("works", "w11.json"))
        self.assertNotIn("based_on", self.read("works.json")["works"][0])

    def test_card(self):
        card = {"nickname": " 澪 ", "bio": "做模型", "langs": ["zh", "ja"], "links": [{"kind": "booth_shop", "url": "https://MIO.booth.pm/"}],
                "birthday": {"month": 2, "day": 29}, "following": ["luna", "MioIya"]}
        if Image:
            card["avatar"] = jpeg_b64()
        out, msg = accept_issue.handle(issue(5, "MioIya", body_of("profile", dict(card, login="someone-else")), ["名片"]), "opened")
        self.assertEqual(out, "close", msg)
        c = self.read("profiles", "mioiya.json")
        self.assertEqual(c["login"], "mioiya")  # （议题的作者，不是分享码里写的）
        self.assertEqual(c["nickname"], "澪")
        self.assertEqual(c["links"][0]["url"], "https://mio.booth.pm/")
        self.assertEqual(c["following"], ["luna"])  # （关注自己的不算）
        self.assertEqual(c["issue"], 5)
        rows = self.read("creators.json")["creators"]
        self.assertEqual([r["login"] for r in rows], ["mioiya"])
        self.assertEqual(rows[0]["birthday"], {"month": 2, "day": 29})
        if Image:
            self.assertEqual(c["avatar"], "avatars/mioiya.jpg")
            with Image.open(os.path.join(self.root, "avatars", "mioiya.jpg")) as im:
                self.assertEqual((im.format, im.size), ("JPEG", (256, 256)))
        # 换回 GitHub 头像：图片删掉
        card.pop("avatar", None)
        out, _ = accept_issue.handle(issue(9, "mioiya", body_of("profile", card), ["名片"]), "edited")
        self.assertEqual(out, "close")
        self.assertFalse(self.exists("avatars", "mioiya.jpg"))
        self.assertNotIn("avatar", self.read("profiles", "mioiya.json"))

    def test_waiting_and_refused(self):
        card = {"nickname": "luna"}
        self.assertEqual(accept_issue.handle(issue(1, "luna", body_of("profile", card), ["名片"]), "opened", auto_profiles=False)[0], "reply")
        self.assertEqual(accept_issue.handle(issue(1, "luna", body_of("profile", card), ["名片"]), "edited", auto_profiles=False)[0], "none")
        self.assertFalse(self.exists("profiles", "luna.json"))
        self.assertEqual(accept_issue.handle(issue(1, "luna", body_of("profile", card), ["名片"]), "labeled", "收录", auto_profiles=False)[0], "close")
        for bad, says in (({"nickname": "a", "vrchat": "https://vrchat.com/home/world/x"}, "VRChat"), ({"nickname": ""}, "昵称不能为空"),
                          ({"nickname": "a", "links": [{"kind": "netdisk", "url": "https://pan.baidu.com/s/1"}]}, "链接格式不正确")):
            with self.assertRaises(accept_issue.Refused) as e:
                accept_issue.handle(issue(2, "sora", body_of("profile", bad), ["名片"]), "opened")
            self.assertIn(says, str(e.exception))
        cut = code("profile", {"nickname": "luna", "bio": "一段介绍" * 10})[:-5]
        with self.assertRaises(accept_issue.Refused) as e:  # 分享码被截断
            accept_issue.handle(issue(3, "sora", "### 名片分享码\n\n" + cut, ["名片"]), "opened")
        self.assertIn("不完整", str(e.exception))
        with open(os.path.join(self.root, "scripts", "banned.txt"), "a", encoding="utf-8") as f:
            f.write("违禁词\n")
        with self.assertRaises(accept_issue.Refused) as e:
            accept_issue.handle(issue(4, "sora", body_of("profile", {"nickname": "这是违禁词"}), ["名片"]), "opened")
        self.assertIn("不允许", str(e.exception))
        # 已关闭的议题被编辑：不处理
        self.assertEqual(accept_issue.handle(issue(5, "sora", body_of("profile", card), ["名片"], state="closed"), "edited")[0], "none")


class Works(Repo):
    def work(self, **kw):
        w = {"title": "新衣服", "video": "https://www.bilibili.com/video/BV1xx411c7mD", "base": "Manuka",
             "assets": [{"name": "Dress", "url": "https://booth.pm/ja/items/1", "shop": "Mio"}], "recipe": "MIOVRCA-RECIPE-1:abc"}
        if Image:
            w["cover"] = jpeg_b64(1280, 720)
        w.update(kw)
        return w

    def test_review(self):
        b = body_of("work", self.work(), **{"作品名称": "新衣服"})
        self.assertEqual(accept_issue.handle(issue(12, "Mio", b, ["作品"]), "opened")[0], "reply")
        self.assertFalse(self.exists("works", "w12.json"))
        out, msg = accept_issue.handle(issue(12, "Mio", b, ["作品", "收录"]), "labeled", "收录")
        self.assertEqual(out, "close", msg)
        w = self.read("works", "w12.json")
        self.assertEqual((w["id"], w["author"], w["issue"], w["created"]), ("w12", "mio", 12, "2026-10-10T00:00:00Z"))
        self.assertNotIn("rights_ok", w)
        rows = self.read("works.json")["works"]
        self.assertEqual(rows[0]["video_kind"], "bilibili")
        self.assertTrue(rows[0]["has_recipe"])
        if Image:
            with Image.open(os.path.join(self.root, "covers", "w12.jpg")) as im:
                self.assertEqual(im.size, (640, 360))
        # 作者本人更新：同一个编号，点赞仍在原来的议题上
        out, _ = accept_issue.handle(issue(20, "mio", body_of("work", self.work(title="新衣服 2", replace="w12")), ["作品"]), "labeled", "收录")
        w = self.read("works", "w12.json")
        self.assertEqual((out, w["title"], w["issue"]), ("close", "新衣服 2", 12))
        self.assertIn("updated", w)
        with self.assertRaises(accept_issue.Refused):  # 别人的作品
            accept_issue.handle(issue(21, "luna", body_of("work", self.work(replace="w12")), ["作品"]), "labeled", "收录")
        self.assertEqual(self.read("creators.json")["creators"], [])  # （没有名片的作者不在创作者列表中）

    def test_auto(self):
        out, _ = accept_issue.handle(issue(30, "mio", body_of("work", self.work()), ["作品"]), "opened", auto_works=True)
        self.assertEqual(out, "close")
        netdisk = self.work(links=[{"kind": "netdisk", "url": "https://pan.baidu.com/s/1x"}], rights_ok=True)
        self.assertEqual(accept_issue.handle(issue(31, "mio", body_of("work", netdisk), ["作品"]), "opened", auto_works=True)[0], "reply")
        with self.assertRaises(accept_issue.Refused) as e:  # 网盘链接没有勾选权利
            accept_issue.handle(issue(32, "mio", body_of("work", dict(netdisk, rights_ok=False)), ["作品"]), "opened")
        self.assertIn("有权分享", str(e.exception))

    def test_remove(self):
        accept_issue.handle(issue(40, "mio", body_of("work", self.work()), ["作品"]), "labeled", "收录")
        rm = body_of(None, None, **{"作品编号": "W40", "说明（选填）": "_No response_"})
        with self.assertRaises(accept_issue.Refused):
            accept_issue.handle(issue(41, "luna", rm, ["作品"], title="[删除作品] w40"), "opened")
        out, _ = accept_issue.handle(issue(42, "mio", rm, ["作品"], title="[删除作品] w40"), "opened")
        self.assertEqual(out, "close")
        self.assertFalse(self.exists("works", "w40.json") or self.exists("covers", "w40.jpg"))
        self.assertEqual(self.read("works.json")["works"], [])
        with self.assertRaises(accept_issue.Refused):
            accept_issue.handle(issue(43, "mio", rm, ["作品"], title="[删除作品] w40"), "opened")


class Recipes(Repo):
    def test_links_and_login(self):
        r = {"format": "miovrca-recipe", "schema": 1, "name": "日常", "author": "Mio", "links": [{"kind": "booth_shop", "url": "https://mio.booth.pm/"}],
             "base": {"name": "Manuka"}, "assets": [{"prefab": "Assets/a.prefab", "name": "Dress", "kind": "衣服", "object": "Dress", "boothId": "1"}], "menus": []}
        b = body_of("recipe", r, **{"方案名称": "日常", "署名（选填）": "澪"})
        self.assertEqual(accept_issue.handle(issue(7, "MioIya", b, ["方案"]), "opened")[0], "none")  # （等「收录」）
        out, _ = accept_issue.handle(issue(7, "MioIya", b, ["方案"]), "labeled", "收录")
        self.assertEqual(out, "close")
        e = self.read("index.json")["recipes"][0]
        self.assertEqual((e["id"], e["author"], e["login"]), ("issue-7", "澪", "mioiya"))
        self.assertEqual(e["links"], [{"kind": "booth_shop", "url": "https://mio.booth.pm/"}])
        f = self.read("recipes", "issue-7.json")
        self.assertNotIn("author", f)  # （1.8.0 的程序读得了的文件）
        self.assertNotIn("links", f)
        bad = dict(r, links=[{"kind": "qq_group", "url": "https://qm.qq.com/q/1"}])
        with self.assertRaises(accept_issue.Refused):
            accept_issue.handle(issue(8, "mio", body_of("recipe", bad), ["方案"]), "labeled", "收录")


class Rebuild(Repo):
    def test_counts(self):
        os.makedirs(os.path.join(self.root, "profiles"), exist_ok=True)
        for login, fl in (("mio", ["luna"]), ("luna", ["mio", "sora", "mio"]), ("sora", ["mio"])):
            rebuild.write_json(os.path.join(self.root, "profiles", login + ".json"), {"login": login, "nickname": login.upper(), "following": fl, "updated": "2026-10-01T00:00:00Z"})
        rebuild.write_json(os.path.join(self.root, "profiles", "x.json"), {"login": "y", "nickname": "wrong file"})
        rebuild.write_json(os.path.join(self.root, "works", "w3.json"), {"id": "w3", "author": "mio", "title": "a", "issue": 3, "created": "2026-10-03T00:00:00Z"})
        rebuild.write_json(os.path.join(self.root, "works", "w4.json"), {"id": "w5", "author": "mio", "title": "wrong file"})
        rebuild.write_json(os.path.join(self.root, "likes.json"), {"w3": 7})
        idx = rebuild.load_index()
        idx["recipes"] = [{"id": "r1", "name": "x", "file": "recipes/r1.json", "login": "luna"}]
        rebuild.write_json(os.path.join(self.root, "index.json"), idx)
        self.assertEqual(rebuild.rebuild_creators(), 3)
        rows = {r["login"]: r for r in self.read("creators.json")["creators"]}
        self.assertEqual((rows["mio"]["followers"], rows["mio"]["works"]), (2, 1))
        self.assertEqual((rows["luna"]["followers"], rows["luna"].get("recipes")), (1, 1))
        self.assertEqual(rows["sora"]["followers"], 1)
        self.assertEqual(rebuild.rebuild_works(), 1)
        self.assertEqual(self.read("works.json")["works"][0]["likes"], 7)


class Handler(BaseHTTPRequestHandler):
    """GitHub API 的替身：议题列表"""
    issues = []

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        if self.headers.get("Authorization") != "Bearer t0ken":
            self.send_response(401)
            self.end_headers()
            return
        items = [it for it in self.issues if q["labels"][0] in [l["name"] for l in it["labels"]] and (q["state"][0] == "all" or it["state"] == q["state"][0])]
        page, per = int(q["page"][0]), int(q["per_page"][0])
        b = json.dumps(items[(page - 1) * per:page * per]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


class Sweep(Repo):
    def test_likes_and_missed(self):
        rebuild.write_json(os.path.join(self.root, "works", "w3.json"), {"id": "w3", "author": "mio", "title": "a", "issue": 3, "created": "2026-10-03T00:00:00Z"})
        card = body_of("profile", {"nickname": "补上"})
        # （作品的议题超过 100 个：分页读取）
        Handler.issues = [dict(issue(3, "mio", "x", ["作品"], state="closed"), reactions={"+1": 4})]
        Handler.issues += [dict(issue(150 + i, "x", "y", ["作品"], state="closed"), reactions={"+1": 1}) for i in range(120)]
        Handler.issues += [dict(issue(60, "Late", card, ["名片"]), comments=0), dict(issue(61, "talked", card, ["名片"]), comments=2),
                           dict(issue(62, "fresh", card, ["名片"]), comments=0, created_at="2999-01-01T00:00:00Z"),
                           dict(issue(63, "bad", body_of("profile", {"nickname": ""}), ["名片"]), comments=0)]
        srv = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        env = {"GITHUB_API_URL": "http://127.0.0.1:%d" % srv.server_port, "GITHUB_TOKEN": "t0ken", "GITHUB_REPOSITORY": "o/r"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(sweep.count_likes(), 4)
            Handler.issues[0]["reactions"]["+1"] = 9
            rebuild.rebuild()
            self.assertEqual(self.read("works.json")["works"][0]["likes"], 9)
            Handler.issues[0]["reactions"]["+1"] = 4
            rebuild.rebuild_works()
            replies = sweep.missed(True, False)
        self.assertEqual(self.read("likes.json"), {"w3": 4})
        self.assertEqual(self.read("works.json")["works"][0]["likes"], 4)
        self.assertEqual([(r["number"], r["close"]) for r in replies], [(60, True), (63, False)])
        self.assertTrue(self.exists("profiles", "late.json"))
        self.assertFalse(self.exists("profiles", "talked.json") or self.exists("profiles", "fresh.json"))


class Events(Repo):
    """从命令行运行，读 GitHub 的事件文件：结果、要做的事、退出码"""

    def run_main(self, ev, env=None):
        path = os.path.join(self.dir, "event.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ev, f, ensure_ascii=False)
        res, out = os.path.join(self.dir, "result.md"), os.path.join(self.dir, "outcome")
        argv = ["accept_issue.py", "--event", path, "--result", res, "--outcome", out]
        code = 0
        with mock.patch.object(sys, "argv", argv), mock.patch.dict(os.environ, env or {}), mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            try:
                accept_issue.main()
            except SystemExit as e:
                code = e.code
        with open(res, encoding="utf-8") as f, open(out, encoding="utf-8") as g:
            return code, f.read(), g.read()

    def test_event_file(self):
        ev = {"action": "opened", "issue": issue(70, "mio", body_of("profile", {"nickname": "澪"}), ["名片"])}
        self.assertEqual(self.run_main(ev)[0::2], (0, "close"))
        self.assertEqual(self.run_main(ev, {"AUTO_PROFILES": "false"})[0::2], (0, "reply"))
        ev["issue"]["body"] = body_of("profile", {"nickname": "澪", "langs": "zh"})
        code, result, outcome = self.run_main(ev)
        self.assertEqual((code, outcome), (1, "reply"))
        self.assertIn("没能收录", result)
        ev = {"action": "labeled", "label": {"name": "收录"}, "issue": issue(71, "mio", "没有分享码", ["收录"])}
        self.assertEqual(self.run_main(ev)[0], 1)

    def test_issue_text_is_data(self):
        nickname = "$(echo owned) `whoami`"
        ev = {"action": "opened", "issue": issue(72, "fixture", body_of("profile", {"nickname": nickname}), ["名片"])}
        self.assertEqual(self.run_main(ev)[0::2], (0, "close"))
        self.assertEqual(self.read("profiles", "fixture.json")["nickname"], nickname)

    def test_workflow_contract(self):
        with open(os.path.join(TEMPLATE, ".github", "workflows", "accept.yml"), encoding="utf-8") as f:
            workflow = f.read()
        self.assertNotRegex(workflow, r"\$\{\{[^}]*github\.event\.issue\.(body|title|user)")
        self.assertIn('--event "$GITHUB_EVENT_PATH"', workflow)
        self.assertEqual(workflow.count("    concurrency:\n      group: community"), 2)
        self.assertEqual(workflow.count("git pull --rebase origin main && git push"), 2)
        self.assertIn('cron: "23 */6 * * *"', workflow)


if __name__ == "__main__":
    unittest.main()
