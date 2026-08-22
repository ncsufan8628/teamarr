"""Deterministic rich sports-preview prose from structured provider facts."""

from __future__ import annotations

from teamarr.core import Event, Team


def _number_word(value: int) -> str:
    return {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}.get(value, str(value))


def _clean_number(value: str) -> str:
    return value[:-2] if value.endswith(".0") else value


def _team_subject(team: Team) -> str:
    """Prefer the provider's location/club prefix for subsequent sentences."""
    short = (team.short_name or "").strip()
    full = team.name.strip()
    if short and full.lower().endswith(f" {short.lower()}"):
        return full[: -(len(short) + 1)]
    return full


def _has_team_detail(team: dict) -> bool:
    return any(team.get(key) for key in ("record", "recent", "leaders", "probable", "stats"))


def _recent_phrase(team: dict) -> str:
    games = team.get("recent") or []
    if not games:
        return ""
    wins = sum(1 for game in games if game.get("result") == "W")
    if len(games) == 1:
        game = games[0]
        result = "win" if game.get("result") == "W" else "loss"
        score = f"{game['score']} " if game.get("score") else ""
        opponent = f" to {game['opponent']}" if game.get("opponent") else ""
        if game.get("result") == "W":
            opponent = f" over {game['opponent']}" if game.get("opponent") else ""
        return f"after a {score}{result}{opponent}"
    return f"after going {wins}-{len(games) - wins} in its last {len(games)} games"


def _leader(team: dict, preferred: tuple[str, ...]) -> dict | None:
    leaders = team.get("leaders") or []
    for stat in preferred:
        found = next((item for item in leaders if item.get("stat") == stat), None)
        if found:
            return found
    return leaders[0] if leaders else None


def _record_intro(name: str, record: str, recent: str) -> str:
    pieces = []
    if record:
        pieces.append(f"enters at {record}")
    if recent:
        pieces.append(recent)
    if not pieces:
        return name
    return f"{name} " + " ".join(pieces)


def _base_sentence(event: Event, data: dict) -> str:
    away = event.away_team.name
    home = event.home_team.name
    venue = event.venue.name if event.venue else ""
    location = f" at {venue}" if venue else ""
    week = data.get("week")
    season_type = data.get("season_type")
    if event.sport == "football" and week:
        phase = "preseason " if season_type == "preseason" else ""
        return f"The {away} visit the {home}{location} for a Week {week} {phase}matchup."
    series = data.get("series") or {}
    if series.get("score") == "0-0" and series.get("games"):
        count = _number_word(int(series["games"]))
        return f"The {away} visit the {home}{location} to open a {count}-game series."
    summary = series.get("summary")
    suffix = f", with {summary.rstrip('.').lower()}" if summary else ""
    return f"The {away} visit the {home}{location}{suffix}."


def _baseball_team_sentence(name: str, team: dict) -> str:
    text = _record_intro(name, team.get("record") or "", _recent_phrase(team))
    leader = _leader(team, ("homeRuns", "avg", "RBIs"))
    if leader:
        labels = {"homeRuns": "home runs", "avg": "batting average", "RBIs": "RBI"}
        text += (
            f", led by {leader['name']} with {leader['value']} "
            f"{labels.get(leader['stat'], leader.get('label', ''))}"
        )
    probable = team.get("probable") or {}
    if probable.get("name"):
        stats = probable.get("stats") or {}
        details = []
        if stats.get("wins") is not None and stats.get("losses") is not None:
            details.append(f"{stats['wins']}-{stats['losses']}")
        if stats.get("ERA"):
            details.append(f"a {stats['ERA']} ERA")
        if details:
            text += f". Probable starter {probable['name']} is " + " with ".join(details)
        else:
            text += f". {probable['name']} is the probable starter"
    return text + "."


def _football_team_sentence(name: str, team: dict) -> str:
    text = _record_intro(name, team.get("record") or "", _recent_phrase(team))
    stats = team.get("stats") or {}
    yards = stats.get("yardsPerGame")
    rushing = stats.get("rushingYardsPerGame")
    if yards:
        text += f", producing {_clean_number(yards)} total yards per game"
        if rushing:
            text += f", including {_clean_number(rushing)} rushing"
    leader = _leader(team, ("passingYards", "rushingYards", "receivingYards"))
    if leader:
        text += f". {leader['name']} leads the team with {leader['value']}"
    return text + "."


def _generic_team_sentence(name: str, team: dict) -> str:
    text = _record_intro(name, team.get("record") or "", _recent_phrase(team))
    leader = _leader(team, ("pointsPerGame", "goals", "assists", "points"))
    if leader:
        text += f", led by {leader['name']} with {leader['value']} {leader['label'].lower()}"
    return text + "."


def build_rich_preview(event: Event | None) -> str:
    """Return complete source-grounded prose, or empty when insufficient.

    Structured facts are captured before kickoff and remain a stable snapshot
    through the event. The service layer prevents live box-score data from
    replacing that snapshot.
    """
    if not event:
        return ""
    data = event.rich_preview_data or {}
    teams = data.get("teams") or {}
    away = teams.get("away") or {}
    home = teams.get("home") or {}
    series = data.get("series") or {}
    if not data or not (_has_team_detail(away) or _has_team_detail(home) or series):
        return ""

    if event.sport == "baseball":
        render = _baseball_team_sentence
    elif event.sport == "football":
        render = _football_team_sentence
    else:
        render = _generic_team_sentence
    sentences = [_base_sentence(event, data)]
    if _has_team_detail(away):
        sentences.append(render(_team_subject(event.away_team), away))
    if _has_team_detail(home):
        sentences.append(render(_team_subject(event.home_team), home))
    return " ".join(sentences)
