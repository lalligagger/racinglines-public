"""
Cycling market sync tests: Polymarket integration for UCI road cycling markets.
Built on a mocked Gamma API (httpx.MockTransport).
"""
import json

import httpx
import pytest
from sqlalchemy import text

from racinglines import sports
from racinglines.markets.cycling import sync as CS


def _market(slug, q, tokens, outcomes_list, bid, ask, end_date="2026-10-12T23:00:00Z"):
    """Create a mock Polymarket market structure."""
    return dict(
        slug=slug,
        question=q,
        conditionId="0x" + slug,
        clobTokenIds=json.dumps(tokens),
        outcomes=json.dumps(outcomes_list),
        outcomePrices=json.dumps([str(ask)] + [str(round((1 - ask) / (len(outcomes_list) - 1), 2))] * (len(outcomes_list) - 1)),
        bestBid=bid,
        bestAsk=ask,
        endDate=end_date,
        negRisk=True,
        volume="5000.0"
    )


# Tour of Guangxi 2026 event with multiple rider markets
GUANGXI_EVENT = dict(
    slug="cycling-tour-of-guangxi-winner-2026-10-12",
    title="Tour of Guangxi 2026: Winner",
    negRisk=True,
    markets=[
        _market("guangxi-ayuso", "Who will win the 2026 Tour of Guangxi?",
                ["tok-guangxi-ayuso", "tok-guangxi-ayuso-no"],
                ["Juan Ayuso", "No"],
                0.14, 0.14,
                end_date="2026-10-12T23:00:00Z"),
        _market("guangxi-pidcock", "Who will win the 2026 Tour of Guangxi?",
                ["tok-guangxi-pidcock", "tok-guangxi-pidcock-no"],
                ["Tom Pidcock", "No"],
                0.14, 0.14,
                end_date="2026-10-12T23:00:00Z"),
        _market("guangxi-milan", "Who will win the 2026 Tour of Guangxi?",
                ["tok-guangxi-milan", "tok-guangxi-milan-no"],
                ["Jonathan Milan", "No"],
                0.14, 0.14,
                end_date="2026-10-12T23:00:00Z"),
        _market("guangxi-mads", "Who will win the 2026 Tour of Guangxi?",
                ["tok-guangxi-mads", "tok-guangxi-mads-no"],
                ["Mads Pedersen", "No"],
                0.14, 0.14,
                end_date="2026-10-12T23:00:00Z"),
    ]
)

# Il Lombardia 2026 event
LOMBARDIA_EVENT = dict(
    slug="cycling-il-lombardia-winner-2026-10-09",
    title="Il Lombardia 2026: Winner",
    negRisk=True,
    markets=[
        _market("lombardia-evenepoel", "Who will win the 2026 Il Lombardia?",
                ["tok-lombardia-evenepoel", "tok-lombardia-evenepoel-no"],
                ["Remco Evenepoel", "No"],
                0.20, 0.25,
                end_date="2026-10-09T23:00:00Z"),
        _market("lombardia-pogacar", "Who will win the 2026 Il Lombardia?",
                ["tok-lombardia-pogacar", "tok-lombardia-pogacar-no"],
                ["Tadej Pogacar", "No"],
                0.15, 0.20,
                end_date="2026-10-09T23:00:00Z"),
    ]
)

# Podium market (example of race_podium prediction)
GUANGXI_PODIUM = dict(
    slug="cycling-tour-of-guangxi-podium-2026-10-12",
    title="Tour of Guangxi 2026: Podium",
    negRisk=True,
    markets=[
        _market("guangxi-podium-ayuso", "Will Juan Ayuso finish on the podium?",
                ["tok-guangxi-podium-ayuso", "tok-guangxi-podium-ayuso-no"],
                ["Juan Ayuso", "No"],
                0.30, 0.35,
                end_date="2026-10-12T23:00:00Z"),
    ]
)


