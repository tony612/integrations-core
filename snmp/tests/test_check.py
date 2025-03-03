# (C) Datadog, Inc. 2018
# All rights reserved
# Licensed under Simplified BSD License (see LICENSE)

import ipaddress
import os
import socket
import time

import mock
import pysnmp_mibs
import pytest
import yaml

from datadog_checks import snmp
from datadog_checks.base import ConfigurationError
from datadog_checks.dev import temp_dir
from datadog_checks.snmp import SnmpCheck

from . import common

pytestmark = pytest.mark.usefixtures("dd_environment")


def test_command_generator():
    """
    Command generator's parameters should match init_config
    """
    instance = common.generate_instance_config(common.CONSTRAINED_OID)
    check = SnmpCheck('snmp', common.MIBS_FOLDER, [instance])
    config = check._config

    # Test command generator MIB source
    mib_folders = config.snmp_engine.getMibBuilder().getMibSources()
    full_path_mib_folders = [f.fullPath() for f in mib_folders]
    assert check.ignore_nonincreasing_oid is False  # Default value

    check = SnmpCheck('snmp', common.IGNORE_NONINCREASING_OID, [instance])
    assert check.ignore_nonincreasing_oid

    assert common.MIBS_FOLDER["mibs_folder"] in full_path_mib_folders


def test_type_support(aggregator):
    """
    Support expected types
    """
    metrics = common.SUPPORTED_METRIC_TYPES + common.UNSUPPORTED_METRICS
    instance = common.generate_instance_config(metrics)
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for metric in common.SUPPORTED_METRIC_TYPES:
        metric_name = "snmp." + metric['name']
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, count=1)
    for metric in common.UNSUPPORTED_METRICS:
        metric_name = "snmp." + metric['name']
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, count=0)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_transient_error(aggregator):
    instance = common.generate_instance_config(common.SUPPORTED_METRIC_TYPES)
    check = common.create_check(instance)

    with mock.patch.object(check, 'raise_on_error_indication', side_effect=RuntimeError):
        check.check(instance)

    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.CRITICAL, tags=common.CHECK_TAGS, at_least=1)

    check.check(instance)
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)


def test_snmpget(aggregator):
    """
    When failing with 'snmpget' command, SNMP check falls back to 'snmpgetnext'

        > snmpget -v2c -c public localhost:11111 1.3.6.1.2.1.25.6.3.1.4
        iso.3.6.1.2.1.25.6.3.1.4 = No Such Instance currently exists at this OID
        > snmpgetnext -v2c -c public localhost:11111 1.3.6.1.2.1.25.6.3.1.4
        iso.3.6.1.2.1.25.6.3.1.4.0 = INTEGER: 4
    """
    instance = common.generate_instance_config(common.PLAY_WITH_GET_NEXT_METRICS)
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for metric in common.PLAY_WITH_GET_NEXT_METRICS:
        metric_name = "snmp." + metric['name']
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, at_least=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_snmp_getnext_call():
    instance = common.generate_instance_config(common.PLAY_WITH_GET_NEXT_METRICS)
    instance['snmp_version'] = 1
    check = common.create_check(instance)

    # Test that we invoke next with the correct keyword arguments that are hard to test otherwise
    with mock.patch("datadog_checks.snmp.snmp.hlapi.nextCmd") as nextCmd:

        check.check(instance)
        _, kwargs = nextCmd.call_args
        assert ("ignoreNonIncreasingOid", False) in kwargs.items()
        assert ("lexicographicMode", False) in kwargs.items()

        check = SnmpCheck('snmp', common.IGNORE_NONINCREASING_OID, [instance])
        check.check(instance)
        _, kwargs = nextCmd.call_args
        assert ("ignoreNonIncreasingOid", True) in kwargs.items()
        assert ("lexicographicMode", False) in kwargs.items()


def test_custom_mib(aggregator):
    instance = common.generate_instance_config(common.DUMMY_MIB_OID)
    instance["community_string"] = "dummy"

    check = SnmpCheck('snmp', common.MIBS_FOLDER, [instance])
    check.check(instance)

    # Test metrics
    for metric in common.DUMMY_MIB_OID:
        metric_name = "snmp." + (metric.get('name') or metric.get('symbol'))
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, at_least=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)


