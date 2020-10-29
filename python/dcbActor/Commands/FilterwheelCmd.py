#!/usr/bin/env python

import opscore.protocols.keys as keys
import opscore.protocols.types as types
from enuActor.utils.wrap import threaded, blocking


class FilterwheelCmd(object):
    def __init__(self, actor):
        # This lets us access the rest of the actor.
        self.actor = actor

        # Declare the commands we implement. When the actor is started
        # these are registered with the parser, which will call the
        # associated methods when matched. The callbacks will be
        # passed a single argument, the parsed and typed command.
        #
        self.vocab = [
            ('filterwheel', 'status', self.status),
            ('set', '@(<linewheel>|<qthwheel>)', self.moveWheel),
            ('init', '@(linewheel|qthwheel)', self.initWheel),
            ('adc', 'calib', self.adcCalib)

        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("dcb__filterwheel", (1, 1),
                                        keys.Key('linewheel', types.String(), help='line wheel position (1-5)'),
                                        keys.Key('qthwheel', types.String(), help='qth wheel position (1-5)'),
                                        )

    @property
    def controller(self):
        try:
            return self.actor.controllers['filterwheel']
        except KeyError:
            raise RuntimeError('filterwheel controller is not connected.')

    @threaded
    def status(self, cmd):
        """Report state, mode, status."""
        self.controller.generate(cmd)

    @blocking
    def moveWheel(self, cmd):
        """set linewheel to required position."""
        cmdKeys = cmd.cmd.keywords
        if 'linewheel' in cmdKeys:
            wheel = 'linewheel'
            holeDict = self.controller.lineHoles
        else:
            wheel = 'qthwheel'
            holeDict = self.controller.qthHoles

        hole = cmdKeys[wheel].values[0]
        hole = '{:.1f}'.format(float(hole)) if hole !='none' else hole
        revHoleDict = dict([(v,k) for k,v in holeDict.items()])

        if hole not in revHoleDict.keys():
            possibleHoles = ",".join([str(key) for key in revHoleDict.keys()])
            raise ValueError(f'unknown hole:{hole}, existing are {possibleHoles}')

        position = revHoleDict[hole]
        self.controller.moving(wheel=wheel, position=position, cmd=cmd)
        self.controller.generate(cmd)

    @blocking
    def initWheel(self, cmd):
        """set linewheel to required position."""
        cmdKeys = cmd.cmd.keywords
        wheel = 'linewheel' if 'linewheel' in cmdKeys else 'qthwheel'

        self.controller.initWheel(wheel=wheel, cmd=cmd)
        self.controller.generate(cmd)

    @blocking
    def adcCalib(self, cmd):
        """set linewheel to required position."""
        cmdKeys = cmd.cmd.keywords
        wheel = 'linewheel' if 'linewheel' in cmdKeys else 'qthwheel'

        self.controller.adcCalib(cmd=cmd)
        self.controller.generate(cmd)