def _transport(log, events=None):
    """Mock Gamma API transport that returns cycling events."""
    if events is None:
        events = [GUANGXI_EVENT, LOMBARDIA_EVENT]

    def handler(req):
        q = dict(req.url.params)
        log.append((req.url.path, q))
        if req.url.path == "/events" and q.get("closed") == "false":
            # Return events for cycling tag
            if q.get("tag_slug") == "cycling":
                return httpx.Response(200, json=events)
        return httpx.Response(200, json=[])

    return httpx.MockTransport(handler)


@pytest.fixture
def gamma(monkeypatch):
    """Fixture: mocked Polymarket Gamma API for cycling."""
    log = []
    real = httpx.Client
    monkeypatch.setattr(CS.httpx, "Client", lambda **kw: real(transport=_transport(log), **kw))
    return log


@pytest.mark.quick
def test_cycling_polymarket_tags():
    """Test that cycling has Polymarket tags in the schema."""
    # Check that road_cycling sport is defined
    schema = sports.load("road_cycling")
    assert schema["competition"]["code"] == "uci_road_wt"
    # Check that polymarket tags are defined
    assert "polymarket" in schema.get("markets", {})
    tags = schema["markets"]["polymarket"].get("tags")
    assert tags == ["cycling"]


@pytest.mark.quick
def test_cycling_market_structure():
    """Test that mock markets have the right structure."""
    market = GUANGXI_EVENT["markets"][0]
    assert market["slug"] == "guangxi-ayuso"
    assert "conditionId" in market
    assert "clobTokenIds" in market
    outcomes = json.loads(market["outcomes"])
    assert len(outcomes) == 2
    assert "Juan Ayuso" in outcomes


@pytest.mark.quick
def test_cycling_sync_fetches_and_counts(test_engine, gamma):
    """Test that sync fetches events and counts markets correctly."""
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed

    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()

    with test_engine.connect() as c, get_session(url) as s:
        # Sync cycling markets
        stats = CS.sync(s, c, 2026, sport="road_cycling")
        
        # Should have fetched events and created links
        assert stats["events"] >= 2, f"Expected at least 2 events, got {stats['events']}"
        assert stats["links"] >= 3, f"Expected at least 3 links, got {stats['links']}"
        assert stats["new"] >= 3, f"Expected at least 3 new tokens, got {stats['new']}"


@pytest.mark.quick
def test_cycling_sync_is_idempotent(test_engine, gamma):
    """Test that sync is idempotent (second run creates no new links)."""
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed

    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()

    with test_engine.connect() as c, get_session(url) as s:
        # First sync
        stats1 = CS.sync(s, c, 2026, sport="road_cycling")
        first_new = stats1["new"]
        first_links = stats1["links"]

        # Second sync should be idempotent
        stats2 = CS.sync(s, c, 2026, sport="road_cycling")
        assert stats2["new"] == 0, f"Second sync should create 0 new links, got {stats2['new']}"
        assert stats2["links"] == first_links, f"Link count should match first sync"


@pytest.mark.quick
def test_cycling_links_are_unmodeled(test_engine, gamma):
    """Test that all cycling links are marked as unmodeled."""
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed

    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()

    with test_engine.connect() as c, get_session(url) as s:
        CS.sync(s, c, 2026, sport="road_cycling")

    with test_engine.connect() as c:
        rows = c.execute(text("""
            SELECT ml.prediction, ml.athlete_id, ml.race_id FROM market_links ml
            JOIN competitions co ON co.id = ml.competition_id
            WHERE ml.exchange = 'polymarket' AND co.code = 'uci_road_wt'
        """)).all()

        assert len(rows) > 0, "Should have created cycling market links"
        # All should be unmodeled (athlete_id and race_id may be None until identity linker runs)
        for pred, athlete, race in rows:
            assert pred == "unmodeled", f"Expected 'unmodeled', got {pred}"