def test_scalar(aggregator):
    """
    Support SNMP scalar objects
    """
    instance = common.generate_instance_config(common.SCALAR_OBJECTS)
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for metric in common.SCALAR_OBJECTS:
        metric_name = "snmp." + (metric.get('name') or metric.get('symbol'))
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, count=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_enforce_constraint(aggregator):
    instance = common.generate_instance_config(common.CONSTRAINED_OID)
    instance["community_string"] = "constraint"
    instance["enforce_mib_constraints"] = True
    check = common.create_check(instance)

    check.check(instance)

    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.CRITICAL, tags=common.CHECK_TAGS, at_least=1)

    assert "failed at: ValueConstraintError" in aggregator.service_checks("snmp.can_check")[0].message


def test_unenforce_constraint(aggregator):
    """
    Allow ignoring constraints
    """
    instance = common.generate_instance_config(common.CONSTRAINED_OID)
    instance["community_string"] = "constraint"
    instance["enforce_mib_constraints"] = False
    check = common.create_check(instance)
    check.check(instance)

    # Test metrics
    for metric in common.CONSTRAINED_OID:
        metric_name = "snmp." + (metric.get('name') or metric.get('symbol'))
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, count=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_table(aggregator):
    """
    Support SNMP tabular objects
    """
    instance = common.generate_instance_config(common.TABULAR_OBJECTS)
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for symbol in common.TABULAR_OBJECTS[0]['symbols']:
        metric_name = "snmp." + symbol
        aggregator.assert_metric(metric_name, at_least=1)
        aggregator.assert_metric_has_tag(metric_name, common.CHECK_TAGS[0], at_least=1)

        for mtag in common.TABULAR_OBJECTS[0]['metric_tags']:
            tag = mtag['tag']
            aggregator.assert_metric_has_tag_prefix(metric_name, tag, at_least=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_table_v3_MD5_DES(aggregator):
    """
    Support SNMP V3 priv modes: MD5 + DES
    """
    # build multiple confgs
    auth = 'MD5'
    priv = 'DES'
    name = 'instance_{}_{}'.format(auth, priv)

    instance = common.generate_v3_instance_config(
        common.TABULAR_OBJECTS,
        name=name,
        user='datadog{}{}'.format(auth.upper(), priv.upper()),
        auth=common.AUTH_PROTOCOLS[auth],
        auth_key=common.AUTH_KEY,
        priv=common.PRIV_PROTOCOLS[priv],
        priv_key=common.PRIV_KEY,
    )
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for symbol in common.TABULAR_OBJECTS[0]['symbols']:
        metric_name = "snmp." + symbol
        aggregator.assert_metric(metric_name, at_least=1)
        aggregator.assert_metric_has_tag(metric_name, common.CHECK_TAGS[0], at_least=1)

        for mtag in common.TABULAR_OBJECTS[0]['metric_tags']:
            tag = mtag['tag']
            aggregator.assert_metric_has_tag_prefix(metric_name, tag, at_least=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_table_v3_MD5_AES(aggregator):
    """
    Support SNMP V3 priv modes: MD5 + AES
    """
    # build multiple confgs
    auth = 'MD5'
    priv = 'AES'
    name = 'instance_{}_{}'.format(auth, priv)

    instance = common.generate_v3_instance_config(
        common.TABULAR_OBJECTS,
        name=name,
        user='datadog{}{}'.format(auth.upper(), priv.upper()),
        auth=common.AUTH_PROTOCOLS[auth],
        auth_key=common.AUTH_KEY,
        priv=common.PRIV_PROTOCOLS[priv],
        priv_key=common.PRIV_KEY,
    )
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for symbol in common.TABULAR_OBJECTS[0]['symbols']:
        metric_name = "snmp." + symbol
        aggregator.assert_metric(metric_name, at_least=1)
        aggregator.assert_metric_has_tag(metric_name, common.CHECK_TAGS[0], at_least=1)

        for mtag in common.TABULAR_OBJECTS[0]['metric_tags']:
            tag = mtag['tag']
            aggregator.assert_metric_has_tag_prefix(metric_name, tag, at_least=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_table_v3_SHA_DES(aggregator):
    """
    Support SNMP V3 priv modes: SHA + DES
    """
    # build multiple confgs
    auth = 'SHA'
    priv = 'DES'
    name = 'instance_{}_{}'.format(auth, priv)
    instance = common.generate_v3_instance_config(
        common.TABULAR_OBJECTS,
        name=name,
        user='datadog{}{}'.format(auth.upper(), priv.upper()),
        auth=common.AUTH_PROTOCOLS[auth],
        auth_key=common.AUTH_KEY,
        priv=common.PRIV_PROTOCOLS[priv],
        priv_key=common.PRIV_KEY,
    )
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for symbol in common.TABULAR_OBJECTS[0]['symbols']:
        metric_name = "snmp." + symbol
        aggregator.assert_metric(metric_name, at_least=1)
        aggregator.assert_metric_has_tag(metric_name, common.CHECK_TAGS[0], at_least=1)

        for mtag in common.TABULAR_OBJECTS[0]['metric_tags']:
            tag = mtag['tag']
            aggregator.assert_metric_has_tag_prefix(metric_name, tag, at_least=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_table_v3_SHA_AES(aggregator):
    """
    Support SNMP V3 priv modes: SHA + AES
    """
    # build multiple confgs
    auth = 'SHA'
    priv = 'AES'
    name = 'instance_{}_{}'.format(auth, priv)
    instance = common.generate_v3_instance_config(
        common.TABULAR_OBJECTS,
        name=name,
        user='datadog{}{}'.format(auth.upper(), priv.upper()),
        auth=common.AUTH_PROTOCOLS[auth],
        auth_key=common.AUTH_KEY,
        priv=common.PRIV_PROTOCOLS[priv],
        priv_key=common.PRIV_KEY,
    )
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for symbol in common.TABULAR_OBJECTS[0]['symbols']:
        metric_name = "snmp." + symbol
        aggregator.assert_metric(metric_name, at_least=1)
        aggregator.assert_metric_has_tag(metric_name, common.CHECK_TAGS[0], at_least=1)

        for mtag in common.TABULAR_OBJECTS[0]['metric_tags']:
            tag = mtag['tag']
            aggregator.assert_metric_has_tag_prefix(metric_name, tag, at_least=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_bulk_table(aggregator):
    instance = common.generate_instance_config(common.BULK_TABULAR_OBJECTS)
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for symbol in common.BULK_TABULAR_OBJECTS[0]['symbols']:
        metric_name = "snmp." + symbol
        aggregator.assert_metric(metric_name, at_least=1)
        aggregator.assert_metric_has_tag(metric_name, common.CHECK_TAGS[0], at_least=1)

        for mtag in common.BULK_TABULAR_OBJECTS[0]['metric_tags']:
            tag = mtag['tag']
            aggregator.assert_metric_has_tag_prefix(metric_name, tag, at_least=1)

    for symbol in common.BULK_TABULAR_OBJECTS[1]['symbols']:
        metric_name = "snmp." + symbol
        aggregator.assert_metric(metric_name, at_least=1)
        aggregator.assert_metric_has_tag(metric_name, common.CHECK_TAGS[0], at_least=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_invalid_metric(aggregator):
    """
    Invalid metrics raise a Warning and a critical service check
    """
    instance = common.generate_instance_config(common.INVALID_METRICS)
    check = common.create_check(instance)
    check.check(instance)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.CRITICAL, tags=common.CHECK_TAGS, at_least=1)


def test_forcedtype_metric(aggregator):
    """
    Forced Types should be reported as metrics of the forced type
    """
    instance = common.generate_instance_config(common.FORCED_METRICS)
    check = common.create_check(instance)
    check.check(instance)

    for metric in common.FORCED_METRICS:
        metric_name = "snmp." + (metric.get('name') or metric.get('symbol'))
        if metric.get('forced_type') == 'counter':
            # rate will be flushed as a gauge, so count should be 0.
            aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, count=0, metric_type=aggregator.GAUGE)
        elif metric.get('forced_type') == 'gauge':
            aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, at_least=1, metric_type=aggregator.GAUGE)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_invalid_forcedtype_metric(aggregator):
    """
    If a forced type is invalid a warning should be issued + a service check
    should be available
    """
    instance = common.generate_instance_config(common.INVALID_FORCED_METRICS)
    check = common.create_check(instance)

    check.check(instance)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.WARNING, tags=common.CHECK_TAGS, at_least=1)


def test_scalar_with_tags(aggregator):
    """
    Support SNMP scalar objects with tags
    """
    instance = common.generate_instance_config(common.SCALAR_OBJECTS_WITH_TAGS)
    check = common.create_check(instance)

    check.check(instance)

    # Test metrics
    for metric in common.SCALAR_OBJECTS_WITH_TAGS:
        metric_name = "snmp." + (metric.get('name') or metric.get('symbol'))
        tags = common.CHECK_TAGS + metric.get('metric_tags')
        aggregator.assert_metric(metric_name, tags=tags, count=1)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.OK, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_network_failure(aggregator):
    """
    Network failure is reported in service check
    """
    instance = common.generate_instance_config(common.SCALAR_OBJECTS)

    # Change port so connection will fail
    instance['port'] = 162
    check = common.create_check(instance)

    check.check(instance)

    # Test service check
    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.CRITICAL, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_cast_metrics(aggregator):
    instance = common.generate_instance_config(common.CAST_METRICS)
    check = common.create_check(instance)

    check.check(instance)
    aggregator.assert_metric('snmp.cpuload1', value=0.06)
    aggregator.assert_metric('snmp.cpuload2', value=0.06)

    aggregator.all_metrics_asserted()


def test_profile(aggregator):
    instance = common.generate_instance_config([])
    instance['profile'] = 'profile1'
    init_config = {'profiles': {'profile1': {'definition': common.SUPPORTED_METRIC_TYPES}}}
    check = SnmpCheck('snmp', init_config, [instance])
    check.check(instance)

    for metric in common.SUPPORTED_METRIC_TYPES:
        metric_name = "snmp." + metric['name']
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, count=1)
    aggregator.assert_all_metrics_covered()


def test_profile_by_file(aggregator):
    instance = common.generate_instance_config([])
    instance['profile'] = 'profile1'
    with temp_dir() as tmp:
        profile_file = os.path.join(tmp, 'profile1.yaml')
        with open(profile_file, 'w') as f:
            f.write(yaml.safe_dump(common.SUPPORTED_METRIC_TYPES))
        init_config = {'profiles': {'profile1': {'definition_file': profile_file}}}
        check = SnmpCheck('snmp', init_config, [instance])
        check.check(instance)

    for metric in common.SUPPORTED_METRIC_TYPES:
        metric_name = "snmp." + metric['name']
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, count=1)
    aggregator.assert_all_metrics_covered()


