"""Structured ESPN facts and deterministic rich-preview rendering."""

from datetime import UTC, datetime, timedelta

from teamarr.core.types import Event, EventStatus, Team, Venue
from teamarr.providers.espn.preview import parse_rich_preview
from teamarr.templates.conditions import ConditionEvaluator
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.rich_preview import build_rich_preview
from teamarr.templates.variables.summary import extract_game_preview_rich


def _team(name: str, team_id: str) -> Team:
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=name.split()[-1],
        abbreviation=name[:3].upper(),
        league="mlb",
        sport="baseball",
    )


def _event(sport="baseball", league="mlb", **kw) -> Event:
    base = {
        "id": "401",
        "provider": "espn",
        "name": "Away at Home",
        "short_name": "AWY @ HOM",
        "start_time": datetime.now(UTC) + timedelta(hours=4),
        "home_team": _team("Seattle Mariners", "12"),
        "away_team": _team("Chicago Cubs", "16"),
        "status": EventStatus(state="scheduled"),
        "league": league,
        "sport": sport,
        "venue": Venue(name="T-Mobile Park", city="Seattle", state="WA"),
    }
    base.update(kw)
    return Event(**base)


def _context(event: Event):
    game = GameContext(event=event, is_home=True, team=event.home_team, opponent=event.away_team)
    ctx = TemplateContext(
        game_context=game,
        team_config=TeamChannelContext(
            team_id="12", league=event.league, sport=event.sport, team_name="Seattle Mariners"
        ),
        team_stats=None,
    )
    return ctx, game


def test_mlb_full_preview_uses_only_structured_facts():
    event = _event(
        rich_preview_data={
            "version": 1,
            "sport": "baseball",
            "league": "mlb",
            "teams": {
                "away": {
                    "record": "74-54",
                    "recent": [{"result": x} for x in "LLWWL"],
                    "leaders": [
                        {
                            "stat": "homeRuns",
                            "label": "Home Runs",
                            "name": "Pete Crow-Armstrong",
                            "value": "31",
                        }
                    ],
                    "probable": {
                        "name": "Matthew Boyd",
                        "stats": {"wins": "8", "losses": "2", "ERA": "4.02"},
                    },
                },
                "home": {
                    "record": "60-68",
                    "recent": [{"result": x} for x in "WWLWL"],
                    "leaders": [
                        {
                            "stat": "avg",
                            "label": "Batting Average",
                            "name": "Randy Arozarena",
                            "value": ".272",
                        }
                    ],
                    "probable": {
                        "name": "Emerson Hancock",
                        "stats": {"wins": "7", "losses": "7", "ERA": "3.30"},
                    },
                },
            },
            "series": {"score": "0-0", "games": 3},
        }
    )
    text = build_rich_preview(event)
    assert "open a three-game series" in text
    assert "Pete Crow-Armstrong with 31 home runs" in text
    assert "Probable starter Matthew Boyd is 8-2 with a 4.02 ERA" in text
    assert "Randy Arozarena with .272 batting average" in text
    assert "odds" not in text.lower() and "favored" not in text.lower()


def test_football_partial_preview_and_no_betting_data():
    event = _event(
        sport="football",
        league="nfl",
        home_team=_team("Denver Broncos", "7"),
        away_team=_team("Green Bay Packers", "9"),
        venue=Venue(name="Empower Field at Mile High", city="Denver", state="CO"),
        season_type="preseason",
        rich_preview_data={
            "version": 1,
            "sport": "football",
            "season_type": "preseason",
            "week": 3,
            "teams": {
                "away": {
                    "record": "0-1",
                    "recent": [{"result": "L", "score": "28-9", "opponent": "Pittsburgh Steelers"}],
                    "stats": {"yardsPerGame": "204.0", "rushingYardsPerGame": "63.0"},
                },
                "home": {
                    "record": "1-0",
                    "recent": [{"result": "W", "score": "27-7", "opponent": "Atlanta Falcons"}],
                    "stats": {"yardsPerGame": "360.0", "rushingYardsPerGame": "162.0"},
                },
            },
            # Even malformed callers cannot cause betting prose: the renderer
            # has no code path that consumes this key.
            "odds": {"spread": -6.5, "over_under": 40.5},
        },
    )
    text = build_rich_preview(event)
    assert "Week 3 preseason matchup" in text
    assert "28-9 loss to Pittsburgh Steelers" in text
    assert "360 total yards per game, including 162 rushing" in text
    assert "6.5" not in text and "40.5" not in text


