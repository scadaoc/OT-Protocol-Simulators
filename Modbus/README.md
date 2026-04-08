# Modbus Simulator

A Modbus TCP/RTU server simulator built with **pymodbus 3.12.x**, used as the lab target for the [Caldera-OT blog series](https://medium.com/@yourblog) on Medium.

## Install

```bash
pip install pymodbus==3.12.1
```

## Run

```bash
python3 modbus_server.py               # TCP on port 5020 (no sudo needed)
sudo python3 modbus_server.py --port 502   # standard Modbus port
python3 modbus_server.py --serial /dev/ttyUSB0  # RTU over serial
python3 modbus_server.py --no-drift    # disable live sensor simulation
```

## What's inside

| Data Type | FC | Access | Simulates |
|---|---|---|---|
| Coils | 01/05/0F | R/W | Pumps, valves, breakers |
| Discrete Inputs | 02 | R | Switches, door contacts |
| Holding Registers | 03/06/10 | R/W | Setpoints, PID, config |
| Input Registers | 04 | R | Live sensor readings |

All 10,000 addresses are available per data type. Input registers update every second with small random noise to simulate live sensor data.
