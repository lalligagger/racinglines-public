"""The X reply bot (scripts/xbot/xbot.py) with Zernio and Claude faked: what a pass answers, skips and remembers."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("xbot", Path(__file__).resolve().parents[1] / "scripts/xbot/xbot.py")
X = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(X)

POSTS = {"data": [{"id": "p1", "content": "Austin fair odds are up", "commentCount": 2}], "meta": {}}
COMMENTS = {"comments": [
    {"id": "c1", "message": "who wins Austin?", "from": {"username": "fan", "isOwner": False},
     "replies": [{"id": "c2", "message": "thanks!", "from": {"username": "racinglines_bet", "isOwner": True}},
                 {"id": "c3", "message": "and Vegas?", "from": {"username": "fan2", "isOwner": False}}]},
    {"id": "c4", "message": "buy my course", "from": {"username": "spam", "isOwner": False}},
]}


TAGS = {"tweets": [{"id": "900", "text": "@racinglines_bet who wins?", "author": {"username": "opticsinspace"}},
                   {"id": "899", "text": "@racinglines_bet hi", "author": {"username": "fan"}}]}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    calls = []

    def zernio(method, path, query=None, body=None, idempotency_key=None):
        calls.append((method, path, body, idempotency_key))
        if path == "/accounts":
            return {"accounts": [{"_id": "acc1", "platform": "twitter", "username": "racinglines_bet", "isActive": True}]}
        if path == "/twitter/search":
            calls[-1] = (method, path, query, None)
            after = int((query or {}).get("sinceId") or 0)
            return {"tweets": [t for t in TAGS["tweets"] if int(t["id"]) > after]}
        if path == "/inbox/comments":
            return POSTS
        if method == "GET":
            return COMMENTS
        return {"success": True, "data": {"commentId": "r"}}

    monkeypatch.setattr(X, "zernio", zernio)
    monkeypatch.setenv("XBOT_STATE", str(tmp_path))
    monkeypatch.setenv("XBOT_ACCOUNT_ID", "acc1")
    monkeypatch.delenv("XBOT_MODE", raising=False)
    monkeypatch.delenv("XBOT_MAX_REPLIES", raising=False)
    return calls


def write(text, post):
    return None if "course" in text else f"re: {text}"


def test_dry_pass_drafts_everything_new_posts_nothing_and_skips_our_own(fake, tmp_path):
    assert X.run_once(write=write) == 5
    assert not [c for c in fake if c[0] == "POST"]
    rows = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert [(r["comment"], r["action"]) for r in rows][:3] == [("c1", "drafted"), ("c4", "skipped"), ("c3", "drafted")]
    assert "c2" not in json.loads((tmp_path / "seen.json").read_text())


def test_live_pass_replies_once_per_comment_with_an_idempotency_key(fake, monkeypatch):
    monkeypatch.setenv("XBOT_MODE", "live")
    X.run_once(write=write)
    posts = [c for c in fake if c[0] == "POST"]
    assert [(p[2]["commentId"], p[3]) for p in posts[:2]] == [("c1", "xbot-c1"), ("c3", "xbot-c3")]
    assert posts[0][2] == {"accountId": "acc1", "message": "re: who wins Austin?", "commentId": "c1"}
    tagged = [p[2] for p in posts if p[1] == "/posts"]           # tags answered oldest first, as replies to the tweet
    assert [t["platforms"][0]["platformSpecificData"]["replyToTweetId"] for t in tagged] == ["899", "900"]
    assert tagged[0]["publishNow"] is True and tagged[0]["platforms"][0]["accountId"] == "acc1"
    fake.clear()
    assert X.run_once(write=write) == 0                       # all seen: the second pass answers nothing
    assert not [c for c in fake if c[0] == "POST"]
    assert [c[2]["sinceId"] for c in fake if c[1] == "/twitter/search"] == ["900"]


def test_the_cap_leaves_the_rest_for_the_next_pass(fake, monkeypatch):
    monkeypatch.setenv("XBOT_MAX_REPLIES", "1")
    assert X.run_once(write=write) == 1
    assert X.run_once(write=write) == 1
    seen = json.loads((Path(X.state_dir()) / "seen.json").read_text())
    assert sorted(seen) == ["c1", "c4"]                      # no tag handled yet, so the search does not move on
    for _ in range(3):
        X.run_once(write=write)
    seen = json.loads((Path(X.state_dir()) / "seen.json").read_text())
    assert {"899", "900"} <= set(seen) and seen["_search"] == {"newest_id": "900"}


def test_clean_drops_skip_long_and_denied_replies(monkeypatch):
    monkeypatch.setenv("XBOT_DENY", "Bookname, other")
    assert X.clean(' "Our model has Norris at 41%." ') == "Our model has Norris at 41%."
    assert X.clean("SKIP") is None and X.clean("skip") is None and X.clean("") is None
    assert X.clean("x" * 281) is None
    assert X.clean("Better odds at bookname tonight") is None


def test_the_toolset_is_read_only():
    assert not set(X.READ_TOOLS) & {"sql", "describe_schema", "data_changes", "run_job", "cancel_job",
                                    "fantasy_order", "pull_manifest", "pull_chunk", "replay_maker"}


def test_bad_mode_stops(fake, monkeypatch):
    monkeypatch.setenv("XBOT_MODE", "yolo")
    with pytest.raises(SystemExit):
        X.run_once(write=write)


def test_tweet_id_takes_an_id_or_a_status_url():
    assert X.tweet_id("1846000000000000001") == "1846000000000000001"
    assert X.tweet_id("https://x.com/opticsinspace/status/1846000000000000001?s=20") == "1846000000000000001"
    with pytest.raises(SystemExit):
        X.tweet_id("https://x.com/opticsinspace")


def test_a_hand_reply_marks_the_tweet_so_the_bot_skips_it(fake, tmp_path):
    (tmp_path / "intro.txt").write_text("hello X")
    X.main(["reply", "https://x.com/opticsinspace/status/900", str(tmp_path / "intro.txt")])
    assert json.loads((tmp_path / "seen.json").read_text())["900"]["action"] == "replied by hand"
    fake.clear()
    X.run_once(write=write)
    assert "900" not in [json.loads(l)["comment"] for l in (tmp_path / "log.jsonl").read_text().splitlines()[1:]]
    with pytest.raises(SystemExit):
        X.main(["reply", "900", str(tmp_path / "intro.txt")])


def test_handles_file_feeds_the_prompt(monkeypatch, tmp_path):
    f = tmp_path / "h.toml"
    f.write_text('[handles]\n"Ada Racer" = "@adaracer"\n')
    monkeypatch.setenv("XBOT_HANDLES", str(f))
    assert X.system_prompt().endswith("HANDLES:\nAda Racer: @adaracer")
    monkeypatch.setenv("XBOT_HANDLES", str(tmp_path / "missing.toml"))
    assert X.system_prompt().endswith("HANDLES:\n(none listed)")
    monkeypatch.delenv("XBOT_HANDLES")
    assert X.system_prompt().endswith("(none listed)")       # the shipped file has no entries


def test_draft_then_reply_posts_the_saved_draft(fake, monkeypatch, tmp_path, capsys):
    real = X.zernio

    def zernio(method, path, query=None, body=None, idempotency_key=None):
        if path == "/twitter/tweet":
            return {"tweet": {"id": "901", "text": "@racinglines_bet odds for Max?", "author": {"username": "opticsinspace"}}}
        return real(method, path, query, body, idempotency_key)

    monkeypatch.setattr(X, "zernio", zernio)
    monkeypatch.setattr(X, "draft", lambda text, ctx: "Max (@x) is 15% on our model.")
    X.main(["draft", "https://x.com/opticsinspace/status/901"])
    assert (tmp_path / "drafts" / "901.txt").read_text() == "Max (@x) is 15% on our model.\n"
    assert not [c for c in fake if c[0] == "POST"]
    X.main(["reply", "901"])
    post = [c for c in fake if c[0] == "POST"][0][2]
    assert post["content"] == "Max (@x) is 15% on our model."
    assert post["platforms"][0]["platformSpecificData"]["replyToTweetId"] == "901"


def test_review_approves_edits_and_skips(fake, monkeypatch, tmp_path):
    X.run_once(mode="queue", write=write)
    assert not [c for c in fake if c[0] == "POST"]               # queueing posts nothing
    pending = json.loads((tmp_path / "pending.json").read_text())
    assert sorted(pending) == ["899", "900", "c1", "c3", "c4"]
    assert (tmp_path / "drafts" / "c4.txt").read_text() == "SKIP\n"   # a model SKIP still waits for you
    # in the order queued: c1, c4, then c3 (nested), then tags 899, 900
    answers = iter(["a", "e", "a", "s", "l", "q"])

    def edit(f):
        Path(f).write_text("edited by hand\n")

    assert X.review(ask=lambda _: next(answers), edit=edit) == 2
    posts = [c[2] for c in fake if c[0] == "POST"]
    assert posts[0] == {"accountId": "acc1", "message": "re: who wins Austin?", "commentId": "c1"}
    assert posts[1]["message"] == "edited by hand" and posts[1]["commentId"] == "c4"
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert [seen[k]["action"] for k in ("c1", "c4", "c3")] == ["replied", "replied", "skipped by hand"]
    left = json.loads((tmp_path / "pending.json").read_text())
    assert sorted(left) == ["899", "900"]                        # 899 later, quit at 900


def test_review_refuses_to_post_a_skip_or_an_overlong_draft(fake, tmp_path):
    X.run_once(mode="queue", write=lambda t, c: None)
    answers = iter(["a", "q"])
    assert X.review(ask=lambda _: next(answers)) == 0
    assert not [c for c in fake if c[0] == "POST"]


def test_queue_requeues_what_a_dry_pass_only_drafted(fake, tmp_path):
    X.run_once(mode="dry", write=write)
    X.run_once(mode="queue", write=write)
    assert sorted(json.loads((tmp_path / "pending.json").read_text())) == ["899", "900", "c1", "c3"]


def test_a_tag_in_a_thread_reads_the_conversation_above_it(fake, monkeypatch, tmp_path):
    real = X.zernio
    parents = {"898": {"id": "898", "text": "Norris is the Austin favourite", "author": {"username": "yippeeosc"},
                       "inReplyToTweetId": "897"},
               "897": {"id": "897", "text": "who do you like this weekend?", "author": {"username": "fan"}}}
    looked = []

    def zernio(method, path, query=None, body=None, idempotency_key=None):
        if path == "/twitter/search":
            return {"tweets": [{"id": "900", "text": "@racinglines_bet @yippeeosc ok, what is ours?",
                                "author": {"username": "whycanti_poker"}, "inReplyToTweetId": "898"}]}
        if path == "/twitter/tweet":
            looked.append(query["tweetId"])
            return {"tweet": parents[query["tweetId"]]}
        if path == "/inbox/comments":
            return {"data": []}
        return real(method, path, query, body, idempotency_key)

    monkeypatch.setattr(X, "zernio", zernio)
    got = []
    X.run_once(mode="queue", write=lambda text, ctx: got.append(ctx) or "ours")
    assert got == ["@fan: who do you like this weekend?\n@yippeeosc: Norris is the Austin favourite"]
    monkeypatch.setenv("XBOT_THREAD_HOPS", "1")
    assert X.thread_above("acc1", {"id": "900", "inReplyToTweetId": "898"}) == ["@yippeeosc: Norris is the Austin favourite"]
    assert X.thread_above("acc1", {"id": "901"}) == []          # not a reply: nothing to read, no lookup
    assert looked == ["898", "897", "898"]


def test_a_nested_comment_sees_the_comments_above_it(fake):
    c3 = [c for c in X.comments("p1", "acc1") if c["id"] == "c3"][0]
    assert c3["_above"] == ["@fan: who wins Austin?"]
    item = dict(kind="comment", post_text="Austin fair odds are up", above=c3["_above"])
    assert X.context_for("acc1", item) == "Our post: Austin fair odds are up\n@fan: who wins Austin?"


def test_review_redraft_reads_the_thread_again(fake, monkeypatch, tmp_path):
    X.run_once(mode="queue", write=write)
    monkeypatch.setattr(X, "context_for", lambda acct, item: "@yippeeosc: Norris 41%")
    answers = iter(["r", "q"])
    X.review(ask=lambda _: next(answers), write=lambda text, ctx: f"redrafted with {ctx}")
    assert (tmp_path / "drafts" / "c1.txt").read_text() == "redrafted with @yippeeosc: Norris 41%\n"
    assert not [c for c in fake if c[0] == "POST"]


def test_the_thread_comes_from_one_conversation_search_and_a_lookup_only_for_the_root(fake, monkeypatch):
    calls = []

    def zernio(method, path, query=None, body=None, idempotency_key=None):
        calls.append((path, query.get("query") or query.get("tweetId")))
        if path == "/twitter/search":
            return {"tweets": [{"id": "898", "text": "Norris 41%?", "author": {"username": "yippeeosc"},
                                "inReplyToTweetId": "897"}]}
        if query["tweetId"] == "897":
            return {"tweet": {"id": "897", "text": "who wins?", "author": {"username": "fan"}}}
        raise RuntimeError("Zernio GET /twitter/tweet: HTTP 404")

    monkeypatch.setattr(X, "zernio", zernio)
    t = {"id": "900", "inReplyToTweetId": "898", "conversationId": "897"}
    assert X.thread_above("acc1", t) == ["@fan: who wins?", "@yippeeosc: Norris 41%?"]
    assert calls == [("/twitter/search", "conversation_id:897"), ("/twitter/tweet", "897")]
    assert X.thread_above("acc1", {"id": "901", "inReplyToTweetId": "deleted"}) == []   # a 404 is not a crash


def test_redraft_of_a_deleted_tweet_keeps_the_draft_and_review_goes_on(fake, monkeypatch, tmp_path):
    X.run_once(mode="queue", write=write)
    monkeypatch.setattr(X, "tags", lambda acct, handle, since_id=None: [])
    monkeypatch.setattr(X, "lookup", lambda acct, tweet: (_ for _ in ()).throw(RuntimeError("HTTP 404")))
    pending = json.loads((tmp_path / "pending.json").read_text())
    for v in pending.values():
        v.pop("tweet", None)                                   # queued by the older code
    (tmp_path / "pending.json").write_text(json.dumps(pending))
    answers = iter(["s", "s", "s", "r", "q"])                     # c1, c4, c3 skipped; redraft tag 899
    X.review(ask=lambda _: next(answers), write=lambda text, ctx: "never")
    assert (tmp_path / "drafts" / "899.txt").read_text() == "re: @racinglines_bet hi\n"


class B:
    def __init__(self, type, **kw):
        self.type = type
        self.__dict__.update(kw)


def test_a_web_answer_is_marked_and_keeps_its_sources():
    web = [B("server_tool_use", name="web_search"),
           B("web_search_tool_result", content=[B("web_search_result", url="https://en.wikipedia.org/wiki/F1")])]
    d = X.labelled("Hamilton has won on five continents.", web)
    assert d == "Not our model: Hamilton has won on five continents." and d.lane == "web"
    assert d.sources == ("https://en.wikipedia.org/wiki/F1",)
    assert X.labelled("Not our model: already marked.", web) == "Not our model: already marked."
    assert X.labelled("x" * 270, web) is None                  # the mark would push it over 280
    m = X.labelled("Max (@x) is 15% on our model.", [B("mcp_tool_use", name="get_predictions")])
    assert m.lane == "model" and m.sources == ()
    assert X.labelled("both", web + [B("mcp_tool_use", name="overview")]).lane == "mixed"
    assert X.labelled(None, web) is None


def test_web_search_can_be_turned_off(monkeypatch):
    assert "Web search is off" not in X.system_prompt()
    monkeypatch.setenv("XBOT_WEB", "0")
    assert "Web search is off" in X.system_prompt()


def test_review_shows_the_lane_and_sources(fake, tmp_path, capsys):
    def write(text, ctx):
        d = X.Draft("Not our model: " + text)
        d.lane, d.sources = "web", ("https://example.org/f1",)
        return d
    X.run_once(mode="queue", write=write)
    assert json.loads((tmp_path / "pending.json").read_text())["c1"]["lane"] == "web"
    X.review(ask=lambda _: "q")
    out = capsys.readouterr().out
    assert "web search, check the sources" in out and "source: https://example.org/f1" in out
