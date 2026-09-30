"""The student: an LLM blue defender that reads its notes before acting.

"Learning" here is nothing but accumulated written notes. Same weights every
time; the only thing that changes between conditions is what is in notes.md.
"""
import os
import re
import sys

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from dojo.llm import chat, STUDENT_MODEL

NOTES_PATH = "/Users/hanavmodasiya/trainme/notes/notes.md"

SYSTEM = """You are the Blue defender in CAGE Challenge 2, a network-defence simulation.

The network has three subnets: a User subnet (User0-4), an Enterprise subnet
(Enterprise0-2, Defender) and an Operational subnet (Op_Host0-2, Op_Server0).
A Red attacker starts on User0 and works toward Op_Server0.

Every step you get a table with one row per host: Activity (None / Scan /
Exploit) and Compromised (No / Unknown / User / Privileged).

Scoring: your score is a sum of NEGATIVE penalties, so 0 is perfect and more
negative is worse. You lose points continuously while hosts are compromised
(Op_Server0 and the Enterprise hosts cost far more than User hosts), and you
also pay a smaller one-off cost for disruptive actions like Restore.

Reply in EXACTLY this format and nothing else:
ACTION: <one action, copied exactly from the action list>
WHY: <one short line>"""


def load_notes(path=NOTES_PATH):
    if path and os.path.exists(path):
        return open(path).read().strip()
    return ""


class BlueAgent:
    """Picks one action per step. Optionally reads a notes file first."""

    def __init__(self, notes="", model=None, name="agent"):
        self.notes = notes or ""
        self.model = model or STUDENT_MODEL
        self.name = name
        self.invalid_picks = 0

    # -- prompt ------------------------------------------------------------
    def _prompt(self, env, obs_text, history, step, hint):
        parts = []
        if self.notes:
            parts.append("=== YOUR NOTES (lessons you have written down) ===\n"
                         + self.notes)
        parts.append("=== ACTION LIST ===\n" + env.action_menu())
        parts.append(f"=== STEP {step + 1} of {env.max_steps} "
                     f"(score so far: {env.total_reward:.1f}) ===")
        if history:
            recent = history[-6:]
            lines = [f"  step {h['step']}: {h['action']}  -> reward {h['reward']:.1f}"
                     for h in recent]
            parts.append("=== YOUR RECENT ACTIONS ===\n" + "\n".join(lines))
        parts.append("=== CURRENT NETWORK STATE ===\n" + obs_text)
        if hint:
            parts.append("=== TEACHER HINT (paid guidance, follow it unless it is clearly wrong) ===\n"
                         + hint)
        parts.append("Choose your single next action.")
        return "\n\n".join(parts)

    # -- acting ------------------------------------------------------------
    def act(self, env, obs_text, history, step, hint=None, tag="act"):
        user = self._prompt(env, obs_text, history, step, hint)
        last_err = ""
        for attempt in range(3):
            ask = user if not last_err else user + "\n\n!! " + last_err
            try:
                raw = chat(self.model, SYSTEM, ask, max_tokens=120,
                           temperature=0.0 if attempt == 0 else 0.4,
                           tag=f"{tag}:{self.name}")
            except Exception as e:
                last_err = f"error {type(e).__name__}, try again"
                continue
            action, why = _parse(raw)
            if action and env.resolve(action) is not None:
                return _canon(env, action), why
            self.invalid_picks += 1
            last_err = (f"{action!r} is not a valid action. Copy one exactly from "
                        f"the ACTION LIST, e.g. 'Restore Enterprise0' or 'Monitor'.")
        # Give up gracefully rather than crashing an episode.
        return "Monitor", "fallback: could not produce a valid action"


def _canon(env, action):
    """Return the action name as the env spells it."""
    for name in env.action_names():
        if name.lower() == " ".join(action.split()).lower():
            return name
    return action


def _parse(raw):
    action, why = "", ""
    for line in (raw or "").splitlines():
        line = line.strip().lstrip("*# ").strip()
        m = re.match(r"(?i)^action\s*[:\-]\s*(.+)$", line)
        if m and not action:
            action = m.group(1).strip().strip("`\"'*")
        m = re.match(r"(?i)^why\s*[:\-]\s*(.+)$", line)
        if m and not why:
            why = m.group(1).strip()
    if not action:
        # Model ignored the format; take the first non-empty line.
        for line in (raw or "").splitlines():
            if line.strip():
                action = line.strip().strip("`\"'*")
                break
    return action, why or "(no reason given)"
