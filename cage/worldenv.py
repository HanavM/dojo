"""The mutable environment surface an LLM world model writes to.

DojoEnv is fixed. WorldEnv takes an EnvConfig -- a small JSON-shaped object --
and builds whatever world that describes, by patching the Scenario2 YAML and
filtering the action list. Everything here is data, not code, so a model can
emit a config and get a new world.
"""
import copy
import inspect
import os
import random
import tempfile

import numpy as np
import yaml

from CybORG import CybORG
from CybORG.Agents import RedMeanderAgent, B_lineAgent, GreenAgent, SleepAgent
from CybORG.Agents.Wrappers.BlueTableWrapper import BlueTableWrapper
from CybORG.Agents.Wrappers.EnumActionWrapper import EnumActionWrapper

BASE_SCENARIO = str(inspect.getfile(CybORG))[:-10] + "/Shared/Scenarios/Scenario2.yaml"

RED_AGENTS = {"meander": RedMeanderAgent, "bline": B_lineAgent, "sleep": SleepAgent}
VALUES = ("None", "Low", "Medium", "High")

# What each machine is worth in stock Scenario2. Setting a host to the value it
# already has is a no-op that silently wastes an iteration.
STOCK_VALUES = {
    "Defender":    {"conf": "None",   "avail": "None"},
    "Enterprise0": {"conf": "Medium", "avail": "Medium"},
    "Enterprise1": {"conf": "Medium", "avail": "Medium"},
    "Enterprise2": {"conf": "Medium", "avail": "Medium"},
    "Op_Host0":    {"conf": "None",   "avail": "None"},
    "Op_Host1":    {"conf": "None",   "avail": "None"},
    "Op_Host2":    {"conf": "None",   "avail": "None"},
    "Op_Server0":  {"conf": "Medium", "avail": "High"},
    "User0":       {"conf": "None",   "avail": "None"},
    "User1":       {"conf": "None",   "avail": "None"},
    "User2":       {"conf": "None",   "avail": "None"},
    "User3":       {"conf": "None",   "avail": "None"},
    "User4":       {"conf": "None",   "avail": "None"},
}

HOSTS = ["Defender", "Enterprise0", "Enterprise1", "Enterprise2",
         "Op_Host0", "Op_Host1", "Op_Host2", "Op_Server0",
         "User0", "User1", "User2", "User3", "User4"]

VERBS = ["Monitor", "Sleep", "Analyse", "Remove", "Restore", "DecoyApache",
         "DecoyFemitter", "DecoyHarakaSMPT", "DecoySmss", "DecoySSHD",
         "DecoySvchost", "DecoyTomcat", "DecoyVsftpd"]

# Never bannable: without these the episode is unplayable, not merely harder.
PROTECTED_VERBS = {"Monitor", "Sleep", "Restore"}


class ConfigError(ValueError):
    """The world model emitted a config that cannot be built."""