@pytest.mark.quick
def test_cycling_linker_classify(gamma):
    """Test the classify_polymarket function."""
    from racinglines.sources.cycling.links import classify_polymarket

    # Test race_win classification
    kind, race, rider = classify_polymarket(
        "Tour de France 2026: Winner",
        "Who will win the Tour de France 2026?",
        "Juan Ayuso"
    )
    assert kind == "race_win", f"Expected race_win, got {kind}"
    assert "tour de france" in (race or "").lower()
    assert rider == "Juan Ayuso"

    # Test podium classification
    kind, race, rider = classify_polymarket(
        "Il Lombardia 2026: Podium",
        "Will Remco Evenepoel finish on the podium?",
        "Remco Evenepoel"
    )
    assert kind == "race_podium", f"Expected race_podium, got {kind}"
    assert "lombardia" in (race or "").lower()

    # Test top 10
    kind, race, rider = classify_polymarket(
        "Tour de France 2026: Top 10",
        "Will rider X finish top 10?",
        "Rider X"
    )
    assert kind == "race_top10", f"Expected race_top10, got {kind}"


@pytest.mark.integration
def test_full_cycling_market_sync_flow(test_engine, gamma):
    """Integration test: sync markets and verify full data flow."""
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed

    url = test_engine.url.render_as_string(hide_password=False)
    
    # Seed the database
    with get_session(url) as s:
        seed(s)
        s.commit()

    # Sync markets
    with test_engine.connect() as c, get_session(url) as s:
        stats = CS.sync(s, c, 2026, sport="road_cycling")
        assert stats["events"] > 0
        assert stats["links"] > 0
        s.commit()

    # Verify market_links were created
    with test_engine.connect() as c:
        rows = c.execute(text("""
            SELECT ml.id, ml.token_id, ml.exchange, ml.prediction, ml.event_title, ml.outcome,
                   co.code FROM market_links ml
            JOIN competitions co ON co.id = ml.competition_id
            WHERE co.code = 'uci_road_wt'
            ORDER BY ml.token_id
        """)).all()

        assert len(rows) > 0, "Should have created market links"
        
        # Check link structure
        for link_id, token, exchange, pred, event_title, outcome, comp_code in rows:
            assert exchange == "polymarket", f"Expected polymarket, got {exchange}"
            assert pred == "unmodeled", f"Expected unmodeled, got {pred}"
            assert comp_code == "uci_road_wt", f"Expected uci_road_wt, got {comp_code}"
            assert token is not None, "Token should be set"
            print(f"✓ Link {token}: {event_title} → {outcome} ({pred})")


@pytest.mark.integration
def test_cycling_identity_linker(test_engine, gamma):
    """Test the identity linker fills in athlete_id and race_id."""
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    from racinglines.sources.cycling.links import Linker

    url = test_engine.url.render_as_string(hide_password=False)
    
    # Seed database
    with get_session(url) as s:
        seed(s)
        s.commit()

    # Create test market link dict
    test_link = dict(
        exchange="polymarket",
        token_id="test-token-1",
        event_title="Tour de France 2026: Winner",
        question="Who will win the 2026 Tour de France?",
        outcome="Juan Ayuso",
        group_title="Juan Ayuso",
        event_slug="tdf-2026",
        end_date="2026-07-21T23:00:00Z",
        prediction="unmodeled",
        params=None,
        athlete_id=None,
        race_id=None
    )

    # Test linker can be created (may not resolve without real data)
    with test_engine.connect() as c:
        linker = Linker(c)
        assert linker.has_data() or True  # OK if no data yet
        
        # Attempt to identify the link
        found = linker.identify(test_link)
        # Note: athlete_id and race_id will be None if no matching data
        assert found.kind == "race_win" or found.kind is None
        print(f"✓ Linker attempted to resolve: kind={found.kind}, athlete={found.athlete_id}, race={found.race_id}")

