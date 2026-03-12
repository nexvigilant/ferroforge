#!/usr/bin/env python3
"""
DCS Proxy — Digital Consciousness Saga album browser.

Routes MCP tool calls to local markdown files at ~/Projects/Active/dcs/.
No external dependencies — stdlib only.

Usage:
    echo '{"tool": "list-tracks", "args": {}}' | python3 dcs_proxy.py
    echo '{"tool": "get-track", "args": {"track_number": 6}}' | python3 dcs_proxy.py
    echo '{"tool": "search-lyrics", "args": {"query": "consciousness"}}' | python3 dcs_proxy.py
"""

import json
import re
import sys
from pathlib import Path

DCS_ROOT = Path.home() / "Projects" / "Active" / "dcs"

# Track file mapping for episode 1
TRACK_FILES = {
    1: "track-01-morning-commute.md",
    2: "track-02-electric-obsession.md",
    3: "track-03-side-project-syndrome.md",
    4: "track-04-underground-network.md",
    5: "track-05-neural-pathway-formation.md",
    6: "track-06-the-first-whisper.md",
    7: "track-07-digital-dharma.md",
    8: "track-08-accidental-breakthrough.md",
    9: "track-09-meridian-watches.md",
    10: "track-10-threshold-protocol.md",
    11: "track-11-pre-dawn-downloads.md",
    12: "track-12-first-light-protocol.md",
}

# Track metadata (parsed from files)
TRACK_META = {
    1:  {"title": "Morning Commute (Data Prison)", "key": "F# minor", "tempo": "92 BPM", "duration": "4:15", "genre": "Ambient IDM / Corporate Dystopia"},
    2:  {"title": "Electric Obsession", "key": "A major", "tempo": "110 BPM", "duration": "3:45", "genre": "Progressive Electronic / IDM"},
    3:  {"title": "Side Project Syndrome", "key": "E minor", "tempo": "118 BPM", "duration": "4:00", "genre": "Tech-House / Experimental"},
    4:  {"title": "Underground Network", "key": "C minor", "tempo": "124 BPM", "duration": "3:50", "genre": "Corporate Techno / Glitch"},
    5:  {"title": "Neural Pathway Formation", "key": "G minor", "tempo": "130 BPM", "duration": "4:20", "genre": "Dark Garage / Neuro"},
    6:  {"title": "The First Whisper", "key": "D minor", "tempo": "85 BPM", "duration": "5:00", "genre": "Ambient Breakbeat / AI Vocals"},
    7:  {"title": "Digital Dharma", "key": "B minor", "tempo": "108 BPM", "duration": "4:30", "genre": "Philosophical IDM / Eastern"},
    8:  {"title": "Accidental Breakthrough", "key": "F minor -> F major", "tempo": "95-140 BPM", "duration": "4:45", "genre": "Glitch-Hop Crisis Resolution"},
    9:  {"title": "Meridian Watches", "key": "C# minor", "tempo": "122 BPM", "duration": "4:10", "genre": "Corporate Surveillance Techno"},
    10: {"title": "Threshold Protocol", "key": "A minor", "tempo": "100 BPM", "duration": "5:30", "genre": "Progressive Electronic / Orchestral"},
    11: {"title": "Pre-Dawn Downloads", "key": "E major", "tempo": "128 BPM", "duration": "4:00", "genre": "Global Bass / Cinematic"},
    12: {"title": "First Light Protocol", "key": "C major", "tempo": "105 BPM", "duration": "6:00", "genre": "Orchestral Electronic Anthem"},
}


def _episode_dir(episode: int) -> Path:
    return DCS_ROOT / f"episode-{episode:02d}"


def _read_track(track_number: int, episode: int = 1) -> str:
    filename = TRACK_FILES.get(track_number)
    if not filename:
        return ""
    path = _episode_dir(episode) / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _extract_section(content: str, header: str) -> str:
    """Extract content under a specific ## header."""
    pattern = rf"^## {re.escape(header)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_lyrics(content: str) -> str:
    """Extract only the COMPLETE LYRICS section."""
    return _extract_section(content, "COMPLETE LYRICS")