class EnvConfig:
    """Everything a world model is allowed to change. Plain data.

    red           : "meander" | "bline" | "sleep"
    steps         : episode length
    red_start     : LOCKED to User0. Red's starting session is a phishing
                    foothold wired to User0; moving it does not relocate the
                    attacker, it disables it (random floor -210 -> -6). Kept as
                    a field only so old configs still load.
    host_values   : {host: {"conf": "Medium", "avail": "High"}} -- what a machine
                    is worth, i.e. how fast it bleeds points while held
    green_noise   : benign employee traffic that looks like reconnaissance
    banned_actions: DISABLED. Taking tools away trains the agent for a world
                    that will not exist -- in the real task it has every tool.
                    The world gets harder; the agent does not get weaker.
    """

    def __init__(self, red="meander", steps=30, red_start="User0",
                 host_values=None, green_noise=False, banned_actions=None,
                 note=""):
        self.red = red
        self.steps = int(steps)
        self.red_start = red_start
        self.host_values = host_values or {}
        self.green_noise = bool(green_noise)
        self.banned_actions = list(banned_actions or [])
        self.note = note
        self.validate()

    # -- guard rails -------------------------------------------------------
    def validate(self):
        if self.red not in RED_AGENTS:
            raise ConfigError(f"red must be one of {sorted(RED_AGENTS)}, got {self.red!r}")
        if not 5 <= self.steps <= 200:
            raise ConfigError(f"steps must be 5-200, got {self.steps}")
        if self.red_start != "User0":
            raise ConfigError(
                f"red_start is locked to User0, got {self.red_start!r}. Moving "
                f"Red's foothold does not relocate the attacker -- it disables "
                f"it (measured: random floor -210 -> -6). Not a difficulty knob.")
        for host, vals in self.host_values.items():
            if host not in HOSTS:
                raise ConfigError(f"unknown host {host!r}")
            for k, v in vals.items():
                if k not in ("conf", "avail"):
                    raise ConfigError(f"host value key must be conf/avail, got {k!r}")
                if v not in VALUES:
                    raise ConfigError(f"value must be one of {VALUES}, got {v!r}")
                if STOCK_VALUES.get(host, {}).get(k) == v:
                    raise ConfigError(
                        f"{host} {k} is ALREADY {v} in the stock scenario -- that "
                        f"change does nothing. Pick a host whose value actually "
                        f"moves, or a different level.")
        if self.banned_actions:
            raise ConfigError(
                f"banned_actions is disabled (got {self.banned_actions}). Removing "
                f"a tool trains the agent for a world that will not exist -- at "
                f"test time it has every tool. Make the WORLD harder instead: "
                f"red, host_values, green_noise.")
        return self

    def signature(self):
        """Identity of this world, so two rounds cannot serve the same one."""
        return (self.red, self.steps, self.green_noise,
                tuple(sorted((h, tuple(sorted(v.items())))
                             for h, v in self.host_values.items())))

    def to_dict(self):
        return {"red": self.red, "steps": self.steps, "red_start": self.red_start,
                "host_values": self.host_values, "green_noise": self.green_noise,
                "banned_actions": self.banned_actions, "note": self.note}

    def stack(self, patch):
        """Layer a change onto THIS world and return the harder world.

        The old behaviour built each round from a fresh config, so round 3 could
        silently undo round 2 and the curriculum went backwards. Now a round can
        only add pressure: host values ratchet UP, never down, and green noise
        once on stays on.
        """
        patch = dict(patch or {})
        red = patch.get("red", self.red)
        # Red only escalates: meander -> bline, never back.
        if self.red == "bline":
            red = "bline"

        hv = {h: dict(v) for h, v in self.host_values.items()}
        for host, vals in (patch.get("host_values") or {}).items():
            cur = hv.setdefault(host, {})
            for k, v in vals.items():
                base = cur.get(k, STOCK_VALUES.get(host, {}).get(k, "None"))
                # ratchet: keep whichever is worth more
                if VALUES.index(v) > VALUES.index(base):
                    cur[k] = v
            if not cur:
                hv.pop(host, None)

        return EnvConfig(
            red=red,
            steps=patch.get("steps", self.steps),
            host_values=hv,
            green_noise=self.green_noise or bool(patch.get("green_noise")),
            note=patch.get("note", ""),
        )

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        d.pop("difficulty", None)
        return cls(**{k: v for k, v in d.items()
                      if k in ("red", "steps", "red_start", "host_values",
                               "green_noise", "banned_actions", "note")})

    def describe(self):
        bits = [f"red={self.red}", f"steps={self.steps}"]
        if self.green_noise:
            bits.append("benign traffic ON")
        if self.banned_actions:
            bits.append("banned: " + ",".join(self.banned_actions))
        if self.host_values:
            bits.append("revalued: " + ",".join(
                f"{h}({v.get('conf','-')}/{v.get('avail','-')})"
                for h, v in self.host_values.items()))
        return "; ".join(bits)