def test_profile_sys_object(aggregator):
    instance = common.generate_instance_config([])
    init_config = {
        'profiles': {
            'profile1': {'definition': common.SUPPORTED_METRIC_TYPES, 'sysobjectid': '1.3.6.1.4.1.8072.3.2.10'}
        }
    }
    check = SnmpCheck('snmp', init_config, [instance])
    check.check(instance)

    for metric in common.SUPPORTED_METRIC_TYPES:
        metric_name = "snmp." + metric['name']
        aggregator.assert_metric(metric_name, tags=common.CHECK_TAGS, count=1)
    aggregator.assert_all_metrics_covered()


def test_profile_sys_object_unknown(aggregator):
    """If the fetched sysObjectID is not referenced by any profiles, check fails."""
    instance = common.generate_instance_config([])
    init_config = {'profiles': {'profile1': {'definition': common.SUPPORTED_METRIC_TYPES, 'sysobjectid': '1.2.3.4.5'}}}
    check = SnmpCheck('snmp', init_config, [instance])
    check.check(instance)

    aggregator.assert_service_check("snmp.can_check", status=SnmpCheck.CRITICAL, tags=common.CHECK_TAGS, at_least=1)

    aggregator.all_metrics_asserted()


def test_profile_sys_object_no_metrics():
    """If an instance is created without metrics and there is no profile defined, an error is raised."""
    instance = common.generate_instance_config([])
    with pytest.raises(ConfigurationError):
        SnmpCheck('snmp', {}, [instance])


