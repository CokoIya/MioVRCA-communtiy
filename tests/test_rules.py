# SPDX-License-Identifier: GPL-3.0-only OR PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 天川澪 (Coko_Iya). Part of MioVRCA: https://github.com/CokoIya/MioVRC_AssetManager (terms in LICENSE.md)
"""rules.py 与 MioVRCA 程序的规则（internal/socialapi/rules.go）是否一致：逐条核对程序的测试写出的用例。

    python3 -m unittest discover community/tests

用例文件在 MioVRCA 的源码中（internal/socialapi/testdata/cases.json）；只有社区仓库、没有源码时，这部分跳过。
"""
import base64
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import miovrca_code  # noqa: E402
import rules  # noqa: E402

CASES = os.environ.get("MIOVRCA_RULE_CASES") or os.path.join(HERE, "..", "..", "internal", "socialapi", "testdata", "cases.json")


def answer(f, *args):
    """和 Go 测试的 answer() 一样：{"ok": true, "out": …} 或 {"ok": false, "code": …, "msg": …}"""
    try:
        return {"ok": True, "out": f(*args)}
    except rules.RuleError as e:
        return {"ok": False, "code": e.code, "msg": str(e)}


def run(fn, args):
    if fn == "norm_login":
        return answer(rules.norm_login, *args)
    if fn == "clean_text":
        return answer(rules.clean_text, *args)
    if fn == "link_kind_of":
        return rules.link_kind_of(*args)
    if fn == "booth_item_id":
        return rules.booth_item_id(*args)
    if fn == "video_kind":
        return rules.video_kind(*args)
    if fn == "check_vrchat":
        return answer(rules.check_vrchat, *args)
    if fn == "check_link":
        return answer(rules.check_link, *args)
    if fn == "check_links":
        return answer(rules.check_links, *args)
    if fn == "date_ok":
        return rules.date_ok(*args)
    if fn == "work_id_ok":
        return rules.work_id_ok(*args)
    if fn == "check_card":
        return answer(rules.check_card, *args)
    if fn == "check_work":
        return answer(rules.check_work, *args)
    if fn == "code":
        return miovrca_code.find(args[1], args[0]).decode("utf-8")
    if fn == "dicts":
        return {"profile": miovrca_code.PROFILE_DICT.decode("utf-8"), "work": miovrca_code.WORK_DICT.decode("utf-8")}
    raise AssertionError("unknown case " + fn)


@unittest.skipUnless(os.path.isfile(CASES), "没有 MioVRCA 源码中的用例文件")
class Parity(unittest.TestCase):
    def test_cases(self):
        with open(CASES, encoding="utf-8") as f:
            cases = json.load(f)
        self.assertGreater(len(cases), 300)
        bad = []
        for c in cases:
            got = run(c["fn"], c["args"])
            if got != c["want"]:
                bad.append("%s%s\n   Go:     %s\n   Python: %s" % (c["fn"], json.dumps(c["args"], ensure_ascii=False)[:160],
                                                                   json.dumps(c["want"], ensure_ascii=False)[:300], json.dumps(got, ensure_ascii=False)[:300]))
        if bad:
            self.fail("%d 条与程序不一致：\n%s" % (len(bad), "\n".join(bad[:40])))


def jpeg(n):
    b = bytearray(n)
    b[:4] = b"\xff\xd8\xff\xe0"
    return base64.b64encode(bytes(b)).decode()


class Limits(unittest.TestCase):
    """用例文件里没有的：图片的最大尺寸（为了文件的大小）。"""

    def test_v3_refusal_codes(self):
        for items, code in [
            ([{"booth_id": "1", "name": "a"}] * 61, "too_long"),
            ([{"booth_id": "1", "name": "a"}] * 2, "bad_request"),
            ([{"booth_id": "１２", "name": "a"}], "bad_request"),
            ([{"booth_id": "1", "name": ""}], "bad_text"),
            ([{"booth_id": "1", "name": "a" * 81}], "too_long"),
            ([{"booth_id": "1", "name": "a", "shop": "b" * 41}], "too_long"),
        ]:
            self.assertEqual(answer(rules.check_card, {"nickname": "Mio", "showcase": items})["code"], code)
        for based in ("w12", "W12", "../w12", "w1234567890"):
            self.assertEqual(answer(rules.check_work, {"title": "Work", "replace": "w12", "based_on": based})["code"], "bad_request")

    def test_legacy_codes(self):
        path = os.path.join(os.path.dirname(CASES), "legacy_codes.json")
        if not os.path.isfile(path):
            self.skipTest("legacy fixtures require the app source tree")
        with open(path, encoding="utf-8") as f:
            for c in json.load(f):
                self.assertEqual(run(c["fn"], c["args"]), c["want"])

    def test_pictures(self):
        self.assertTrue(rules.jpeg_b64(jpeg(49152), rules.MAX_AVATAR_B64))  # 65 536 个字符
        self.assertFalse(rules.jpeg_b64(jpeg(49153), rules.MAX_AVATAR_B64))
        with self.assertRaises(rules.RuleError) as e:
            rules.check_card({"nickname": "a", "avatar": jpeg(49153)})
        self.assertEqual(e.exception.code, rules.ERR_BAD_IMAGE)
        with self.assertRaises(rules.RuleError) as e:
            rules.check_work({"title": "a", "cover": jpeg(98305)})
        self.assertEqual(e.exception.code, rules.ERR_BAD_IMAGE)
        self.assertEqual(rules.check_work({"title": "a", "cover": jpeg(98304)})["title"], "a")

    def test_truncated_stream(self):
        code = miovrca_code.encode(b'{"nickname":"fixture"}', "profile")
        prefix, letters = code.split(":", 1)
        raw = base64.urlsafe_b64decode(letters + "=" * (-len(letters) % 4))
        cut = prefix + ":" + base64.urlsafe_b64encode(raw[:-1]).decode().rstrip("=")
        with self.assertRaises(miovrca_code.CodeError):
            miovrca_code.find(cut, "profile")

    def test_wrong_types(self):
        for r in ({"nickname": 1}, {"nickname": "a", "langs": "zh"}, {"nickname": "a", "links": [1]}, {"nickname": "a", "birthday": "2-29"}, []):
            with self.assertRaises(rules.RuleError):
                rules.check_card(r)
        for r in ({"title": "a", "rights_ok": "yes"}, {"title": "a", "assets": [1]}, {"title": ["a"]}):
            with self.assertRaises(rules.RuleError):
                rules.check_work(r)

    def test_banned(self):
        rules.check_banned(["正常的介绍"], ["广告词"])
        with self.assertRaises(rules.RuleError) as e:
            rules.check_banned(["这里有 广告词"], ["广告词"])
        self.assertEqual(e.exception.code, rules.ERR_BANNED_WORDS)


if __name__ == "__main__":
    unittest.main()