def build_scenario(cfg, out_dir=None):
    """Write a patched Scenario2 YAML for this config. Returns its path."""
    with open(BASE_SCENARIO) as f:
        sc = yaml.safe_load(f)

    # where Red gets its foothold
    red = sc["Agents"]["Red"]
    for sess in red.get("starting_sessions", []):
        sess["hostname"] = cfg.red_start

    # benign employee traffic: off in stock Scenario2 (green is a SleepAgent)
    if cfg.green_noise:
        sc["Agents"]["Green"]["agent_type"] = "GreenAgent"

    # what each machine is worth
    for host, vals in cfg.host_values.items():
        entry = sc["Hosts"].setdefault(host, {})
        if "conf" in vals:
            entry["ConfidentialityValue"] = vals["conf"]
        if "avail" in vals:
            entry["AvailabilityValue"] = vals["avail"]

    out_dir = out_dir or tempfile.mkdtemp(prefix="dojo_scenario_")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "scenario.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(sc, f, sort_keys=False)
    return path


class WorldEnv:
    """Same interface as DojoEnv, but the world itself is a parameter."""

    def __init__(self, cfg=None):
        self.cfg = cfg or EnvConfig()
        self.max_steps = self.cfg.steps
        self._scenario = build_scenario(self.cfg)
        self._cyborg = None
        self._env = None
        self._actions = {}
        self.step_count = 0
        self.total_reward = 0.0

    def reset(self, seed):
        random.seed(seed)
        np.random.seed(seed % (2 ** 32))
        agents = {"Red": RED_AGENTS[self.cfg.red]}
        if self.cfg.green_noise:
            agents["Green"] = GreenAgent
        self._cyborg = CybORG(self._scenario, "sim", agents=agents)
        self._cyborg.set_seed(seed)
        self._env = BlueTableWrapper(self._cyborg, output_mode="table")
        result = self._env.reset(agent="Blue")
        self._build_actions()
        self.step_count = 0
        self.total_reward = 0.0
        return str(result.observation)

    def _build_actions(self):
        space = self._cyborg.get_action_space("Blue")
        enum = EnumActionWrapper(env=self._cyborg)
        enum.action_space_change(space)
        banned = set(self.cfg.banned_actions)
        self._actions = {
            str(a): a for a in enum.possible_actions
            if str(a).split(" ")[0] not in banned
        }
        if not self._actions:
            raise ConfigError("every action was banned; nothing is playable")

    def step(self, action_name):
        action = self.resolve(action_name)
        if action is None:
            raise ValueError(f"invalid action {action_name!r}")
        result = self._env.step(agent="Blue", action=action)
        reward = float(result.reward)
        self.step_count += 1
        self.total_reward += reward
        done = self.step_count >= self.max_steps
        return str(result.observation), reward, done, {
            "step": self.step_count, "action": str(action),
            "total_reward": self.total_reward,
        }

    def resolve(self, name):
        if name in self._actions:
            return self._actions[name]
        key = " ".join(str(name).split()).lower()
        for k, v in self._actions.items():
            if k.lower() == key:
                return v
        return None

    def action_names(self):
        return list(self._actions)

    def hosts(self):
        return list(self._cyborg.get_action_space("Blue")["hostname"])

    def action_menu(self):
        verbs = []
        for name in self._actions:
            v = name.split(" ")[0]
            if v not in verbs:
                verbs.append(v)
        lines = [f"HOSTS: {', '.join(self.hosts())}",
                 'ACTIONS (write exactly "Verb Host", or a bare verb where noted):']
        for v in verbs:
            targeted = any(n.startswith(v + " ") for n in self._actions)
            lines.append(f"  {v} <host>" if targeted else f"  {v}")
        if self.cfg.banned_actions:
            lines.append("  (unavailable this episode: "
                         + ", ".join(self.cfg.banned_actions) + ")")
        return "\n".join(lines)
