#!/usr/bin/env python

"""
@package ion.agents.platform.rsn.rsn_platform_driver
@file    ion/agents/platform/rsn/rsn_platform_driver.py
@author  Carlos Rueda
@brief   The main RSN OMS platform driver class.
"""

__author__ = 'Carlos Rueda'
__license__ = 'Apache 2.0'


from pyon.public import log, CFG
import logging

from copy import deepcopy

from ion.agents.platform.platform_driver import PlatformDriver
from ion.agents.platform.platform_driver import PlatformDriverState
from ion.agents.platform.platform_driver import PlatformDriverEvent
from ion.agents.platform.util.network import InstrumentNode
from ion.agents.platform.exceptions import PlatformException
from ion.agents.platform.exceptions import PlatformDriverException
from ion.agents.platform.exceptions import PlatformConnectionException
from ion.agents.platform.rsn.oms_client_factory import CIOMSClientFactory
from ion.agents.platform.responses import NormalResponse, InvalidResponse

from ion.agents.platform.util import ion_ts_2_ntp

from pyon.agent.common import BaseEnum
from pyon.agent.instrument_fsm import FSMError


class RSNPlatformDriverState(PlatformDriverState):
    """
    We simply inherit the states from the superclass
    """
    pass


class RSNPlatformDriverEvent(PlatformDriverEvent):
    """
    The ones for superclass plus a few others for the CONNECTED state.
    """
    CONNECT_INSTRUMENT        = 'RSN_PLATFORM_DRIVER_CONNECT_INSTRUMENT'
    DISCONNECT_INSTRUMENT     = 'RSN_PLATFORM_DRIVER_DISCONNECT_INSTRUMENT'
    TURN_ON_PORT              = 'RSN_PLATFORM_DRIVER_TURN_ON_PORT'
    TURN_OFF_PORT             = 'RSN_PLATFORM_DRIVER_TURN_OFF_PORT'
    CHECK_SYNC                = 'RSN_PLATFORM_DRIVER_CHECK_SYNC'


class RSNPlatformDriverCapability(BaseEnum):
    CONNECT_INSTRUMENT        = RSNPlatformDriverEvent.CONNECT_INSTRUMENT
    DISCONNECT_INSTRUMENT     = RSNPlatformDriverEvent.DISCONNECT_INSTRUMENT
    TURN_ON_PORT              = RSNPlatformDriverEvent.TURN_ON_PORT
    TURN_OFF_PORT             = RSNPlatformDriverEvent.TURN_OFF_PORT
    CHECK_SYNC                = RSNPlatformDriverEvent.CHECK_SYNC


