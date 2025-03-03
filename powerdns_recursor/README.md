# PowerDNS Recursor Integration

## Overview

Track the performance of your PowerDNS Recursor and monitor strange or worrisome traffic. This Agent check collects a wealth of metrics from your recursors, including those for:

* Query answer times - see how many responses take less than 1ms, 10ms, 100ms, 1s, and greater than 1s
* Query timeouts
* Cache hits and misses
* Answer rates by type - SRVFAIL, NXDOMAIN, NOERROR
* Ignored and dropped packets

And many more.

## Setup

Follow the instructions below to install and configure this check for an Agent running on a host. For containerized environments, see the [Autodiscovery Integration Templates][1] for guidance on applying these instructions.

### Installation

The PowerDNS Recursor check is included in the [Datadog Agent][2] package, so you don't need to install anything else on your recursors.

### Configuration
#### Prepare PowerDNS

This check collects performance statistics via pdns_recursor's statistics API. Versions of pdns_recursor before 4.1 do not enable the stats API by default. If you're running an older version, enable it by adding the following to your recursor config file (e.g. `/etc/powerdns/recursor.conf`):

   ```
   webserver=yes
   api-key=changeme             # only available since ver 4.0
   webserver-readonly=yes       # default no
   #webserver-port=8081         # default 8082
   #webserver-address=0.0.0.0   # default 127.0.0.1
   ```

If you're running pdns_recursor 3.x, prepend `experimental-` to these option names, e.g. `experimental-webserver=yes`.

If you're running pdns_recursor >= 4.1, just set `api-key`.

Restart the recursor to enable the statistics API.

#### Connect the Agent

1. Edit the `powerdns_recursor.d/conf.yaml` file, in the `conf.d/` folder at the root of your [Agent's configuration directory][3].
	See the [sample powerdns_recursor.d/conf.yaml][4] for all available configuration options:

    ```yaml
	    init_config:

	    instances:
      	- host: 127.0.0.1
	        port: 8082
	        api_key: changeme
	        version: 4 # omit this line if you're running pdns_recursor version 3.x
    ```

2. [Restart the Agent][5] to begin sending PowerDNS Recursor metrics to Datadog.

### Validation

[Run the Agent's `status` subcommand][6] and look for `powerdns_recursor` under the Checks section.

## Data Collected
### Metrics
See [metadata.csv][7] for a list of metrics provided by this integration.

### Events
The PowerDNS Recursor check does not include any events.

### Service Checks
**`powerdns.recursor.can_connect`**:

Returns CRITICAL if the Agent is unable to connect to the recursor's statistics API, otherwise OK.

## Troubleshooting
Need help? Contact [Datadog support][8].

[1]: https://docs.datadoghq.com/agent/autodiscovery/integrations
[2]: https://app.datadoghq.com/account/settings#agent
[3]: https://docs.datadoghq.com/agent/guide/agent-configuration-files/?tab=agentv6#agent-configuration-directory
[4]: https://github.com/DataDog/integrations-core/blob/master/powerdns_recursor/datadog_checks/powerdns_recursor/data/conf.yaml.example
[5]: https://docs.datadoghq.com/agent/guide/agent-commands/?tab=agentv6#start-stop-and-restart-the-agent
[6]: https://docs.datadoghq.com/agent/guide/agent-commands/?tab=agentv6#agent-status-and-information
[7]: https://github.com/DataDog/integrations-core/blob/master/powerdns_recursor/metadata.csv
[8]: https://docs.datadoghq.com/help
