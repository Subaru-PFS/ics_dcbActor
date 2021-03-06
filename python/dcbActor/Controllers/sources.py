__author__ = 'alefur'

import logging
import time

import enuActor.utils.bufferedSocket as bufferedSocket
from dcbActor.Simulators.sources import SourcesSim
from dcbActor.utils.lampState import LampState
from enuActor.utils.fsmThread import FSMThread


class sources(FSMThread, bufferedSocket.EthComm):
    warmingTimes = dict(hgar=15, neon=15, xenon=15, krypton=15, argon=15, qth=60, halogen=60)

    def __init__(self, actor, name, loglevel=logging.DEBUG):
        """This sets up the connections to/from the hub, the logger, and the twisted reactor.

        :param actor: enuActor.
        :param name: controller name.
        :type name: str
        """
        substates = ['IDLE', 'WARMING', 'TRIGGERING', 'FAILED']
        events = [{'name': 'warming', 'src': 'IDLE', 'dst': 'WARMING'},
                  {'name': 'triggering', 'src': 'IDLE', 'dst': 'TRIGGERING'},
                  {'name': 'idle', 'src': ['WARMING', 'TRIGGERING', ], 'dst': 'IDLE'},
                  {'name': 'fail', 'src': ['WARMING', 'TRIGGERING', ], 'dst': 'FAILED'},
                  ]

        FSMThread.__init__(self, actor, name, events=events, substates=substates, doInit=True)

        self.addStateCB('WARMING', self.warmup)
        self.addStateCB('TRIGGERING', self.doGo)
        self.sim = SourcesSim()

        self.monitor = 0
        self.abortWarmup = False
        self.config = dict()
        self.outletConfig = dict()
        self.lampStates = dict()

        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(loglevel)

    @property
    def simulated(self):
        """Return True if self.mode=='simulation', return False if self.mode='operation'."""
        if self.mode == 'simulation':
            return True
        elif self.mode == 'operation':
            return False
        else:
            raise ValueError('unknown mode')

    @property
    def lampNames(self):
        return list(self.outletConfig.values())

    @property
    def sourcesOn(self):
        return [lamp for lamp in self.lampNames if self.lampStates[lamp].lampOn]

    def _loadCfg(self, cmd, mode=None):
        """Load sources configuration.

        :param cmd: current command.
        :param mode: operation|simulation, loaded from config file if None.
        :type mode: str
        :raise: Exception if config file is badly formatted.
        """
        self.mode = self.actor.config.get('sources', 'mode') if mode is None else mode

        bufferedSocket.EthComm.__init__(self,
                                        host=self.actor.config.get('sources', 'host'),
                                        port=int(self.actor.config.get('sources', 'port')),
                                        EOL='\r\n')

    def _openComm(self, cmd):
        """Open socket with sources controller or simulate it.

        :param cmd: current command.
        :raise: socket.error if the communication has failed.
        """
        self.ioBuffer = bufferedSocket.BufferedSocket(self.name + 'IO', EOL='tcpover\n')
        s = self.connectSock()

    def _closeComm(self, cmd):
        """Close socket.

        :param cmd: current command.
        """
        self.closeSock()

    def _testComm(self, cmd):
        """Test communication.

        :param cmd: current command.
        :raise: Exception if the communication has failed with the controller.
        """
        self.getOutletsConfig(cmd)

    def _init(self, cmd):
        """Instanciate lampState for each lamp and switch them off by safety."""

        for lamp in self.lampNames:
            self.lampStates[lamp] = LampState()

        self.switchOff(cmd, self.lampNames)

    def getStatus(self, cmd):
        """Get all ports status.

        :param cmd: current command.
        :raise: Exception with warning message.
        """
        states = self.sendOneCommand('getState', cmd=cmd, doClose=True)
        self.genAllKeys(cmd, states)

    def genKeys(self, cmd, lampState, genTimeStamp=False):
        """ Generate one lamp keywords.

        :param cmd: current command.
        :param lampState: single lamp state
        :raise: Exception with warning message.
        """
        lamp, state = [r.strip() for r in lampState.split('=')]
        self.lampStates[lamp].setState(state, genTimeStamp=genTimeStamp)

        cmd.inform(f'{lamp}={str(self.lampStates[lamp])}')

    def genAllKeys(self, cmd, states, genTimeStamp=False):
        """ Generate all lamps keywords.

        :param cmd: current command.
        :param states: all lamp states
        :raise: Exception with warning message.
        """
        for lampState in states.split(','):
            self.genKeys(cmd, lampState, genTimeStamp=genTimeStamp)

    def getOutletsConfig(self, cmd):
        """Get all ports status.

        :param cmd: current command.
        :raise: Exception with warning message.
        """
        outlets = self.sendOneCommand('getOutletsConfig', cmd=cmd, doClose=True)

        for ret in outlets.split(','):
            cmd.inform(ret)
            outlet, lamp = [r.strip() for r in ret.split('=')]
            self.outletConfig[outlet] = lamp

        cmd.inform(f'lampNames={",".join(self.lampNames)}')
        return self.lampNames

    def warmup(self, cmd, lamps, warmingTime=None):
        """warm up lamps list

        :param cmd: current command.
        :param lamps: ['hgar', 'neon']
        :type lamps: list.
        :raise: Exception with warning message.
        """
        self.abortWarmup = False

        for lamp in lamps:
            if lamp not in self.sourcesOn:
                lampState = self.sendOneCommand(f'switch {lamp} on', doClose=True, cmd=cmd)
                self.genKeys(cmd, lampState, genTimeStamp=True)

        toBeWarmed = lamps if lamps else self.sourcesOn
        warmingTimes = [sources.warmingTimes[lamp] for lamp in toBeWarmed] if warmingTime is None else len(toBeWarmed) * [warmingTime]
        remainingTimes = [t - self.lampStates[lamp].elapsed() for t, lamp in zip(warmingTimes, toBeWarmed)]

        sleepTime = max(remainingTimes) if remainingTimes else 0

        if sleepTime > 0:
            cmd.inform(f'text="warmingTime:{max(warmingTimes)} secs now sleeping for {sleepTime}'"")
            self.wait(time.time() + sleepTime)

    def switchOff(self, cmd, lamps):
        """Switch off lamp list.

        :param cmd: current command.
        :param lamps: ['hgar', 'neon']
        :type lamps: list.
        :raise: Exception with warning message.
        """
        for lamp in lamps:
            lampState = self.sendOneCommand(f'switch {lamp} off', doClose=True, cmd=cmd)
            self.genKeys(cmd, lampState, genTimeStamp=True)

    def prepare(self, cmd):
        """Configure a future illumination sequence.

        :param cmd: current command.
        :raise: Exception with warning message.
        """
        cmdStr = f'prepare {" ".join(sum([[lamp, str(time)] for lamp, time in self.config.items()], []))}'
        return self.sendOneCommand(cmdStr, doClose=True, cmd=cmd)

    def doGo(self, cmd):
        """Run the preconfigured illumination sequence.

        :param cmd: current command.
        :raise: Exception with warning message.
        """
        timeout = max(self.config.values()) + 2
        timeLim = time.time() + timeout + 10
        replies = bufferedSocket.EthComm.sendOneCommand(self, cmdStr='go', cmd=cmd).split('\n')
        states = replies[-1]

        for reply in replies[:len(replies) - 1]:
            cmd.inform(f'text="{reply}"')

        self.genAllKeys(cmd, states)

        reply = self.getOneResponse(cmd=cmd, timeout=timeout)

        while ';;' not in reply:
            if reply:
                self.genKeys(cmd, reply, genTimeStamp=True)

            reply = self.getOneResponse(cmd=cmd, timeout=timeout)
            if time.time() > timeLim:
                raise TimeoutError('lamps has not been triggered correctly')

        status, ret = reply.split(';;')

        if status != 'OK':
            raise RuntimeError(ret)

        self.genAllKeys(cmd, states)

        self._closeComm(cmd)

    def wait(self, end, ti=0.01):
        """ Wait until time.time() >end.

        :param end: nb of secs since epoch.
        """
        while time.time() < end:
            time.sleep(ti)
            self.handleTimeout()
            if self.abortWarmup:
                raise UserWarning('sources warmup aborted')

    def doAbort(self):
        """Abort warmup.
        """
        self.abortWarmup = True
        while self.currCmd:
            pass
        return

    def sendOneCommand(self, cmdStr, doClose=False, cmd=None):
        """Send one command and return one response.

        :param cmdStr: string to send.
        :param doClose: If True (the default), the device socket is closed before returning.
        :param cmd: current command.
        :return: reply : the single response string, with EOLs stripped.
        :raise: IOError : from any communication errors.
        """
        reply = bufferedSocket.EthComm.sendOneCommand(self, cmdStr=cmdStr, doClose=doClose, cmd=cmd)
        status, ret = reply.split(';;')

        if status != 'OK':
            raise RuntimeError(ret)

        return ret

    def createSock(self):
        """Create socket in operation, simulator otherwise.
        """
        if self.simulated:
            s = self.sim
        else:
            s = bufferedSocket.EthComm.createSock(self)

        return s

    def leaveCleanly(self, cmd):
        """Clear and leave.

        :param cmd: current command.
        """
        self.monitor = 0
        self.doAbort()

        try:
            self.switchOff(cmd, self.lampNames)
            self.getStatus(cmd)
        except Exception as e:
            cmd.warn('text=%s' % self.actor.strTraceback(e))

        self._closeComm(cmd=cmd)