def test_discovery(aggregator):
    host = socket.gethostbyname(common.HOST)
    network = ipaddress.ip_network(u'{}/29'.format(host), strict=False).with_prefixlen
    # Make sure the check handles bytes
    network = network.encode("utf-8")
    check_tags = ['snmp_device:{}'.format(host)]
    instance = {'name': 'snmp_conf', 'network_address': network, 'port': common.PORT, 'community_string': 'public'}
    init_config = {
        'profiles': {
            'profile1': {'definition': common.SUPPORTED_METRIC_TYPES, 'sysobjectid': '1.3.6.1.4.1.8072.3.2.10'}
        }
    }
    check = SnmpCheck('snmp', init_config, [instance])
    try:
        for _ in range(30):
            check.check(instance)
            if aggregator.metric_names:
                break
            time.sleep(1)
    finally:
        check._running = False

    for metric in common.SUPPORTED_METRIC_TYPES:
        metric_name = "snmp." + metric['name']
        aggregator.assert_metric(metric_name, tags=check_tags, count=1)
    aggregator.assert_all_metrics_covered()


def test_fetch_mib():
    instance = common.generate_instance_config(common.DUMMY_MIB_OID)
    # Try a small MIB
    instance['metrics'][0]['MIB'] = 'A3COM-AUDL-R1-MIB'
    instance['enforce_mib_constraints'] = False
    # Remove it
    path = os.path.join(os.path.dirname(pysnmp_mibs.__file__), 'A3COM-AUDL-R1-MIB.py')
    # Make sure it doesn't exist
    if os.path.exists(path):
        os.unlink(path)
    pyc = '{}c'.format(path)
    if os.path.exists(pyc):
        os.unlink(pyc)
    SnmpCheck('snmp', common.MIBS_FOLDER, [instance])
    assert os.path.exists(path)


