#!/usr/bin/env python

__author__ = "Carlos Rueda"
__license__ = 'Apache 2.0'

from ion.services.mi.drivers.uw_bars.test import WithSimulatorTestCase
from ion.services.mi.drivers.uw_bars.driver import BarsInstrumentDriver
from ion.services.mi.drivers.uw_bars.common import BarsChannel

from ion.services.mi.instrument_driver import DriverState
from ion.services.mi.common import InstErrorCode

class DriverTest(WithSimulatorTestCase):

    def test(self):
        """
        Tests driver initialization, configuration, connection
        """

        driver = BarsInstrumentDriver()

        self.assertEqual(DriverState.UNCONFIGURED, driver.get_state())

        # initialize
        success, result = driver.initialize()
        self.assertEqual(InstErrorCode.OK, success)
        self.assertEqual(DriverState.UNCONFIGURED, driver.get_state())

        # configure
        configs = {BarsChannel.ALL: self.config}
        success, result = driver.configure(configs)
        self.assertEqual(InstErrorCode.OK, success)
        self.assertEqual(DriverState.DISCONNECTED, driver.get_state())

        # connect
        success, result = driver.connect([BarsChannel.ALL])
        self.assertEqual(InstErrorCode.OK, success)
        self.assertEqual(DriverState.CONNECTING, driver.get_state())