class RSNPlatformDriver(PlatformDriver):
    """
    The main RSN OMS platform driver class.
    """

    def __init__(self, pnode, event_callback):
        """
        Creates an RSNPlatformDriver instance.

        @param pnode           Root PlatformNode defining the platform network
                               rooted at this platform.
        @param event_callback  Listener of events generated by this driver
        """
        PlatformDriver.__init__(self, pnode, event_callback)

        # CIOMSClient instance created by connect() and destroyed by disconnect():
        self._rsn_oms = None

        # URL for the event listener registration/unregistration (based on
        # web server launched by ServiceGatewayService, since that's the
        # service in charge of receiving/relaying the OMS events).
        # NOTE: (as proposed long ago), this kind of functionality should
        # actually be provided by some component more in charge of the RSN
        # platform netwokr as a whole -- as opposed to platform-specific).
        self.listener_url = None

    def _filter_capabilities(self, events):
        """
        """
        events_out = [x for x in events if RSNPlatformDriverCapability.has(x)]
        return events_out

    def validate_driver_configuration(self, driver_config):
        """
        Driver config must include 'oms_uri' entry.
        """
        if not 'oms_uri' in driver_config:
            log.error("'oms_uri' not present in driver_config = %s", driver_config)
            raise PlatformDriverException(msg="driver_config does not indicate 'oms_uri'")

    def configure(self, driver_config):
        """
        Nothing special done here, only calls super.configure(driver_config)

        @param driver_config with required 'oms_uri' entry.
        """
        PlatformDriver.configure(self, driver_config)
        self._construct_resource_schema()

    def _construct_resource_schema(self):
        """
        """
        
        parameters = deepcopy(self._param_dict)
        ports_dict = self._driver_config.get('ports',{})
        ports = []
        # remove until network checkpoint needs are defined.
        # port info can be retrieve from active deployment
        #for k,v in ports_dict.iteritems():
        #    ports.append(v['port_id'])
        for k,v in parameters.iteritems():
            read_write = v.get('read_write', None)
            if read_write == 'write':
                v['visibility'] = 'READ_WRITE'
            else:
                v['visibility'] = 'READ_ONLY'
                
        commands = {}
        commands[RSNPlatformDriverEvent.CONNECT_INSTRUMENT] = \
            {
                "display_name" : "Connect Instrument",
                "description" : "Connect an instrument to the platform.",
                "args" : [], 
                "kwargs" : {
                    'port_id' : {
                        "required" : True,
                        "type" : "int",
                        "valid_values" : ports
                        },
                    'instrument_id' : {
                        "required" : True,
                        "type" : "str"
                        },
                    'attributes' : {
                        "required" : True,
                        "type" : "dict"
                        }                    
                }
            }
        commands[RSNPlatformDriverEvent.DISCONNECT_INSTRUMENT] = \
            {
                "display_name" : "Disconnect Instrument",
                "description" : "Disconnect an instrument from the platform.",
                "args" : [], 
                "kwargs" : {
                    'port_id' : {
                        "required" : True,
                        "type" : "int",
                        "valid_values" : ports
                        },
                    'instrument_id' : {
                        "required" : True,
                        "type" : "str"
                        }
                }
            }
        commands[RSNPlatformDriverEvent.TURN_ON_PORT] = \
            {
                "display_name" : "Port Power On",
                "description" : "Activate port power.",
                "args" : [],
                "kwargs" : {
                       'port_id' : {
                            "required" : True,
                            "type" : "int",
                            "valid_values" : ports
                        }
                }
                     
            }
        commands[RSNPlatformDriverEvent.TURN_OFF_PORT] = \
            {
                "display_name" : "Port Power Off",
                "description" : "Deactivate port power.",
                "args" : [],
                "kwargs" : {
                       'port_id' : {
                            "required" : True,
                            "type" : "int",
                            "valid_values" : ports
                        }
                }
            }
        commands[RSNPlatformDriverEvent.CHECK_SYNC] = \
            {
                "display_name" : "Check Platform Hierarchy",
                "description" : "Verify the platform hierarchy is consistent with OMS.",
                "args" : [],
                "kwargs" : {}
            }       
        self._resource_schema['parameters'] = parameters
        self._resource_schema['commands'] = commands
                
    def ping(self):
        """
        Verifies communication with external platform returning "PONG" if
        this verification completes OK.

        @retval "PONG" iff all OK.
        @raise PlatformConnectionException Cannot ping external platform or
               got unexpected response.
        """
        log.debug("%r: pinging OMS...", self._platform_id)
        
        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot ping: _rsn_oms object required (created via connect() call)")
            
        try:
            retval = self._rsn_oms.hello.ping()
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot ping: %s" % str(e))

        if retval is None or retval.upper() != "PONG":
            raise PlatformConnectionException(msg="Unexpected ping response: %r" % retval)

        log.debug("%r: ping completed: response: %s", self._platform_id, retval)

        return "PONG"

    def connect(self):
        """
        Creates an CIOMSClient instance, does a ping to verify connection,
        and starts event dispatch.
        """
        # create CIOMSClient:
        oms_uri = self._driver_config['oms_uri']
        log.debug("%r: creating CIOMSClient instance with oms_uri=%r",
                  self._platform_id, oms_uri)
        self._rsn_oms = CIOMSClientFactory.create_instance(oms_uri)
        log.debug("%r: CIOMSClient instance created: %s",
                  self._platform_id, self._rsn_oms)

        # ping to verify connection:
        self.ping()

        # start event dispatch:
        self._start_event_dispatch()

    def disconnect(self):
        """
        Stops event dispatch and destroys the CIOMSClient instance.
        """
        self._stop_event_dispatch()
        CIOMSClientFactory.destroy_instance(self._rsn_oms)
        self._rsn_oms = None
        log.debug("%r: CIOMSClient instance destroyed", self._platform_id)

    def get_metadata(self):
        """
        """
        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot get_platform_metadata: _rsn_oms object required (created via connect() call)")
            
        try:
            retval = self._rsn_oms.config.get_platform_metadata(self._platform_id)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot get_platform_metadata: %s" % str(e))

        log.debug("get_platform_metadata = %s", retval)

        if not self._platform_id in retval:
            raise PlatformException("Unexpected: response does not include "
                                    "requested platform '%s'" % self._platform_id)

        md = retval[self._platform_id]
        return md

    def get_subplatform_ids(self):
        """
        Gets the IDs of my sub-platforms.
        """
        return self._pnode.subplatforms.keys()

    def get_attribute_values(self, attrs):
        """
        """
        log.debug("get_attribute_values: attrs=%s", attrs)

        if not isinstance(attrs, (list, tuple)):
            raise PlatformException('get_attribute_values: attrs argument must be a '
                                    'list [(attrName, from_time), ...]. Given: %s', attrs)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot get_platform_attribute_values: _rsn_oms object required (created via connect() call)")
            
        # convert the ION system time from_time to NTP, as this is the time
        # format used by the RSN OMS interface:
        attrs_ntp = [(attr_id, ion_ts_2_ntp(from_time))
                     for (attr_id, from_time) in attrs]

        try:
            retval = self._rsn_oms.attr.get_platform_attribute_values(self._platform_id,
                                                                      attrs_ntp)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot get_platform_attribute_values: %s" % str(e))

        if not self._platform_id in retval:
            raise PlatformException("Unexpected: response does not include "
                                    "requested platform '%s'" % self._platform_id)

        attr_values = retval[self._platform_id]

        # reported timestamps are already in NTP. Just return the dict:
        return attr_values

    def _validate_set_attribute_values(self, attrs):
        """
        Does some pre-validation of the passed values according to the
        definition of the attributes.

        NOTE: We don't check everything here, just some basics.
        TODO determine appropriate validations at this level.
        Note that the basic checks here follow what the OMS system
        will do if we just send the request directly to it. So,
        need to determine what exactly should be done on the CI side.

        @param attrs

        @return dict of errors for the offending attribute names, if any.
        """
        # TODO determine appropriate validations at this level.

        # get definitions to verify the values against
        attr_defs = self._get_platform_attributes()

        if log.isEnabledFor(logging.DEBUG):
            log.debug("validating passed attributes: %s against defs %s", attrs, attr_defs)

        # to collect errors, if any:
        error_vals = {}
        for attr_name, attr_value in attrs:

            attr_def = attr_defs.get(attr_name, None)

            if log.isEnabledFor(logging.DEBUG):
                log.debug("validating %s against %s", attr_name, str(attr_def))

            if not attr_def:
                error_vals[attr_name] = InvalidResponse.ATTRIBUTE_ID
                log.warn("Attribute %s not in associated platform %s",
                         attr_name, self._platform_id)
                continue

            type_ = attr_def.get('type', None)
            units = attr_def.get('units', None)
            min_val = attr_def.get('min_val', None)
            max_val = attr_def.get('max_val', None)
            read_write = attr_def.get('read_write', None)
            group = attr_def.get('group', None)

            if "write" != read_write:
                error_vals[attr_name] = InvalidResponse.ATTRIBUTE_NOT_WRITABLE
                log.warn(
                    "Trying to set read-only attribute %s in platform %s",
                    attr_name, self._platform_id)
                continue

            #
            # TODO the following value-related checks are minimal
            #
            if type_ in ["float", "int"]:
                if min_val and float(attr_value) < float(min_val):
                    error_vals[attr_name] = InvalidResponse.ATTRIBUTE_VALUE_OUT_OF_RANGE
                    log.warn(
                        "Value %s for attribute %s is less than specified minimum "
                        "value %s in associated platform %s",
                        attr_value, attr_name, min_val,
                        self._platform_id)
                    continue

                if max_val and float(attr_value) > float(max_val):
                    error_vals[attr_name] = InvalidResponse.ATTRIBUTE_VALUE_OUT_OF_RANGE
                    log.warn(
                        "Value %s for attribute %s is greater than specified maximum "
                        "value %s in associated platform %s",
                        attr_value, attr_name, max_val,
                        self._platform_id)
                    continue

        return error_vals

    def set_attribute_values(self, attrs):
        """
        """
        log.debug("set_attribute_values: attrs = %s", attrs)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot set_platform_attribute_values: _rsn_oms object required (created via connect() call)")
            
        error_vals = self._validate_set_attribute_values(attrs)
        if len(error_vals) > 0:
            # remove offending attributes for the request below
            attrs_dict = dict(attrs)
            for bad_attr_name in error_vals:
                del attrs_dict[bad_attr_name]

            # no good attributes at all?
            if len(attrs_dict) == 0:
                # just immediately return with the errors:
                return error_vals

            # else: update attrs with the good attributes:
            attrs = attrs_dict.items()

        # ok, now make the request to RSN OMS:
        try:
            retval = self._rsn_oms.attr.set_platform_attribute_values(self._platform_id,
                                                                      attrs)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot set_platform_attribute_values: %s" % str(e))

        log.debug("set_platform_attribute_values = %s", retval)

        if not self._platform_id in retval:
            raise PlatformException("Unexpected: response does not include "
                                    "requested platform '%s'" % self._platform_id)

        attr_values = retval[self._platform_id]

        # Note that the reported timestamps are in NTP.
        # (Timestamps indicate the time when the value was set for each attribute.)

        # ret_attr_values: dictionary to return, initialized with the error ones
        # determined above, if any:
        ret_attr_values = error_vals

        # add the info returned from RSN OMS:
        for attr_name, attr_val_ts in attr_values.iteritems():
            ret_attr_values[attr_name] = attr_val_ts

        log.debug("set_attribute_values: returning %s", ret_attr_values)

        return ret_attr_values

    def _verify_platform_id_in_response(self, response):
        """
        Verifies the presence of my platform_id in the response.

        @param response Dictionary returned by _rsn_oms

        @retval response[self._platform_id]
        """
        if not self._platform_id in response:
            msg = "unexpected: response does not contain entry for %r" % self._platform_id
            log.error(msg)
            raise PlatformException(msg=msg)

        if response[self._platform_id] == InvalidResponse.PLATFORM_ID:
            msg = "response reports invalid platform_id for %r" % self._platform_id
            log.error(msg)
            raise PlatformException(msg=msg)
        else:
            return response[self._platform_id]

    def _verify_port_id_in_response(self, port_id, dic):
        """
        Verifies the presence of port_id in the dic.

        @param port_id  The ID to verify
        @param dic Dictionary returned by _rsn_oms

        @return dic[port_id]
        """
        if not port_id in dic:
            msg = "unexpected: dic does not contain entry for %r" % port_id
            log.error(msg)
            raise PlatformException(msg=msg)

        if dic[port_id] == InvalidResponse.PORT_ID:
            msg = "%r: response reports invalid port_id for %r" % (
                                 self._platform_id, port_id)
            log.error(msg)
            raise PlatformException(msg=msg)
        else:
            return dic[port_id]

    def _verify_instrument_id_in_response(self, port_id, instrument_id, dic):
        """
        Verifies the presence of instrument_id in the dic.

        @param port_id        Used for error reporting
        @param instrument_id  The ID to verify
        @param dic            Dictionary returned by _rsn_oms

        @return dic[instrument_id]
        """
        if not instrument_id in dic:
            msg = "unexpected: dic does not contain entry for %r" % instrument_id
            log.error(msg)
            raise PlatformException(msg=msg)

        return dic[instrument_id]

    def connect_instrument(self, port_id, instrument_id, attributes):
        log.debug("%r: connect_instrument: port_id=%r instrument_id=%r attributes=%s",
                  self._platform_id, port_id, instrument_id, attributes)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot connect_instrument: _rsn_oms object required (created via connect() call)")

        try:
            response = self._rsn_oms.instr.connect_instrument(self._platform_id,
                                                              port_id,
                                                              instrument_id,
                                                              attributes)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot connect_instrument: %s" % str(e))

        log.debug("%r: connect_instrument response: %s",
                  self._platform_id, response)

        dic_plat = self._verify_platform_id_in_response(response)
        port_dic = self._verify_port_id_in_response(port_id, dic_plat)
        instr_res = self._verify_instrument_id_in_response(port_id, instrument_id, port_dic)

        # update local image if instrument was actually connected in this call:
        if isinstance(instr_res, dict):
            attrs = instr_res
            instrumentNode = InstrumentNode(instrument_id, attrs)
            self._pnode.ports[port_id].add_instrument(instrumentNode)
            log.debug("%r: port_id=%s connect_instrument: local image updated: %s",
                      self._platform_id, port_id, instrument_id)

        return dic_plat  # note: return the dic for the platform

    def disconnect_instrument(self, port_id, instrument_id):
        log.debug("%r: disconnect_instrument: port_id=%r instrument_id=%r",
                  self._platform_id, port_id, instrument_id)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot disconnect_instrument: _rsn_oms object required (created via connect() call)")

        try:
            response = self._rsn_oms.instr.disconnect_instrument(self._platform_id,
                                                                 port_id,
                                                                 instrument_id)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot disconnect_instrument: %s" % str(e))

        log.debug("%r: disconnect_instrument response: %s",
                  self._platform_id, response)

        dic_plat = self._verify_platform_id_in_response(response)
        port_dic = self._verify_port_id_in_response(port_id, dic_plat)
        instr_res = self._verify_instrument_id_in_response(port_id, instrument_id, port_dic)

        # update local image if instrument was actually disconnected in this call:
        if instr_res == NormalResponse.INSTRUMENT_DISCONNECTED:
            del self._pnode.ports[port_id].instruments[instrument_id]
            log.debug("%r: port_id=%s disconnect_instrument: local image updated: %s",
                      self._platform_id, port_id, instrument_id)

        return dic_plat  # note: return the dic for the platform

    def get_connected_instruments(self, port_id):
        log.debug("%r: get_connected_instruments: port_id=%s",
                  self._platform_id, port_id)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot get_connected_instruments: _rsn_oms object required (created via connect() call)")

        try:
            response = self._rsn_oms.instr.get_connected_instruments(self._platform_id,
                                                                     port_id)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot get_connected_instruments: %s" % str(e))

        log.debug("%r: port_id=%r: get_connected_instruments response: %s",
                  self._platform_id, port_id, response)

        dic_plat = self._verify_platform_id_in_response(response)
        port_dic = self._verify_port_id_in_response(port_id, dic_plat)

        return dic_plat  # note: return the dic for the platform

    def turn_on_port(self, port_id):
        log.debug("%r: turning on port: port_id=%s",
                  self._platform_id, port_id)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot turn_on_platform_port: _rsn_oms object required (created via connect() call)")

        try:
            response = self._rsn_oms.port.turn_on_platform_port(self._platform_id,
                                                                port_id)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot turn_on_platform_port: %s" % str(e))

        log.debug("%r: turn_on_platform_port response: %s",
                  self._platform_id, response)

        dic_plat = self._verify_platform_id_in_response(response)
        self._verify_port_id_in_response(port_id, dic_plat)

        return dic_plat  # note: return the dic for the platform

    def turn_off_port(self, port_id):
        log.debug("%r: turning off port: port_id=%s",
                  self._platform_id, port_id)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot turn_off_platform_port: _rsn_oms object required (created via connect() call)")

        try:
            response = self._rsn_oms.port.turn_off_platform_port(self._platform_id,
                                                                 port_id)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot turn_off_platform_port: %s" % str(e))

        log.debug("%r: turn_off_platform_port response: %s",
                  self._platform_id, response)

        dic_plat = self._verify_platform_id_in_response(response)
        self._verify_port_id_in_response(port_id, dic_plat)

        return dic_plat  # note: return the dic for the platform

    ###############################################
    # External event handling:

    def _register_event_listener(self, url):
        """
        Registers given url for all event types.
        """
        log.debug("%r: registering event listener: %s", self._platform_id, url)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot _register_event_listener: _rsn_oms object required (created via connect() call)")

        try:
            already_registered = self._rsn_oms.event.get_registered_event_listeners()
        except Exception as e:
            raise PlatformConnectionException(
                msg="%r: Cannot get registered event listeners: %s" % (self._platform_id, e))

        if url in already_registered:
            log.debug("listener %r was already registered", url)
            return

        try:
            result = self._rsn_oms.event.register_event_listener(url)
        except Exception as e:
            raise PlatformConnectionException(
                msg="%r: Cannot register_event_listener: %s" % (self._platform_id, e))

        log.debug("%r: register_event_listener(%r) => %s", self._platform_id, url, result)

    def _unregister_event_listener(self, url):
        """
        Unregisters given url for all event types.
        """
        log.debug("%r: unregistering event listener: %s", self._platform_id, url)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot _unregister_event_listener: _rsn_oms object required (created via connect() call)")

        try:
            result = self._rsn_oms.event.unregister_event_listener(url)
        except Exception as e:
            raise PlatformConnectionException(
                msg="%r: Cannot unregister_event_listener: %s" % (self._platform_id, e))

        log.debug("%r: unregister_event_listener(%r) => %s", self._platform_id, url, result)

    def _start_event_dispatch(self):
        """
        Registers the event listener by using a URL that is composed from
        CFG.server.oms.host, CFG.server.oms.port, and CFG.server.oms.path.

        NOTE: the same listener URL will be registered by multiple RSN platform
        drivers. See other related notes in this file.

        @see https://jira.oceanobservatories.org/tasks/browse/OOIION-1287
        @see https://jira.oceanobservatories.org/tasks/browse/OOIION-968
        """

        # gateway host and port to compose URL:
        host = CFG.get_safe('server.oms.host', "localhost")
        port = CFG.get_safe('server.oms.port', "5000")
        path = CFG.get_safe('server.oms.path', "/ion-service/oms_event")

        self.listener_url = "http://%s:%s%s" % (host, port, path)
        self._register_event_listener(self.listener_url)

        return "OK"

    def _stop_event_dispatch(self):
        """
        Stops the dispatch of events received from the platform network.

        NOTE: Nothing is actually done here: since the same listener URL
        is registered by multiple RSN platform drivers, we avoid unregistering
        it here because it might affect other drivers still depending on the
        events being notified.

        @see https://jira.oceanobservatories.org/tasks/browse/OOIION-968
        """

        log.debug("%r: Not unregistering listener URL to avoid affecting "
                  "other RSN platform drivers", self._platform_id)

        # unregister listener:
        #self._unregister_event_listener(self.listener_url)
        # NOTE: NO, DON'T unregister: other drivers might still be depending
        # on the listener being registered.

        return "OK"

    ##############################################################
    # sync/checksum
    ##############################################################

    def get_external_checksum(self):
        """
        Returns the checksum of the external platform associated with this
        driver.

        @return SHA1 hash value as string of hexadecimal digits.
        """
        log.debug("%r: get_checksum...", self._platform_id)

        if self._rsn_oms is None: 
            raise PlatformConnectionException("Cannot get_checksum: _rsn_oms object required (created via connect() call)")

        try:
            response = self._rsn_oms.config.get_checksum(self._platform_id)
        except Exception as e:
            raise PlatformConnectionException(msg="Cannot get_checksum: %s" % str(e))

        dic_plat = self._verify_platform_id_in_response(response)
        log.debug("%r: get_checksum... dic_plat=%s" % (self._platform_id, dic_plat))
        return dic_plat  # note: return the dic for the platform

    def _check_sync(self):
        """
        This will be the main operation related with checking that the
        information on this platform agent (and sub-platforms) is consistent
        with the information in the external network rooted at the
        corresponding platform, then publishing relevant notification events.

        For the moment, it only tries to do the following:
        - gets the checksum reported by the external platform
        - compares it with the local checksum
        - if equal ...
        - if different ...

        @todo complete implementation

        @return TODO
        """

        log.debug("%r: _check_sync: getting external checksum...", self._platform_id)

        external_checksum = self.get_external_checksum()
        local_checksum = self._pnode.compute_checksum()

        if external_checksum == local_checksum:
            result = "OK: checksum for platform_id=%r: %s" % (
                self._platform_id, local_checksum)
        else:
            result = "ERROR: different external and local checksums for " \
                     "platform_id=%r: %s != %s" % (self._platform_id,
                     external_checksum, local_checksum)

            # TODO - determine what sub-components are in disagreement
            # TODO - publish relevant event(s)

        log.debug("%r: _check_sync: result: %s", self._platform_id, result)

        return result

    ##############################################################
    # GET
    ##############################################################

    def get(self, *args, **kwargs):

        if 'attrs' in kwargs:
            attrs = kwargs['attrs']
            result = self.get_attribute_values(attrs)
            return result

        if 'subplatform_ids' in kwargs:
            result = self.get_subplatform_ids()
            return result

        if 'ports' in kwargs:
            result = self._get_ports()
            return result

        if 'connected_instruments' in kwargs:
            port_id = kwargs['connected_instruments']
            result = self.get_connected_instruments(port_id)
            return result

        if 'metadata' in kwargs:
            result = self.get_metadata()
            return result

        return super(RSNPlatformDriver, self).get(*args, **kwargs)

    ##############################################################
    # EXECUTE
    ##############################################################

    def execute(self, cmd, *args, **kwargs):
        """
        Executes the given command.

        @param cmd   command

        @return  result of the execution
        """

        if cmd == RSNPlatformDriverEvent.CHECK_SYNC:
            result = self._check_sync()

        elif cmd == RSNPlatformDriverEvent.TURN_ON_PORT:
            result = self.turn_on_port(*args, **kwargs)

        elif cmd == RSNPlatformDriverEvent.TURN_OFF_PORT:
            result = self.turn_off_port(*args, **kwargs)

        elif cmd == RSNPlatformDriverEvent.CONNECT_INSTRUMENT:
            result = self.connect_instrument(*args, **kwargs)

        elif cmd == RSNPlatformDriverEvent.DISCONNECT_INSTRUMENT:
            result = self.disconnect_instrument(*args, **kwargs)

        else:
            result = super(RSNPlatformDriver, self).execute(cmd, args, kwargs)

        return result

    def _get_ports(self):
        ports = {}
        for port_id, port in self._pnode.ports.iteritems():
            ports[port_id] = {'network': port.network,
                              'state':   port.state}
        log.debug("%r: _get_ports: %s", self._platform_id, ports)
        return ports

    ##############################################################
    # CONNECTED event handlers we add in this subclass
    ##############################################################

    def _handler_connected_connect_instrument(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        port_id = kwargs.get('port_id', None)
        if port_id is None:
            raise FSMError('connect_instrument: missing port_id argument')

        instrument_id = kwargs.get('instrument_id', None)
        if instrument_id is None:
            raise FSMError('connect_instrument: missing instrument_id argument')

        attributes = kwargs.get('attributes', None)
        if attributes is None:
            raise FSMError('connect_instrument: missing attributes argument')

        try:
            result = self.connect_instrument(port_id, instrument_id, attributes)
            return None, result

        except PlatformConnectionException as e:
            return self._connection_lost(RSNPlatformDriverEvent.CONNECT_INSTRUMENT,
                                         args, kwargs, e)

    def _handler_connected_disconnect_instrument(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        port_id = kwargs.get('port_id', None)
        if port_id is None:
            raise FSMError('disconnect_instrument: missing port_id argument')

        instrument_id = kwargs.get('instrument_id', None)
        if instrument_id is None:
            raise FSMError('disconnect_instrument: missing instrument_id argument')

        try:
            result = self.disconnect_instrument(port_id, instrument_id)
            next_state = None

        except PlatformConnectionException as e:
            return self._connection_lost(RSNPlatformDriverEvent.DISCONNECT_INSTRUMENT,
                                         args, kwargs, e)

        return next_state, result

    def _handler_connected_turn_on_port(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        port_id = kwargs.get('port_id', None)
        if port_id is None:
            raise FSMError('turn_on_port: missing port_id argument')

        try:
            result = self.turn_on_port(port_id)
            return None, result

        except PlatformConnectionException as e:
            return self._connection_lost(RSNPlatformDriverEvent.TURN_ON_PORT,
                                         args, kwargs, e)

    def _handler_connected_turn_off_port(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        port_id = kwargs.get('port_id', None)
        if port_id is None:
            raise FSMError('turn_off_port: missing port_id argument')

        try:
            result = self.turn_off_port(port_id)
            return None, result

        except PlatformConnectionException as e:
            return self._connection_lost(RSNPlatformDriverEvent.TURN_OFF_PORT,
                                         args, kwargs, e)

    def _handler_connected_check_sync(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        try:
            result = self._check_sync()
            return None, result

        except PlatformConnectionException as e:
            return self._connection_lost(RSNPlatformDriverEvent.CHECK_SYNC,
                                         args, kwargs, e)

    ##############################################################
    # RSN Platform driver FSM setup
    ##############################################################

    def _construct_fsm(self,
                       states=RSNPlatformDriverState,
                       events=RSNPlatformDriverEvent,
                       enter_event=RSNPlatformDriverEvent.ENTER,
                       exit_event=RSNPlatformDriverEvent.EXIT):
        """
        """
        log.debug("constructing RSN platform driver FSM")

        super(RSNPlatformDriver, self)._construct_fsm(states, events,
                                                      enter_event, exit_event)

        # CONNECTED state event handlers we add in this class:
        self._fsm.add_handler(PlatformDriverState.CONNECTED, RSNPlatformDriverEvent.CONNECT_INSTRUMENT, self._handler_connected_connect_instrument)
        self._fsm.add_handler(PlatformDriverState.CONNECTED, RSNPlatformDriverEvent.DISCONNECT_INSTRUMENT, self._handler_connected_disconnect_instrument)
        self._fsm.add_handler(PlatformDriverState.CONNECTED, RSNPlatformDriverEvent.TURN_ON_PORT, self._handler_connected_turn_on_port)
        self._fsm.add_handler(PlatformDriverState.CONNECTED, RSNPlatformDriverEvent.TURN_OFF_PORT, self._handler_connected_turn_off_port)
        self._fsm.add_handler(PlatformDriverState.CONNECTED, RSNPlatformDriverEvent.CHECK_SYNC, self._handler_connected_check_sync)