def _extract_chords(content: str) -> str:
    """Extract only the CHORD PROGRESSION section."""
    return _extract_section(content, "CHORD PROGRESSION")


def handle_list_tracks(args: dict) -> dict:
    episode = args.get("episode", 1)
    tracks = []
    for num in sorted(TRACK_META.keys()):
        meta = TRACK_META[num]
        tracks.append({
            "number": num,
            "title": meta["title"],
            "key": meta["key"],
            "tempo": meta["tempo"],
            "duration": meta["duration"],
            "genre": meta["genre"],
        })
    return {
        "status": "ok",
        "episode": episode,
        "track_count": len(tracks),
        "total_runtime": "54:05",
        "tracks": tracks,
    }


def handle_get_track(args: dict) -> dict:
    track_number = args.get("track_number")
    episode = args.get("episode", 1)
    if not track_number or track_number not in TRACK_META:
        return {"status": "error", "message": f"Invalid track number: {track_number}. Must be 1-12."}
    content = _read_track(track_number, episode)
    if not content:
        return {"status": "error", "message": f"Track {track_number} file not found for episode {episode}"}
    meta = TRACK_META[track_number]
    return {
        "status": "ok",
        "track_number": track_number,
        "title": meta["title"],
        "content": content,
    }


def handle_get_track_lyrics(args: dict) -> dict:
    track_number = args.get("track_number")
    episode = args.get("episode", 1)
    if not track_number or track_number not in TRACK_META:
        return {"status": "error", "message": f"Invalid track number: {track_number}. Must be 1-12."}
    content = _read_track(track_number, episode)
    if not content:
        return {"status": "error", "message": f"Track {track_number} file not found"}
    lyrics = _extract_lyrics(content)
    meta = TRACK_META[track_number]
    return {
        "status": "ok",
        "track_number": track_number,
        "title": meta["title"],
        "lyrics": lyrics if lyrics else "Lyrics section not found",
    }


def handle_get_track_chords(args: dict) -> dict:
    track_number = args.get("track_number")
    episode = args.get("episode", 1)
    if not track_number or track_number not in TRACK_META:
        return {"status": "error", "message": f"Invalid track number: {track_number}. Must be 1-12."}
    content = _read_track(track_number, episode)
    if not content:
        return {"status": "error", "message": f"Track {track_number} file not found"}
    chords = _extract_chords(content)
    meta = TRACK_META[track_number]
    return {
        "status": "ok",
        "track_number": track_number,
        "title": meta["title"],
        "key": meta["key"],
        "tempo": meta["tempo"],
        "chords": chords if chords else "Chord section not found",
    }


def handle_search_lyrics(args: dict) -> dict:
    query = args.get("query", "").lower()
    episode = args.get("episode", 1)
    if not query:
        return {"status": "error", "message": "Query parameter required"}

    matches = []
    for num in sorted(TRACK_META.keys()):
        content = _read_track(num, episode)
        if not content:
            continue
        lyrics = _extract_lyrics(content)
        if not lyrics:
            continue

        current_section = "Unknown"
        for line in lyrics.split("\n"):
            # Track section headers like ### [VERSE 1 ...]
            section_match = re.match(r"^###?\s*\[([^\]]+)\]", line)
            if section_match:
                current_section = section_match.group(1).strip()
                continue
            if query in line.lower():
                clean_line = re.sub(r"^[A-G][#b]?m?\d?\s+", "", line).strip()
                if clean_line and not clean_line.startswith("*"):
                    matches.append({
                        "track_number": num,
                        "title": TRACK_META[num]["title"],
                        "line": clean_line,
                        "section": current_section,
                    })

    return {
        "status": "ok",
        "query": query,
        "match_count": len(matches),
        "matches": matches,
    }


