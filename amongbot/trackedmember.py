import asyncio


class TrackedMember:
    def __init__(self, member, presence, *, dead=False, mute=False, ignore=False):
        self.member = member
        self.presence = presence
        self.dead = dead
        self._mute = mute
        self.ignore = ignore
        self.mute_lock = asyncio.Lock()

    @property
    def mute(self):
        return self._mute

    async def set_mute(self, mute_state):
        async with self.mute_lock:
            if not self.ignore and self.is_in_vc:
                if self.dead:
                    self._mute = True
                else:
                    self._mute = mute_state
                if self.member.voice.mute != self._mute:
                    await self.member.edit(mute=self._mute)

    @property
    def state(self):
        if self.is_in_vc:
            if self.ignore:
                return "IGNORED"
            elif self.dead:
                return "DEAD"
            elif self.mute:
                return "MUTED"
            else:
                return "ALIVE"
        else:
            return "AWAY"

    @property
    def is_in_vc(self):
        if self.member.voice and self.member.voice.channel == self.presence.voice_channel:
            return True
        else:
            return False
