from __future__ import annotations

import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from matrix.db import Database
from matrix.quarantine_handler import move_to_quarantine

console = Console()


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _show_group(db: Database, group_id: int) -> None:
    g = db.fetchone("SELECT * FROM duplicate_groups WHERE id=?", (group_id,))
    if not g:
        console.print("[red]Group not found[/]")
        return
    members = db.fetchall(
        "SELECT * FROM assets WHERE duplicate_group_id=? ORDER BY is_master DESC, confidence DESC",
        (group_id,),
    )
    table = Table(title=f"Group #{group_id} — {g['group_type']}")
    table.add_column("Role")
    table.add_column("Path")
    table.add_column("Type")
    table.add_column("Size")
    table.add_column("Dims")
    table.add_column("Conf")
    for m in members:
        dims = f"{m['width']}x{m['height']}" if m["width"] else "—"
        role = "MASTER" if m["is_master"] else "candidate"
        table.add_row(
            role,
            m["path"],
            m["file_type"],
            _format_bytes(int(m["size_bytes"])),
            dims,
            f"{m['confidence']:.2f}" if m["confidence"] else "—",
        )
    console.print(table)
    finder = " [F]inder" if platform.system() == "Darwin" else ""
    console.print(
        Panel(
            f"Match: {g['group_type']} | Actions: [K]eep All  [D]elete Duplicates  [S]kip  [M]anual{finder}  [Q]uit",
            title="Review",
        )
    )


def _reveal_in_finder(path: str) -> None:
    if platform.system() != "Darwin":
        console.print("[yellow]Finder reveal is macOS-only[/]")
        return
    p = Path(path)
    if not p.is_file():
        console.print(f"[red]File not found: {path}[/]")
        return
    subprocess.run(["open", "-R", str(p)], check=False)
    console.print(f"[dim]Revealed in Finder: {path}[/]")


def run_review(db: Database, dry_run: bool = True, execute: bool = False) -> None:
    if execute:
        dry_run = False

    groups = db.fetchall(
        """
        SELECT dg.* FROM duplicate_groups dg
        WHERE dg.group_type IN ('EXACT', 'VISUAL')
        AND EXISTS (
            SELECT 1 FROM assets a
            WHERE a.duplicate_group_id = dg.id AND a.review_status = 'PENDING'
        )
        ORDER BY dg.id
        """
    )
    if not groups:
        console.print("[green]No pending duplicate groups.[/]")
        return

    mode = "DRY-RUN" if dry_run else "EXECUTE → quarantine"
    console.print(f"[bold]MATRIX Review[/] ({mode}) — {len(groups)} groups\n")

    for g in groups:
        gid = int(g["id"])
        _show_group(db, gid)
        choices = ["k", "d", "s", "m", "q"]
        if platform.system() == "Darwin":
            choices.append("f")
        choice = Prompt.ask("Action", choices=choices, default="s").lower()
        if choice == "q":
            break
        if choice == "f":
            members = db.fetchall(
                "SELECT path FROM assets WHERE duplicate_group_id=? ORDER BY is_master DESC",
                (gid,),
            )
            for i, m in enumerate(members, 1):
                console.print(f"  [{i}] {m['path']}")
            pick = Prompt.ask("Reveal which file #", default="1")
            try:
                idx = int(pick) - 1
                if 0 <= idx < len(members):
                    _reveal_in_finder(members[idx]["path"])
            except ValueError:
                console.print("[red]Invalid number[/]")
            continue

        action_map = {
            "k": "KEEP_ALL",
            "d": "DELETE_DUPLICATES",
            "s": "SKIP",
            "m": "MANUAL",
        }
        action = action_map[choice]
        cur = db.execute(
            """
            INSERT INTO review_decisions (duplicate_group_id, action, dry_run, notes)
            VALUES (?, ?, ?, ?)
            """,
            (gid, action, 1 if dry_run else 0, None),
        )
        decision_id = int(cur.lastrowid)

        if action == "KEEP_ALL":
            db.execute(
                "UPDATE assets SET review_status='APPROVED', updated_at=? WHERE duplicate_group_id=?",
                (datetime.now(timezone.utc).isoformat(), gid),
            )
        elif action == "SKIP" or action == "MANUAL":
            status = "SKIPPED" if action == "SKIP" else "PENDING"
            db.execute(
                "UPDATE assets SET review_status=?, updated_at=? WHERE duplicate_group_id=?",
                (status, datetime.now(timezone.utc).isoformat(), gid),
            )
        elif action == "DELETE_DUPLICATES":
            members = db.fetchall(
                "SELECT * FROM assets WHERE duplicate_group_id=? AND is_master=0",
                (gid,),
            )
            for m in members:
                move_to_quarantine(
                    db,
                    int(m["id"]),
                    Path(m["path"]),
                    dry_run=dry_run,
                    review_decision_id=decision_id,
                )
            db.execute(
                "UPDATE assets SET review_status='APPROVED', updated_at=? WHERE duplicate_group_id=? AND is_master=1",
                (datetime.now(timezone.utc).isoformat(), gid),
            )

        console.print(f"[dim]Recorded: {action}[/]\n")