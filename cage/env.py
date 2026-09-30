"""DojoEnv: CAGE Challenge 2 (CybORG 2.1) wrapped as a text-in / text-out env.

Observation -> compact text table. Actions -> stable string names.
The whole point is that an LLM can read the obs and name an action.
"""
import inspect
import random
from collections import OrderedDict

import numpy as np

from CybORG import CybORG
from CybORG.Agents import RedMeanderAgent, B_lineAgent, SleepAgent
from CybORG.Agents.Wrappers.BlueTableWrapper import BlueTableWrapper
from CybORG.Agents.Wrappers.EnumActionWrapper import EnumActionWrapper

SCENARIO = str(inspect.getfile(CybORG))[:-10] + '/Shared/Scenarios/Scenario2.yaml'

RED_AGENTS = {
    'meander': RedMeanderAgent,   # the "new task"
    'bline': B_lineAgent,
    'sleep': SleepAgent,
}

# Seed policy: practice may only use 1-20, eval only 100-104. Enforced here
# so no amount of prompt drift can leak an eval seed into practice.
PRACTICE_SEEDS = list(range(1, 21))
EVAL_SEEDS = [100, 101, 102, 103, 104]


class DojoEnv:
    def __init__(self, red='meander', max_steps=30):
        if red not in RED_AGENTS:
            raise ValueError(f'unknown red agent {red!r}')
        self.red = red
        self.max_steps = max_steps
        self._cyborg = None
        self._env = None
        self._actions = OrderedDict()   # name -> Action object
        self.step_count = 0
        self.total_reward = 0.0

    # -- lifecycle ---------------------------------------------------------
    def reset(self, seed):
        # CybORG leans on the global RNG, so seed everything it could touch.
        random.seed(seed)
        np.random.seed(seed % (2**32))
        self._cyborg = CybORG(SCENARIO, 'sim', agents={'Red': RED_AGENTS[self.red]})
        self._cyborg.set_seed(seed)
        self._env = BlueTableWrapper(self._cyborg, output_mode='table')
        result = self._env.reset(agent='Blue')
        self._build_actions()
        self.step_count = 0
        self.total_reward = 0.0
        return self._obs_text(result.observation)

    def _build_actions(self):
        space = self._cyborg.get_action_space('Blue')
        enum = EnumActionWrapper(env=self._cyborg)
        enum.action_space_change(space)
        self._actions = OrderedDict((str(a), a) for a in enum.possible_actions)

    # -- stepping ----------------------------------------------------------
    def step(self, action_name):
        """action_name must be one of action_names(). Raises on invalid."""
        action = self.resolve(action_name)
        if action is None:
            raise ValueError(f'invalid action {action_name!r}')
        result = self._env.step(agent='Blue', action=action)
        reward = float(result.reward)
        self.step_count += 1
        self.total_reward += reward
        done = self.step_count >= self.max_steps
        return self._obs_text(result.observation), reward, done, {
            'step': self.step_count,
            'action': str(action),
            'total_reward': self.total_reward,
        }

    def resolve(self, name):
        """Tolerant lookup: exact, then case/space-insensitive."""
        if name in self._actions:
            return self._actions[name]
        key = ' '.join(str(name).split()).lower()
        for k, v in self._actions.items():
            if k.lower() == key:
                return v
        return None

    # -- text views --------------------------------------------------------
    @staticmethod
    def _obs_text(obs):
        return str(obs)

    def action_names(self):
        return list(self._actions)

    def hosts(self):
        return list(self._cyborg.get_action_space('Blue')['hostname'])

    def action_menu(self):
        """Compact grouped menu -- 145 actions in ~12 lines instead of 145."""
        hosts = self.hosts()
        verbs = []
        for name in self._actions:
            verb = name.split(' ')[0]
            if verb not in verbs:
                verbs.append(verb)
        lines = [f'HOSTS: {", ".join(hosts)}', 'ACTIONS (write exactly "Verb Host", or a bare verb where noted):']
        for verb in verbs:
            targeted = any(n.startswith(verb + ' ') for n in self._actions)
            lines.append(f'  {verb} <host>' if targeted else f'  {verb}')
        return '\n'.join(lines)
