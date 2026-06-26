import os
import sys
import time
import pickle
import base64
import hashlib
import random
import itertools
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from typing import List, Dict

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, IntPrompt
from rich.rule import Rule
from rich import box
from rich.columns import Columns

console = Console()

DB_FILE = "votes.txt"
PARTICIPANTS = ["Filip i Karolina", "Tomek i Julia", "Tomek i Martyna", "Bartek i Julia"]


# ─── VISUAL HELPERS ───────────────────────────────────────────────────────────


def animated_ascii(art: str, batch: int = 12, noise_frames: int = 4, frame_delay: float = 0.035):
    """
    Fade-in animation for ASCII art.

    Each non-space character is revealed in a random order:
      1. A random block/noise character flickers at it briefly  (dim green)
      2. The correct character snaps into place                  (bold green)

    Characters are revealed in small random batches so the whole logo
    materialises gradually rather than all at once.

    Args:
        art:          Multi-line ASCII string.
        batch:        How many characters to reveal per frame.
        noise_frames: How many flicker frames before the char locks in.
        frame_delay:  Seconds between frames.
    """
    from rich.live import Live

    # ── noise palette — visually heavy so the flicker reads as "static" ───────
    NOISE = list("█▓▒░▄▀■□▪▫")

    # ── colour stages: noise → locked ─────────────────────────────────────────
    # We step through these styles as noise_frames elapse, finishing on the
    # final style so the character "brightens" as it resolves.
    NOISE_STYLES = ["color(22)", "color(28)", "color(34)"]  # dark → mid green
    FINAL_STYLE = "bold bright_green"
    SETTLED_STYLE = "bold green"  # calmer shade once the whole art is done

    lines = art.splitlines()
    rows = len(lines)
    cols = max(len(l) for l in lines)

    # Pad all lines to the same width so indexing is uniform
    grid = [list(line.ljust(cols)) for line in lines]

    # Collect every position that has a non-space character
    targets = [(r, c) for r in range(rows) for c in range(cols) if grid[r][c] != " "]
    random.shuffle(targets)

    # State arrays:
    #   revealed[r][c] = True  → character has locked in
    #   noise_left[r][c]       → frames of noise still to show (0 = not yet started)
    revealed = [[False] * cols for _ in range(rows)]
    noise_left = [[0] * cols for _ in range(rows)]
    active = set()  # positions currently flickering

    def render() -> Text:
        """Build the full art as a Rich Text object from current state."""
        text = Text()
        for r in range(rows):
            for c in range(cols):
                ch = grid[r][c]
                if revealed[r][c]:
                    text.append(ch, style=FINAL_STYLE)
                elif (r, c) in active:
                    frames_done = noise_frames - noise_left[r][c]
                    style = NOISE_STYLES[min(frames_done, len(NOISE_STYLES) - 1)]
                    text.append(random.choice(NOISE), style=style)
                else:
                    text.append(" ")
            text.append("\n")
        return text

    ptr = 0  # index into targets — next character to start revealing

    with Live(render(), console=console, refresh_per_second=60) as live:
        while True:
            # ── start a new batch of characters flickering ─────────────────
            for _ in range(batch):
                if ptr < len(targets):
                    r, c = targets[ptr]
                    active.add((r, c))
                    noise_left[r][c] = noise_frames
                    ptr += 1

            # ── advance all active flickers by one frame ───────────────────
            done_this_frame = []
            for r, c in list(active):
                noise_left[r][c] -= 1
                if noise_left[r][c] <= 0:
                    revealed[r][c] = True
                    active.discard((r, c))
                    done_this_frame.append((r, c))

            live.update(render())
            time.sleep(frame_delay)

            # ── stop when everything is revealed and no flickers remain ────
            if ptr >= len(targets) and not active:
                break

        # Final render: switch to the calmer settled style
        settled = Text()
        for r in range(rows):
            for c in range(cols):
                settled.append(grid[r][c], style=SETTLED_STYLE)
            settled.append("\n")
        live.update(settled)


def typewrite(text: str, style: str = "bold green", delay: float = 0.025):
    for ch in text:
        console.print(ch, style=style, end="")
        time.sleep(delay)
    console.print()
    time.sleep(1)


