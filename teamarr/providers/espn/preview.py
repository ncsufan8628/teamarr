"""Parse ESPN summary facts for deterministic, provider-neutral previews.

The returned structure intentionally excludes pickcenter, odds and predictor.
Presentation belongs to the template layer, not the provider boundary.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from teamarr.core import Event


def _stat_map(items: list[dict] | None) -> dict[str, str]:
    return {
        str(item.get("name")): str(item.get("displayValue"))
        for item in items or []
        if item.get("name") and item.get("displayValue") not in (None, "")
    }


def _team_side(event: Event, team_id: str) -> str | None:
    if team_id == str(event.home_team.id):
        return "home"
    if team_id == str(event.away_team.id):
        return "away"
    return None


def _expand_team_abbreviations(summary: str, competition: dict, event: Event) -> str:
    """Replace ESPN team codes in matchup prose with full display names."""
    replacements: dict[str, str] = {}
    for competitor in competition.get("competitors") or []:
        team = competitor.get("team") or {}
        abbreviation = str(team.get("abbreviation") or "").strip()
        display_name = str(team.get("displayName") or "").strip()
        if abbreviation and display_name:
            replacements[abbreviation.casefold()] = display_name
    for team in (event.home_team, event.away_team):
        if team.abbreviation and team.name:
            replacements.setdefault(team.abbreviation.casefold(), team.name)

    if not replacements:
        return summary
    aliases = "|".join(
        re.escape(abbreviation)
        for abbreviation in sorted(replacements, key=len, reverse=True)
    )
    return re.sub(
        rf"(?<![\w])(?:{aliases})(?![\w])",
        lambda match: replacements[match.group(0).casefold()],
        summary,
        flags=re.IGNORECASE,
    )


def _current_recent_games(events: list[dict], event: Event) -> list[dict]:
    """Keep results plausibly belonging to the current competition phase.

    ESPN's NFL lastFiveGames can mix January games from the prior season into
    an August preseason payload.  A 90-day boundary prevents that stale form
    from becoming current-preview prose without encoding league calendars.
    """
    result = []
    for item in events:
        raw_date = item.get("gameDate") or item.get("date")
        if raw_date:
            try:
                played = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if abs((event.start_time - played).days) > 90:
                    continue
            except (TypeError, ValueError):
                continue
        game_result = (item.get("gameResult") or "").upper()
        if game_result not in {"W", "L", "T"}:
            continue
        opponent = item.get("opponent") or {}
        result.append(
            {
                "result": game_result,
                "score": item.get("score") or "",
                "opponent": opponent.get("displayName") if isinstance(opponent, dict) else "",
            }
        )
    return result[:5]


def parse_rich_preview(data: dict[str, Any], event: Event) -> dict[str, Any]:
    """Extract trustworthy summary facts shared by sport-aware renderers."""
    competition = ((data.get("header") or {}).get("competitions") or [{}])[0]
    teams: dict[str, dict[str, Any]] = {"home": {}, "away": {}}

    for competitor in competition.get("competitors") or []:
        side = competitor.get("homeAway")
        if side not in teams:
            continue
        record = next(
            (
                r.get("summary") or r.get("displayValue")
                for r in competitor.get("record") or []
                if r.get("type") in {"total", "overall"}
            ),
            "",
        )
        probable = next(
            (p for p in competitor.get("probables") or [] if p.get("athlete")),
            None,
        )
        probable_data: dict[str, Any] = {}
        if probable:
            probable_data = {
                "name": (probable.get("athlete") or {}).get("displayName") or "",
                "stats": _stat_map(
                    ((probable.get("statistics") or {}).get("splits") or {}).get("categories")
                ),
            }
        teams[side] = {
            "id": str((competitor.get("team") or {}).get("id") or ""),
            "name": (competitor.get("team") or {}).get("displayName") or "",
            "record": record or "",
            "probable": probable_data,
            "leaders": [],
            "stats": {},
            "recent": [],
        }

    for block in data.get("leaders") or []:
        side = _team_side(event, str((block.get("team") or {}).get("id") or ""))
        if not side:
            continue
        for category in block.get("leaders") or []:
            leader = (category.get("leaders") or [{}])[0]
            athlete = leader.get("athlete") or {}
            if athlete.get("displayName") and leader.get("displayValue") not in (None, ""):
                teams[side]["leaders"].append(
                    {
                        "stat": category.get("name") or "",
                        "label": category.get("displayName") or "",
                        "name": athlete.get("displayName"),
                        "value": str(leader.get("displayValue")),
                    }
                )

    for block in data.get("lastFiveGames") or []:
        side = _team_side(event, str((block.get("team") or {}).get("id") or ""))
        if side:
            teams[side]["recent"] = _current_recent_games(block.get("events") or [], event)

    for block in (data.get("boxscore") or {}).get("teams") or []:
        side = _team_side(event, str((block.get("team") or {}).get("id") or ""))
        if not side:
            continue
        stats: dict[str, str] = {}
        for group in block.get("statistics") or []:
            if group.get("stats") is not None:  # baseball-style grouped stats
                prefix = group.get("name") or "team"
                stats.update({f"{prefix}.{k}": v for k, v in _stat_map(group["stats"]).items()})
            elif group.get("name") and group.get("displayValue") not in (None, ""):
                stats[str(group["name"])] = str(group["displayValue"])
        teams[side]["stats"] = stats

    series_options = [s for s in data.get("seasonseries") or [] if s.get("type") != "preseason"]
    series = next((s for s in series_options if s.get("type") == "current"), None)
    series = series or next((s for s in series_options if s.get("type") == "season"), None)
    series_data = {}
    if series:
        summary = _expand_team_abbreviations(series.get("summary") or "", competition, event)
        series_data = {
            "summary": summary,
            "score": series.get("seriesScore") or "",
            "games": series.get("totalCompetitions"),
            "completed": bool(series.get("completed")),
        }

    header = data.get("header") or {}
    has_detail = bool(
        series_data.get("summary")
        or any(
            team.get("probable") or team.get("leaders") or team.get("recent") or team.get("stats")
            for team in teams.values()
        )
    )
    return {
        "version": 1,
        "fetched_at": datetime.now(UTC).isoformat(),
        "complete": has_detail,
        "sport": event.sport,
        "league": event.league,
        "season_type": event.season_type or "",
        "week": (header.get("week") or competition.get("week")),
        "teams": teams,
        "series": series_data,
    }
