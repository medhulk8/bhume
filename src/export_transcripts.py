"""Convert Claude Code JSONL session files to readable markdown transcripts.

Usage:
    python export_transcripts.py <jsonl_file> <output_md>
    python export_transcripts.py --all  # converts all sessions to transcripts/
"""

import json
import sys
from pathlib import Path

SESSIONS_DIR = Path.home() / ".claude/projects/-Users-medhul-Desktop-projects-bhume"
TRANSCRIPTS_DIR = Path(__file__).parent.parent / "transcripts"


def jsonl_to_md(jsonl_path: Path, out_path: Path):
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    lines = [f"# Claude Code Session Transcript\n\n**File:** `{jsonl_path.name}`\n"]
    msg_count = 0

    for rec in records:
        rec_type = rec.get("type", "")
        if rec_type not in ("user", "assistant"):
            continue
        # Message content is nested under rec["message"]
        msg = rec.get("message", {})
        role = msg.get("role", rec_type)
        content = msg.get("content", "")
        ts = rec.get("timestamp", "")[:19] if rec.get("timestamp") else ""

        text = _extract_text(content)
        if not text.strip():
            continue

        msg_count += 1
        if role == "user":
            lines.append(f"\n---\n\n**USER** {ts}\n\n{text}\n")
        else:
            lines.append(f"\n**ASSISTANT** {ts}\n\n{text}\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {out_path} ({msg_count} messages)")


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    name = block.get("name", "tool")
                    inp = json.dumps(block.get("input", {}), indent=2)[:300]
                    parts.append(f"*[Tool call: {name}]*\n```json\n{inp}\n```")
                elif block.get("type") == "tool_result":
                    content_inner = block.get("content", "")
                    text_inner = _extract_text(content_inner)[:500]
                    parts.append(f"*[Tool result]*\n```\n{text_inner}\n```")
        return "\n\n".join(p for p in parts if p.strip())
    return ""


def main():
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)

    if "--all" in sys.argv:
        jsonl_files = sorted(SESSIONS_DIR.glob("*.jsonl"))
        for i, f in enumerate(jsonl_files, 1):
            out = TRANSCRIPTS_DIR / f"session_{i}_{f.stem[:8]}.md"
            jsonl_to_md(f, out)
    elif len(sys.argv) == 3:
        jsonl_to_md(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        # Default: convert the largest session (main project session)
        jsonl_files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_size, reverse=True)
        if not jsonl_files:
            print("No JSONL files found")
            sys.exit(1)
        main_session = jsonl_files[0]
        out = TRANSCRIPTS_DIR / f"claude_session_{main_session.stem[:8]}.md"
        jsonl_to_md(main_session, out)


if __name__ == "__main__":
    main()