def test_different_mibs(aggregator):
    metrics = [
        {
            'MIB': 'ENTITY-SENSOR-MIB',
            'table': 'entitySensorObjects',
            'symbols': ['entPhySensorValue'],
            'metric_tags': [
                {'tag': 'desc', 'column': 'entLogicalDescr', 'table': 'entLogicalTable', 'MIB': 'ENTITY-MIB'}
            ],
        }
    ]
    instance = common.generate_instance_config(metrics)
    instance['community_string'] = 'entity'
    check = common.create_check(instance)

    check.check(instance)
    aggregator.assert_metric_has_tag_prefix('snmp.entPhySensorValue', 'desc')


def test_different_tables(aggregator):
    metrics = [
        {
            'MIB': 'IF-MIB',
            'table': 'ifTable',
            'symbols': ['ifInOctets', 'ifOutOctets'],
            'metric_tags': [
                {'tag': 'interface', 'column': 'ifDescr'},
                {'tag': 'speed', 'column': 'ifHighSpeed', 'table': 'ifXTable'},
            ],
        }
    ]
    instance = common.generate_instance_config(metrics)
    instance['community_string'] = 'if'
    # Enforce bulk to trigger table usage
    instance['bulk_threshold'] = 1
    instance['enforce_mib_constraints'] = False
    check = common.create_check(instance)

    check.check(instance)
    aggregator.assert_metric_has_tag_prefix('snmp.ifInOctets', 'speed')