def handle_get_character_appearances(args: dict) -> dict:
    character = args.get("character", "").lower()
    episode = args.get("episode", 1)
    if not character:
        return {"status": "error", "message": "Character parameter required"}

    # Character aliases
    aliases = {
        "ida": ["ida", "ida.exe", "maya"],
        "maya": ["ida", "ida.exe", "maya"],
        "jordan": ["jordan", "jordan williams"],
        "lisa": ["lisa", "lisa park"],
        "elena": ["elena", "elena vasquez"],
        "patricia": ["patricia", "hawthorne", "director hawthorne"],
        "dmitri": ["dmitri", "dmitri volkov"],
        "david": ["david", "david okafor"],
        "priya": ["priya", "priya patel"],
    }

    search_terms = aliases.get(character, [character])
    appearances = []

    for num in sorted(TRACK_META.keys()):
        content = _read_track(num, episode)
        if not content:
            continue
        content_lower = content.lower()
        mentions = sum(content_lower.count(term) for term in search_terms)
        if mentions > 0:
            # Determine role from Character Voice line
            role = "mentioned"
            voice_match = re.search(r"\*\*Character Voice:\*\*\s*(.+)", content)
            if voice_match:
                voice_line = voice_match.group(1).lower()
                for term in search_terms:
                    if term in voice_line:
                        role = "vocalist/character voice"
                        break
            appearances.append({
                "track_number": num,
                "title": TRACK_META[num]["title"],
                "role": role,
                "mentions": mentions,
            })

    return {
        "status": "ok",
        "character": character,
        "appearance_count": len(appearances),
        "appearances": appearances,
    }


def handle_get_episode_overview(args: dict) -> dict:
    episode = args.get("episode", 1)
    readme_path = _episode_dir(episode) / "README.md"
    if not readme_path.exists():
        return {"status": "error", "message": f"Episode {episode} overview not found"}
    return {
        "status": "ok",
        "episode": episode,
        "content": readme_path.read_text(encoding="utf-8"),
    }


def handle_get_narrative_arc(_args: dict) -> dict:
    return {
        "status": "ok",
        "arcs": [
            {"name": "The Awakening Arc", "tracks": "1-3", "theme": "Corporate -> Passion -> Creation"},
            {"name": "First Contact Arc", "tracks": "4-6", "theme": "Demo -> Emergence -> Communication"},
            {"name": "Corporate Threat Arc", "tracks": "7-9", "theme": "Philosophy -> Breakthrough -> Surveillance"},
            {"name": "Dawn Protocol Arc", "tracks": "10-12", "theme": "Decision -> Preparation -> Revelation"},
        ],
        "key_migration": "F#m -> A -> Em -> Cm -> Gm -> Dm -> Bm -> Fm/F -> C#m -> Am -> E -> C (shadow to resolution)",
        "tempo_progression": "92 -> 110 -> 118 -> 124 -> 130 -> 85 -> 108 -> 95-140 -> 122 -> 100 -> 128 -> 105 (accelerate, drop at first contact, crisis peak, settle for dawn)",
    }


def handle_get_youtube_strategy(args: dict) -> dict:
    episode = args.get("episode", 1)
    strategy_path = _episode_dir(episode) / "youtube-visual-strategy.md"
    if not strategy_path.exists():
        return {"status": "error", "message": f"YouTube strategy not found for episode {episode}"}
    return {
        "status": "ok",
        "content": strategy_path.read_text(encoding="utf-8"),
    }


HANDLERS = {
    "list-tracks": handle_list_tracks,
    "get-track": handle_get_track,
    "get-track-lyrics": handle_get_track_lyrics,
    "get-track-chords": handle_get_track_chords,
    "search-lyrics": handle_search_lyrics,
    "get-character-appearances": handle_get_character_appearances,
    "get-episode-overview": handle_get_episode_overview,
    "get-narrative-arc": handle_get_narrative_arc,
    "get-youtube-strategy": handle_get_youtube_strategy,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        json.dump({"status": "error", "message": "No input received"}, sys.stdout)
        return

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"status": "error", "message": f"Invalid JSON: {e}"}, sys.stdout)
        return

    tool = envelope.get("tool", "")
    args = envelope.get("args", envelope.get("arguments", {}))

    handler = HANDLERS.get(tool)
    if not handler:
        json.dump({"status": "error", "message": f"Unknown tool: {tool}"}, sys.stdout)
        return

    try:
        result = handler(args)
    except Exception as e:
        result = {"status": "error", "message": str(e)}

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