def fake_progress(label: str, steps: int = 30, delay: float = 0.018):
    with Progress(
        SpinnerColumn(spinner_name="dots2", style="green"),
        TextColumn(f"[bold green]{label}"),
        BarColumn(bar_width=28, style="green", complete_style="bright_green"),
        TextColumn("[dim green]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as p:
        t = p.add_task("", total=steps)
        for _ in range(steps):
            time.sleep(delay * 3)
            p.advance(t)
    time.sleep(0.5)


def glitch_hex(label: str, seconds: float = 1.2, message="sealed"):
    """Spinning 'cracking' animation that resolves to a real value."""
    spinners = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    end = time.time() + seconds
    result = None
    while time.time() < end:
        attempt = "".join(f"{random.randint(0,255):02X}" for _ in range(8))
        result = attempt
        console.print(
            f"  [green]{next(spinners)}[/green] [dim]{label}[/dim] " f"[bright_green]{attempt}[/bright_green]",
            end="\r",
        )
    # overwrite with final line
    console.print(
        f"  [bold green]✔[/bold green] [dim]{label}[/dim] "
        f"[bold bright_green]{result}[/bold bright_green]  [dim green]← {message}[/dim green]"
    )
    return result


def hex_mini(data: bytes):
    """Hex preview of bytes."""
    chunk_size = 25
    time.sleep(0.3)
    for chunk in [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]:
        # preview = "    " + " ".join(f"{b:02X}" for b in chunk)
        # console.print(f"[green]{preview}[/green]")
        console.print("    ", end="")
        for b in chunk:
            console.print(f"[green][dim]{b:02X} [/dim][/green]", end="")
            time.sleep(0.02)
        console.print()

    console.print()
    time.sleep(1.3)


def rule(title: str = ""):
    console.print(Rule(f"[dim green]{title}[/dim green]", style="green"))
    time.sleep(0.3)


def ok(msg: str):
    time.sleep(0.3)
    console.print(f"  [bold green]✔[/bold green] [green]{msg}[/green]")
    time.sleep(0.8)


def warn(msg: str):
    console.print(f"  [bold yellow]![/bold yellow] [yellow]{msg}[/yellow]")


def err(msg: str):
    console.print(f"  [bold red]✘[/bold red] [red]{msg}[/red]")


def show_banner():
    art = """
     ██╗   ██╗ ██████╗  ██████╗ ████████╗ ██████╗ ██╗    ██╗ █████╗ ███╗   ██╗██╗
     ██║   ██║██╔════╝ ██╔═══██╗╚══██╔══╝██╔═══██╗██║    ██║██╔══██╗████╗  ██║██║
     ██║   ██║██║  ███╗██║   ██║   ██║   ██║   ██║██║ █╗ ██║███████║██╔██╗ ██║██║
     ██║   ██║██║   ██║██║   ██║   ██║   ██║   ██║██║███╗██║██╔══██║██║╚██╗██║██║
     ╚██████╔╝╚██████╔╝╚██████╔╝   ██║   ╚██████╔╝╚███╔███╔╝██║  ██║██║ ╚████║██║
      ╚═════╝  ╚═════╝  ╚═════╝    ╚═╝    ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝v1.0"""

    # console.print(art, style="bold green")
    animated_ascii(art)
    console.print(
        Panel(
            "[dim]SECURE CRYPTOGRAPHIC VOTING SYSTEM  |  AES-256-GCM + PBKDF2  |  " "(C) Tomek Żebrowski[/dim]",
            border_style="green",
            expand=False,
        )
    )
    time.sleep(1)
    console.print()


# ─── DATA CLASSES ─────────────────────────────────────────────────────────────


class Vote:
    def __init__(self, score: int, prev_hash: str):
        self.score = score
        self.prev_hash = prev_hash

    def __repr__(self):
        return f"{self.score}/10 (prev_hash={self.prev_hash})"


class EncryptedVote:
    def __init__(self, cipherdata: str):
        self.cipherdata = cipherdata

    def __repr__(self):
        return self.cipherdata


class VoteRecord:
    def __init__(self, voter: str, votee: str, vote: EncryptedVote):
        self.voter = voter
        self.votee = votee
        self.vote = vote

    def toString(self):
        return self.voter + ":" + self.votee + ":" + self.vote.cipherdata

    def fromString(string: str) -> "VoteRecord":
        parts = string.split(":")
        return VoteRecord(parts[0], parts[1], EncryptedVote(parts[2]))

    def __repr__(self):
        return f"{self.voter}:{self.votee}:{self.vote}"


# ─── CRYPTO ───────────────────────────────────────────────────────────────────


class Crypto:
    def derive_key(passphrase: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600_000,
        )
        return kdf.derive(passphrase.encode())

    def encrypt(vote: Vote, passphrase: str) -> EncryptedVote:
        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = Crypto.derive_key(passphrase, salt)
        plaintext = pickle.dumps(vote)
        aesgcm = AESGCM(key)
        cipherdata = aesgcm.encrypt(nonce, plaintext, None)
        ciphertext = base64.b64encode(salt + nonce + cipherdata).decode("utf8")
        return EncryptedVote(ciphertext)

    def decrypt(encrypted_vote: EncryptedVote, passphrase: str) -> Vote:
        data = base64.b64decode(encrypted_vote.cipherdata)
        salt, nonce, votedata = data[:16], data[16:28], data[28:]
        plaintext = AESGCM(Crypto.derive_key(passphrase, salt)).decrypt(nonce, votedata, None)
        return pickle.loads(plaintext)

    def get_secure_short_hash(text: str) -> str:
        hasher = hashlib.sha256(text.encode("utf-8"))
        raw_bytes = hasher.digest()
        base64_bytes = base64.urlsafe_b64encode(raw_bytes)
        return base64_bytes.decode("utf-8").rstrip("=")[:16]

# ─── PASSPHRASE CHECKER ────────────────────────────────────────────────────────

class PassphraseChecker:
    def __init__(self, passphrase_hashes: Dict[str, str]):
        self.passphrase_hashes = passphrase_hashes
    
    def verify(self, votee, passphrase) -> bool:
        candidate_hash = Crypto.get_secure_short_hash(passphrase)
        if not votee in self.passphrase_hashes.keys(): # Register a password
            self.passphrase_hashes[votee] = candidate_hash
            return True
        if self.passphrase_hashes[votee] == candidate_hash:
            return True
        else:
            return False
    
    def from_string(string: str) -> "PassphraseChecker":
        passphrase_hashes = {}
        pairs = string.split(";")
        for pair in pairs:
            if pair == "":
                continue
            name, hash = pair.split(":")
            passphrase_hashes[name] = hash
        return PassphraseChecker(passphrase_hashes)


    def to_string(self) -> str:
        result = ""
        for name, hash in self.passphrase_hashes.items():
            result += name + ":" + hash + ";"
        return result


# ─── DATABASE ─────────────────────────────────────────────────────────────────


class VoteDatabase:
    def __init__(self, filename: str):
        self.filename = filename
        if not os.path.exists(self.filename):
            with open(self.filename, 'w') as file:
                file.write("======================== UGOTOWANI: Vote Database (c) ========================\n")
                file.write("    File format v1.0. Do not edit manually. Tampering prevents final count.   \n")
                file.write("             All participants shall keep a copy of the database.              \n")
                file.write("==============================================================================\n")
                file.write("\n")
    
    def store(self, record: VoteRecord):
        with open(self.filename, 'a') as file:
            file.write(">")
            file.write(record.toString())
            file.write("\n")
    
    def get_records(self) -> List[VoteRecord]:
        with open(self.filename, 'r') as file:
            return [VoteRecord.fromString(line[1:].strip()) for line in file.readlines() if line.startswith(">")]
    
    def get_latest_line(self) -> str:
        with open(self.filename, 'r') as file:
            lines = file.readlines()
            return "first-vote-certificate" if not lines else lines[-1][1:].strip()
    
    def store_passphrase_hashes(self, passphrase_checker: PassphraseChecker):
        with open(self.filename, 'r') as file:
            lines = file.readlines()
        with open(self.filename, 'w') as file:
            lines[4] = passphrase_checker.to_string() + "\n"
            file.writelines(lines)
    
    def load_passphrase_hashes(self) -> PassphraseChecker:
        with open(self.filename, 'r') as file:
            lines = file.readlines()
            return PassphraseChecker.from_string(lines[4].strip())

# ─── VOTING CLI ───────────────────────────────────────────────────────────────
def get_passphrase(database: VoteDatabase, user: str) -> str:
    def prompt_and_input(user):
        console.print()
        console.print("  [dim]Enter your secret passphrase (hidden after confirmation):[/dim]")
        passphrase = console.input("  [green]>>>[/green] ")

        warn("Remember your passphrase — you will need it during the count.")
        console.input("  [dim]Press[/dim] [bold]ENTER[/bold] [dim]when ready...[/dim]")
        sys.stdout.write("\033[1A\033[G\033[K")
        console.print()

        # Erase passphrase line from terminal
        sys.stdout.write("\033[s\033[3A\033[G\033[K")
        console.print("  [green]>>>[/green] [dim green]************  ← hidden[/dim green]")
        sys.stdout.write("\033[u")
        sys.stdout.flush()
        return passphrase

    checker = database.load_passphrase_hashes()
    passphrase = prompt_and_input(user)
    while not checker.verify(user, passphrase):
        err("Wrong passphrase! Please try again.")
        passphrase = prompt_and_input(user)
    database.store_passphrase_hashes(checker)
    return passphrase

class VotingCli:
    def __init__(self, database: VoteDatabase, participants: List[str], votee: str):
        self.database = database
        self.participants = participants
        self.votee = votee
        self.passphrase_concatenation = ""

    def run(self):
        for voter in self.participants:
            self.get_vote(voter)
        self.seal_up_database()
        typewrite("Voting done.")
        typewrite("Thank you.")

    def get_vote(self, voter: str):

        typewrite(f"\n\n  Done. Pass the console to {voter}")
        console.input("  [dim]Press[/dim] [bold]ENTER[/bold] [dim]when ready...[/dim]")
        sys.stdout.write("\033[1A\033[G\033[K")

        rule(f"VOTER SESSION  //  {voter}")

        if voter == self.votee:
            console.print(
                Panel(
                    f"[dim]You are the [bold white]votee[/bold white] in this round.\n"
                    f"Provide your passphrase — it becomes part of the security seal.[/dim]",
                    border_style="yellow",
                    expand=False,
                )
            )
            passphrase = get_passphrase(self.database, voter)
            self.passphrase_concatenation += passphrase
            return

        typewrite(f"  Authenticating voter: {voter} ...", delay=0.02)
        fake_progress("Establishing encrypted channel", steps=20, delay=0.015)

        prev_line = self.database.get_latest_line()
        prev_hash = Crypto.get_secure_short_hash(prev_line)
        ok(f"Chain hash extracted → [bold bright_green]{prev_hash}[/bold bright_green]")
        ok("Vote slot ready. Ready to record.")
        console.print()

        # Score input — hidden after entry
        console.print("  [dim]Enter your score for[/dim] " f"[bold white]{self.votee}[/bold white] [dim](0–10)[/dim]")
        while True:
            score_raw = console.input("  [green]>>>[/green] ")
            try:
                score_int = int(score_raw)
                if 0 <= score_int <= 10:
                    break
            except ValueError:
                pass
            sys.stdout.write("\033[1A\033[G\033[K")
            console.print("  [green]>>>[/green] [dim green]******[/dim green]")
            warn("Invalid score — enter an integer between 0 and 10.")

        # Overwrite the typed score with blocks
        sys.stdout.write("\033[1A\033[G\033[K")
        console.print("  [green]>>>[/green] [dim green]******  ← recorded[/dim green]")

        vote = Vote(score_int, prev_hash)

        passphrase = get_passphrase(self.database, voter)
        self.passphrase_concatenation += passphrase
        

        console.print()
        fake_progress("Deriving AES-256 key via PBKDF2 (600K rounds)", steps=40, delay=0.025)
        fake_progress("Encrypting vote payload (AES-GCM)", steps=20, delay=0.018)

        encrypted_vote = Crypto.encrypt(vote, passphrase)
        raw = base64.b64decode(encrypted_vote.cipherdata)
        ok("Encryption complete. Ciphertext preview:")
        hex_mini(raw)

        record = VoteRecord(voter, self.votee, encrypted_vote)
        self.database.store(record)
        glitch_hex("Processing encrypted vote →", message="done")
        ok(f"Record committed → [dim]{self.database.filename}[/dim]")


    def seal_up_database(self):
        console.print()
        rule("SEALING DATABASE")
        prev_line = self.database.get_latest_line()
        prev_hash = Crypto.get_secure_short_hash(prev_line)
        seal = Vote(0, prev_hash)
        fake_progress("Generating cryptographic seal", steps=25, delay=0.02)
        encrypted_seal = Crypto.encrypt(seal, self.passphrase_concatenation)
        glitch_hex("Seal digest →")
        record = VoteRecord("[SECURITY-SEAL]", "[SECURITY-SEAL]", encrypted_seal)
        self.database.store(record)
        ok("Database sealed. Integrity chain locked.")
        console.print()


# ─── REVEAL CLI ───────────────────────────────────────────────────────────────


class RevealCli:
    def __init__(self, database: VoteDatabase, participants: List[str]):
        self.database = database
        self.participants = participants
        self.passphrase_concatenated = ""

    def run(self):
        console.print()
        rule("VOTE REVEAL  //  FINAL COUNT")

        records = self.database.get_records()
        console.print()
        console.print("  [dim]Encrypted records on disk:[/dim]")
        for i, rec in enumerate(records):
            preview = rec.vote.cipherdata[:40] + "..."
            tag = "[dim red]SEAL[/dim red]" if rec.voter == "[SECURITY-SEAL]" else f"[dim]{rec.voter}[/dim]"
            console.print(f"  [bright_black]{i:02d}[/bright_black]  {tag} [dim green]{preview}[/dim green]")

        console.print()
        fake_progress("Loading encrypted record set", steps=15, delay=0.02)

        passphrases = self.collect_passwords()
        votes = self.obtain_votes(passphrases)
        if not votes:
            return

        target_hashes = self.obtain_target_hashes()
        console.print()
        rule("INTEGRITY VERIFICATION")
        typewrite("Verifying database integrity...")
        if not self.verify_hashes(votes, target_hashes):
            return
        if not self.verify_security_seal(votes):
            return
        console.print()
        ok("[bold]Database status:[/bold] [bold bright_green]INTEGRITY OK[/bold bright_green]")

        console.print()
        fake_progress("Wrapping up", steps=90, delay=0.02)
        fake_progress("Counting votes", steps=180, delay=0.02)
        fake_progress("Preparing results", steps=30, delay=0.02)

        results = self.count_votes(votes)
        self.present_results(results)

    def collect_passwords(self):
        passphrases = {}
        console.print()
        rule("PASSPHRASE COLLECTION")
        for participant in self.participants:
            passphrase = self.ask_passphrase(participant)
            passphrases[participant] = passphrase
            self.passphrase_concatenated += passphrase
        passphrases["[SECURITY-SEAL]"] = self.passphrase_concatenated
        return passphrases

    def ask_passphrase(self, participant: str):
        console.print(f"\n  [dim]Passphrase for[/dim] [bold white]{participant}[/bold white]:")
        passphrase = console.input("  [green]>>>[/green] ")
        sys.stdout.write("\033[1A\033[G\033[K")
        checker = self.database.load_passphrase_hashes()
        if checker.verify(participant, passphrase):
            console.print("  [green]>>>[/green] [dim green]************  ← accepted[/dim green]")
        else:
            console.print("  [green]>>>[/green] [dim red]************  ← mismatch?[/dim red]")
        return passphrase

    def obtain_votes(self, passphrases: Dict[str, str]):
        console.print()
        glitch_hex("Preparing vote payload", seconds=2.7, message="ready")
        try:
            votes = []
            for i, record in enumerate(self.database.get_records()):
                votes.append(Crypto.decrypt(record.vote, passphrases[record.voter]))
                fake_progress(f"Decrypting vote (index {i})")
            ok(f"Decrypted {len(votes)} record(s) successfully.")
            return votes
        except Exception:
            err("Critical error — could not decrypt votes!")
            err("Wrong passphrase or compromised database integrity.")
            err("Cannot safely proceed with the count.")
            return []

    def obtain_target_hashes(self):
        return [Crypto.get_secure_short_hash(r.toString()) for r in self.database.get_records()]

    def verify_hashes(self, votes: List[Vote], target_hashes: List[str]):
        fake_progress("Computing chain hashes", steps=20, delay=0.018)
        console.print()

        all_ok = True
        for i in range(1, len(votes)):
            vote_hash = votes[i].prev_hash
            target = target_hashes[i - 1]
            match = vote_hash == target

            if match:
                console.print(
                    f"  [bright_black]{i:02d}[/bright_black]  "
                    f"[green]{vote_hash}[/green] → [green]{target}[/green]  "
                    f"[bold green]MATCH[/bold green]"
                )
                time.sleep(0.3)
            else:
                console.print(
                    f"  [bright_black]{i:02d}[/bright_black]  "
                    f"[red]{vote_hash}[/red] → [red]{target}[/red]  "
                    f"[bold red]MISMATCH[/bold red]"
                )
                err(f"Tamper detected at record index {i}.")
                err("Database integrity compromised — aborting.")
                all_ok = False

        return all_ok

    def verify_security_seal(self, votes: List[Vote]):
        records = self.database.get_records()
        fake_progress("Verifying security seal", steps=15, delay=0.02)
        for i in range(len(votes)):
            if records[i].voter == "[SECURITY-SEAL]":
                if votes[i].score != 0:
                    err(f"Malformed security seal at index {i}.")
                    err("Database integrity compromised — aborting.")
                    return False
                ok(f"Security seal at index {i} → [bold bright_green]VALID[/bold bright_green]")
        if records[-1].voter != "[SECURITY-SEAL]":
            err("No seal found at end of database — aborting.")
            return False
        return True

    def count_votes(self, votes: List[Vote]):
        result = {p: [] for p in self.participants}
        records = self.database.get_records()
        for record, vote in zip(records, votes):
            if record.votee in self.participants:
                result[record.votee].append(vote.score)
        return result

    def present_results(self, results: Dict[str, List[int]]):
        console.print()
        rule("FINAL RESULTS")
        console.print()

        # Build a rich table sorted by total score descending
        sorted_results = sorted(results.items(), key=lambda x: sum(x[1]), reverse=True)
        max_score = max(sum(v) for _, v in sorted_results) if sorted_results else 1

        table = Table(
            box=box.SIMPLE_HEAVY,
            border_style="green",
            show_header=True,
            header_style="bold green",
        )
        table.add_column("#", justify="right", style="bright_black", width=3)
        table.add_column("Couple", style="bold white")
        table.add_column("Score", justify="center", style="bold bright_green", width=7)
        table.add_column("Votes", justify="center", style="dim green", width=7)
        table.add_column("", style="green")

        for rank, (votee, scores) in enumerate(sorted_results):
            total = sum(scores)
            bar_w = int(total / max_score * 20) if max_score else 0
            bar = "█" * bar_w + "░" * (20 - bar_w)
            table.add_row(
                str(rank + 1),
                f"{votee}",
                str(total),
                str(len(scores)),
                bar,
            )

        console.print(table)
        winner, winner_scores = sorted_results[0]
        console.print(
            Panel(
                f"[bold bright_green] WINNER:  {winner}  —  {sum(winner_scores)} pts[/bold bright_green]",
                border_style="bright_green",
                expand=False,
            )
        )
        console.print()
        time.sleep(3)
        typewrite("Congratulations!")
        console.input()


# ─── MAIN MENU ────────────────────────────────────────────────────────────────


class MainMenu:
    def __init__(self):
        show_banner()
        typewrite("  Initializing secure voting subsystem...", delay=0.022)
        fake_progress("Loading cryptographic modules", steps=20, delay=0.015)
        self.database = VoteDatabase(DB_FILE)
        ok(f"Database connected → [dim]{DB_FILE}[/dim]")
        console.print()
        self.participants = PARTICIPANTS

    def run(self):
        while True:
            rule("MAIN MENU")
            console.print()

            table = Table(box=box.MINIMAL, show_header=False, padding=(0, 2))
            table.add_column("key", style="bold green", width=4)
            table.add_column("desc", style="white")

            for i, p in enumerate(self.participants, 1):
                table.add_row(f"[{i}]", f"Vote for  {p}")
            maxoption = len(self.participants) + 2
            table.add_row(f"[{maxoption-1}]", "Final count  [dim]← decrypt & reveal results[/dim]")
            table.add_row(f"[{maxoption}]", "Exit")

            console.print(table)
            console.print()

            while True:
                raw = console.input("  [green]>>>[/green] ")
                try:
                    option = int(raw)
                    if 1 <= option <= maxoption:
                        break
                except ValueError:
                    pass
                warn(f"Enter a number between 1 and {maxoption}.")

            console.print()

            if option < maxoption - 1:
                console.print("  Initiating vote...")
                time.sleep(2)
                votee = self.participants[option - 1]
                voting = VotingCli(self.database, self.participants, votee)
                voting.run()
            elif option == maxoption - 1:
                console.print("  Initiating vote reveal...")
                time.sleep(2)
                reveal = RevealCli(self.database, self.participants)
                reveal.run()
            else:
                typewrite("  Terminating session. Goodbye.", style="dim green", delay=0.03)
                break


if __name__ == "__main__":
    app = MainMenu()
    app.run()