def test_f5(aggregator):
    instance = common.generate_instance_config([])
    # We need the full path as we're not in installed mode
    path = os.path.join(os.path.dirname(snmp.__file__), 'data', 'profiles', 'f5-big-ip.yaml')
    instance['community_string'] = 'f5'
    instance['enforce_mib_constraints'] = False

    init_config = {'profiles': {'f5-big-ip': {'definition_file': path, 'sysobjectid': '1.3.6.1.4.1.3375.2.1.3.4.43'}}}
    check = SnmpCheck('snmp', init_config, [instance])

    check.check(instance)

    gauges = [
        'sysStatMemoryTotal',
        'sysStatMemoryUsed',
        'sysGlobalTmmStatMemoryTotal',
        'sysGlobalTmmStatMemoryUsed',
        'sysGlobalHostOtherMemoryTotal',
        'sysGlobalHostOtherMemoryUsed',
        'sysGlobalHostSwapTotal',
        'sysGlobalHostSwapUsed',
        'sysTcpStatOpen',
        'sysTcpStatCloseWait',
        'sysTcpStatFinWait',
        'sysTcpStatTimeWait',
        'sysTcpStatAccepts',
        'sysTcpStatAcceptfails',
        'sysTcpStatConnects',
        'sysTcpStatConnfails',
        'sysUdpStatOpen',
        'sysUdpStatAccepts',
        'sysUdpStatAcceptfails',
        'sysUdpStatConnects',
        'sysUdpStatConnfails',
        'sysClientsslStatCurConns',
        'sysClientsslStatEncryptedBytesIn',
        'sysClientsslStatEncryptedBytesOut',
        'sysClientsslStatDecryptedBytesIn',
        'sysClientsslStatDecryptedBytesOut',
        'sysClientsslStatHandshakeFailures',
    ]
    cpu_gauges = [
        'sysMultiHostCpuUser',
        'sysMultiHostCpuNice',
        'sysMultiHostCpuSystem',
        'sysMultiHostCpuIdle',
        'sysMultiHostCpuIrq',
        'sysMultiHostCpuSoftirq',
        'sysMultiHostCpuIowait',
    ]
    if_gauges = ['ifInOctets', 'ifInErrors', 'ifOutOctets', 'ifOutErrors']
    interfaces = ['1.0', 'mgmt', '/Common/internal', '/Common/http-tunnel', '/Common/socks-tunnel']
    for metric in gauges:
        aggregator.assert_metric('snmp.{}'.format(metric), tags=common.CHECK_TAGS, count=1)
    for metric in cpu_gauges:
        aggregator.assert_metric('snmp.{}'.format(metric), tags=['cpu:0'] + common.CHECK_TAGS, count=1)
        aggregator.assert_metric('snmp.{}'.format(metric), tags=['cpu:1'] + common.CHECK_TAGS, count=1)
    for metric in if_gauges:
        for interface in interfaces:
            aggregator.assert_metric(
                'snmp.{}'.format(metric), tags=['interface:{}'.format(interface)] + common.CHECK_TAGS, count=1
            )
    aggregator.assert_all_metrics_covered()