def test_live_and_final_events_keep_frozen_preview_copy():
    data = {"teams": {"away": {"record": "1-0"}, "home": {"record": "0-1"}}}
    scheduled = build_rich_preview(_event(rich_preview_data=data))
    live = build_rich_preview(
        _event(status=EventStatus(state="in_progress"), rich_preview_data=data)
    )
    final = build_rich_preview(_event(status=EventStatus(state="final"), rich_preview_data=data))
    assert live == scheduled
    assert final == scheduled


def test_generic_team_sport_uses_records_form_and_available_leader():
    event = _event(
        sport="basketball",
        league="nba",
        rich_preview_data={
            "teams": {
                "away": {
                    "record": "8-4",
                    "recent": [{"result": result} for result in "WWWLL"],
                    "leaders": [
                        {
                            "stat": "pointsPerGame",
                            "label": "Points Per Game",
                            "name": "A. Player",
                            "value": "27.4",
                        }
                    ],
                },
                "home": {"record": "10-2", "recent": []},
            }
        },
    )
    text = build_rich_preview(event)
    assert "enters at 8-4 after going 3-2" in text
    assert "A. Player with 27.4 points per game" in text
    assert "enters at 10-2" in text


def test_variable_and_condition_share_renderer():
    event = _event(
        rich_preview_data={"teams": {"away": {"record": "1-0"}, "home": {"record": "0-1"}}}
    )
    ctx, game = _context(event)
    assert extract_game_preview_rich(ctx, game) == build_rich_preview(event)
    assert ConditionEvaluator().evaluate("has_rich_preview", None, ctx, game)


def test_parser_excludes_betting_and_ignores_preseason_series():
    event = _event()
    payload = {
        "header": {
            "week": 3,
            "competitions": [
                {
                    "competitors": [
                        {
                            "homeAway": "home",
                            "team": {
                                "id": "12",
                                "displayName": "Seattle Mariners",
                                "abbreviation": "SEA",
                            },
                            "record": [{"type": "total", "summary": "60-68"}],
                        },
                        {
                            "homeAway": "away",
                            "team": {
                                "id": "16",
                                "displayName": "Chicago Cubs",
                                "abbreviation": "CHC",
                            },
                            "record": [{"type": "total", "summary": "74-54"}],
                        },
                    ]
                }
            ],
        },
        "seasonseries": [
            {"type": "preseason", "summary": "CHC win series 2-0"},
            {
                "type": "season",
                "summary": "Series tied 0-0",
                "seriesScore": "0-0",
                "totalCompetitions": 3,
            },
        ],
        "pickcenter": [{"details": "SEA -2.5"}],
        "odds": [{"overUnder": 8.5}],
        "predictor": {"homeTeam": {"gameProjection": "55%"}},
    }
    parsed = parse_rich_preview(payload, event)
    assert parsed["teams"]["away"]["record"] == "74-54"
    assert parsed["series"]["games"] == 3
    assert "preseason" not in str(parsed["series"]).lower()
    assert "pickcenter" not in parsed and "odds" not in parsed and "predictor" not in parsed


def test_series_summary_expands_team_abbreviation_to_full_name():
    event = _event(
        home_team=_team("Los Angeles Dodgers", "19"),
        away_team=_team("Pittsburgh Pirates", "23"),
    )
    payload = {
        "header": {
            "competitions": [
                {
                    "competitors": [
                        {
                            "homeAway": "home",
                            "team": {
                                "id": "19",
                                "displayName": "Los Angeles Dodgers",
                                "abbreviation": "LAD",
                            },
                        },
                        {
                            "homeAway": "away",
                            "team": {
                                "id": "23",
                                "displayName": "Pittsburgh Pirates",
                                "abbreviation": "PIT",
                            },
                        },
                    ]
                }
            ]
        },
        "seasonseries": [
            {"type": "season", "summary": "LAD lead series 2-1", "seriesScore": "2-1"}
        ],
    }

    parsed = parse_rich_preview(payload, event)
    event.rich_preview_data = parsed
    text = build_rich_preview(event)

    assert "Los Angeles Dodgers lead series 2-1" in text
    assert "LAD" not in text