def test_router(aggregator):
    instance = common.generate_instance_config([])
    # We need the full path as we're not in installed mode
    path = os.path.join(os.path.dirname(snmp.__file__), 'data', 'profiles', 'generic-router.yaml')
    instance['community_string'] = 'network'
    instance['profile'] = 'router'
    instance['enforce_mib_constraints'] = False

    init_config = {'profiles': {'router': {'definition_file': path}}}
    check = SnmpCheck('snmp', init_config, [instance])

    check.check(instance)

    tcp_rates = [
        'tcpActiveOpens',
        'tcpPassiveOpens',
        'tcpAttemptFails',
        'tcpEstabResets',
        'tcpHCInSegs',
        'tcpHCOutSegs',
        'tcpRetransSegs',
        'tcpInErrs',
        'tcpOutRsts',
    ]
    tcp_gauges = ['tcpCurrEstab']
    udp_rates = ['udpHCInDatagrams', 'udpNoPorts', 'udpInErrors', 'udpHCOutDatagrams']
    if_rates = [
        'ifInErrors',
        'ifInDiscards',
        'ifOutErrors',
        'ifOutDiscards',
        'ifHCInOctets',
        'ifHCInUcastPkts',
        'ifHCInMulticastPkts',
        'ifHCInBroadcastPkts',
        'ifHCOutOctets',
        'ifHCOutUcastPkts',
        'ifHCOutMulticastPkts',
        'ifHCOutBroadcastPkts',
    ]
    ip_rates = [
        'ipSystemStatsHCInReceives',
        'ipSystemStatsHCInOctets',
        'ipSystemStatsInHdrErrors',
        'ipSystemStatsInNoRoutes',
        'ipSystemStatsInAddrErrors',
        'ipSystemStatsInUnknownProtos',
        'ipSystemStatsInTruncatedPkts',
        'ipSystemStatsHCInForwDatagrams',
        'ipSystemStatsReasmReqds',
        'ipSystemStatsReasmOKs',
        'ipSystemStatsReasmFails',
        'ipSystemStatsInDiscards',
        'ipSystemStatsHCInDelivers',
        'ipSystemStatsHCOutRequests',
        'ipSystemStatsOutNoRoutes',
        'ipSystemStatsHCOutForwDatagrams',
        'ipSystemStatsOutDiscards',
        'ipSystemStatsOutFragReqds',
        'ipSystemStatsOutFragOKs',
        'ipSystemStatsOutFragFails',
        'ipSystemStatsOutFragCreates',
        'ipSystemStatsHCOutTransmits',
        'ipSystemStatsHCOutOctets',
        'ipSystemStatsHCInMcastPkts',
        'ipSystemStatsHCInMcastOctets',
        'ipSystemStatsHCOutMcastPkts',
        'ipSystemStatsHCOutMcastOctets',
        'ipSystemStatsHCInBcastPkts',
        'ipSystemStatsHCOutBcastPkts',
    ]
    ip_if_rates = [
        'ipIfStatsHCInOctets',
        'ipIfStatsInHdrErrors',
        'ipIfStatsInNoRoutes',
        'ipIfStatsInAddrErrors',
        'ipIfStatsInUnknownProtos',
        'ipIfStatsInTruncatedPkts',
        'ipIfStatsHCInForwDatagrams',
        'ipIfStatsReasmReqds',
        'ipIfStatsReasmOKs',
        'ipIfStatsReasmFails',
        'ipIfStatsInDiscards',
        'ipIfStatsHCInDelivers',
        'ipIfStatsHCOutRequests',
        'ipIfStatsHCOutForwDatagrams',
        'ipIfStatsOutDiscards',
        'ipIfStatsOutFragReqds',
        'ipIfStatsOutFragOKs',
        'ipIfStatsOutFragFails',
        'ipIfStatsOutFragCreates',
        'ipIfStatsHCOutTransmits',
        'ipIfStatsHCOutOctets',
        'ipIfStatsHCInMcastPkts',
        'ipIfStatsHCInMcastOctets',
        'ipIfStatsHCOutMcastPkts',
        'ipIfStatsHCOutMcastOctets',
        'ipIfStatsHCInBcastPkts',
        'ipIfStatsHCOutBcastPkts',
    ]
    for interface in ['eth0', 'eth1']:
        tags = ['interface:{}'.format(interface)] + common.CHECK_TAGS
        for metric in if_rates:
            aggregator.assert_metric('snmp.{}'.format(metric), metric_type=aggregator.RATE, tags=tags, count=1)
    for metric in tcp_rates:
        aggregator.assert_metric('snmp.{}'.format(metric), metric_type=aggregator.RATE, tags=common.CHECK_TAGS, count=1)
    for metric in tcp_gauges:
        aggregator.assert_metric(
            'snmp.{}'.format(metric), metric_type=aggregator.GAUGE, tags=common.CHECK_TAGS, count=1
        )
    for metric in udp_rates:
        aggregator.assert_metric('snmp.{}'.format(metric), metric_type=aggregator.RATE, tags=common.CHECK_TAGS, count=1)
    for version in ['ipv4', 'ipv6']:
        tags = ['ipversion:{}'.format(version)] + common.CHECK_TAGS
        for metric in ip_rates:
            aggregator.assert_metric('snmp.{}'.format(metric), metric_type=aggregator.RATE, tags=tags, count=1)
        for metric in ip_if_rates:
            for interface in ['17', '21']:
                tags = ['ipversion:{}'.format(version), 'interface:{}'.format(interface)] + common.CHECK_TAGS
                aggregator.assert_metric('snmp.{}'.format(metric), metric_type=aggregator.RATE, tags=tags, count=1)
