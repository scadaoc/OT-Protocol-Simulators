#!/usr/bin/env python3
"""
=============================================================================
  Modbus TCP/RTU Simulator — Built for Caldera-OT Blog Series by SCADAOC
  Compatible with: pymodbus 3.12.1
=============================================================================

p

Supported Function Codes:
  FC01 - Read Coils
  FC02 - Read Discrete Inputs
  FC03 - Read Holding Registers
  FC04 - Read Input Registers
  FC05 - Write Single Coil
  FC06 - Write Single Register
  FC0F - Write Multiple Coils
  FC10 - Write Multiple Registers
  FC17 - Read/Write Multiple Registers
  FC2B - Read Device Identification (MEI)

Usage:
  python3 modbus_server.py                   # TCP on 0.0.0.0:5020 (no sudo)
  sudo python3 modbus_server.py --port 502   # standard Modbus port
  python3 modbus_server.py --host 192.168.1.10 --port 5020
  python3 modbus_server.py --serial /dev/ttyUSB0   # RTU over serial
  python3 modbus_server.py --no-drift              # static data, no noise
=============================================================================
"""

import asyncio
import logging
import argparse
import random
import time
from threading import Thread

# ---------------------------------------------------------------------------
# pymodbus 3.12 correct imports
#
#   ModbusDeviceIdentification  --> top-level "pymodbus" package
#   ModbusDeviceContext         --> pymodbus.datastore  (was ModbusSlaveContext)
#   ModbusServerContext         --> pymodbus.datastore  (unchanged)
#   ModbusSequentialDataBlock   --> pymodbus.datastore  (unchanged)
#   StartAsyncTcpServer         --> pymodbus.server     (unchanged)
#   FramerType                  --> pymodbus.framer     (unchanged)
# ---------------------------------------------------------------------------
from pymodbus import ModbusDeviceIdentification          # <-- top-level in 3.x
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusDeviceContext,                                 # <-- was ModbusSlaveContext
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer, StartAsyncSerialServer
from pymodbus.framer import FramerType

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("modbus-sim")


# ---------------------------------------------------------------------------
# Data store builders — pre-populated with realistic OT values
# ---------------------------------------------------------------------------

def build_coils() -> ModbusSequentialDataBlock:
    """
    FC01 / FC05 / FC0F — Coils (1-bit, read/write)
    Simulates: pump on/off, valve open/close, breaker state, alarms
    """
    values = [False] * 10000

    # Pump states
    values[0] = True    # Pump 1 ON
    values[1] = False   # Pump 2 OFF
    values[2] = True    # Pump 3 ON

    # Valve states
    values[10] = True   # Valve 1 OPEN
    values[11] = True   # Valve 2 OPEN
    values[12] = False  # Valve 3 CLOSED
    values[13] = False  # Valve 4 CLOSED

    # Alarm bits
    values[100] = False  # High-pressure alarm   : OK
    values[101] = False  # Low-flow alarm         : OK
    values[102] = False  # Temperature alarm      : OK
    values[103] = True   # General system status  : OK

    # Substation breaker states
    values[200] = True   # Breaker A CLOSED
    values[201] = False  # Breaker B OPEN
    values[202] = True   # Breaker C CLOSED

    return ModbusSequentialDataBlock(0x00, values)


def build_discrete_inputs() -> ModbusSequentialDataBlock:
    """
    FC02 — Discrete Inputs (1-bit, read-only)
    Simulates: physical sensor states, door contacts, limit switches
    """
    values = [False] * 10000

    values[0]  = True    # Door contact       : CLOSED
    values[1]  = False   # Emergency stop     : NOT pressed
    values[2]  = True    # High-level float   : ACTIVE
    values[3]  = False   # Low-level float    : INACTIVE
    values[10] = True    # Motor running feedback
    values[11] = False   # Motor fault feedback
    values[20] = True    # Pressure switch    : HIGH
    values[21] = True    # Flow switch        : FLOW DETECTED

    return ModbusSequentialDataBlock(0x00, values)


def build_holding_registers() -> ModbusSequentialDataBlock:
    """
    FC03 / FC06 / FC10 / FC17 — Holding Registers (16-bit, read/write)
    Simulates: setpoints, PID parameters, motor speed, config registers
    """
    values = [0] * 10000

    # Setpoints
    values[0]  = 1500   # Pump speed setpoint     (RPM)
    values[1]  = 850    # Pressure setpoint        (mbar*10 = 8.5 bar)
    values[2]  = 250    # Temperature setpoint     (°C*10 = 25.0°C)
    values[3]  = 750    # Flow setpoint            (L/min*10)

    # Mirrored process values (updated live by drift thread)
    values[10] = 1487   # Actual pump speed
    values[11] = 832    # Actual pressure
    values[12] = 248    # Actual temperature
    values[13] = 741    # Actual flow

    # PID tuning registers
    values[20] = 100    # Kp * 10
    values[21] = 50     # Ki * 10
    values[22] = 10     # Kd * 10

    # Device configuration
    values[100] = 1     # Device / slave ID
    values[101] = 502   # TCP port config register
    values[102] = 100   # Scan rate (ms)

    # Alarm thresholds
    values[200] = 1000  # High-pressure limit
    values[201] = 100   # Low-pressure limit
    values[202] = 600   # High-temperature limit
    values[203] = 50    # Low-flow limit

    # Runtime counters
    values[300] = 4712  # Total runtime   (hours)
    values[301] = 127   # Start count
    values[302] = 3     # Fault count

    # Firmware/version registers (a common Caldera-OT recon target)
    values[1000] = 0x0103   # Firmware version 1.3
    values[1001] = 0x2024   # Build year 2024
    values[1002] = 0x0A01   # Build month/day Oct 1

    return ModbusSequentialDataBlock(0x00, values)


def build_input_registers() -> ModbusSequentialDataBlock:
    """
    FC04 — Input Registers (16-bit, read-only)
    Simulates: live sensor readings, analog inputs, energy meters
    """
    values = [0] * 10000

    # Analog sensor readings
    values[0]  = 1487   # Pump speed       (RPM)
    values[1]  = 832    # Pressure         (mbar*10)
    values[2]  = 248    # Temperature      (°C*10)
    values[3]  = 741    # Flow rate        (L/min*10)
    values[4]  = 485    # Humidity         (%*10)
    values[5]  = 2311   # Voltage          (V*10)
    values[6]  = 1250   # Current          (A*100)

    # Power / energy meter
    values[10] = 1140   # Active power     (W*10)
    values[11] = 9950   # Power factor     (PF * 10000 → 0.995)
    values[12] = 3300   # Reactive power   (VAR)

    # Tank levels
    values[20] = 7800   # Tank 1 level     (mm)
    values[21] = 4500   # Tank 2 level     (mm)
    values[22] = 9100   # Tank 3 level     (mm)

    # Vibration / diagnostics
    values[30] = 12     # Vibration RMS    (mm/s * 10)
    values[31] = 450    # Bearing temp     (°C*10)
    values[32] = 980    # Insulation R     (MΩ*10)

    return ModbusSequentialDataBlock(0x00, values)


# ---------------------------------------------------------------------------
# Device Identification — FC2B (MEI)
# ---------------------------------------------------------------------------

def build_identity() -> ModbusDeviceIdentification:
    # In pymodbus 3.x the preferred way is info_name dict
    identity = ModbusDeviceIdentification()
    identity.VendorName = 'Siemens AG'
    identity.ProductCode = '6ES7 214-1AG40-0XB0'  
    identity.VendorUrl = 'https://www.siemens.com'
    identity.ProductName = 'SIMATIC S7-1200'
    identity.ModelName = 'CPU 1214C DC/DC/DC'
    identity.MajorMinorRevision = 'V4.4.1' 


# ---------------------------------------------------------------------------
# Server context builder
# ---------------------------------------------------------------------------

def build_context() -> ModbusServerContext:
    """
    Build a single-device Modbus context.

    pymodbus 3.12 class names:
        ModbusDeviceContext  (was: ModbusSlaveContext)
        ModbusServerContext  (unchanged)
    """
    device = ModbusDeviceContext(
        di=build_discrete_inputs(),
        co=build_coils(),
        hr=build_holding_registers(),
        ir=build_input_registers(),
    )
    # single=True → every unit-id maps to the same device context
    context = ModbusServerContext(devices=device, single=True)
    return context


# ---------------------------------------------------------------------------
# Background sensor drift — makes data "live" for blog demos
# ---------------------------------------------------------------------------

def simulate_sensor_drift(context: ModbusServerContext):
    """
    Mutates input registers every second with small random noise so that
    any polling client (Caldera-OT, mbpoll, Wireshark) sees changing data.
    """
    base = {
        0: 1487,   # RPM
        1: 832,    # Pressure
        2: 248,    # Temperature
        3: 741,    # Flow
        5: 2311,   # Voltage
        6: 1250,   # Current
    }
    log.info("[drift] Sensor simulation thread started (1 s interval)")

    while True:
        try:
            device = context[0]  # single=True → any key returns the device

            for addr, centre in base.items():
                new_val = max(0, centre + random.randint(-15, 15))
                device.setValues(4, addr, [new_val])   # fc=4 → input regs

            # Mirror live values into holding registers 10–13
            device.setValues(3, 10, device.getValues(4, 0, 1))
            device.setValues(3, 11, device.getValues(4, 1, 1))
            device.setValues(3, 12, device.getValues(4, 2, 1))
            device.setValues(3, 13, device.getValues(4, 3, 1))

            time.sleep(1)
        except Exception as exc:
            log.warning(f"[drift] {exc}")
            time.sleep(2)


# ---------------------------------------------------------------------------
# Async server runners
# ---------------------------------------------------------------------------

async def run_tcp(host: str, port: int,
                  context: ModbusServerContext,
                  identity: ModbusDeviceIdentification):
    log.info(f"[server] Modbus TCP listening on {host}:{port}")
    await StartAsyncTcpServer(
        context=context,
        identity=identity,
        address=(host, port),
        framer=FramerType.SOCKET,
    )


async def run_rtu(port: str,
                  context: ModbusServerContext,
                  identity: ModbusDeviceIdentification):
    log.info(f"[server] Modbus RTU on {port} @ 9600-8N1")
    await StartAsyncSerialServer(
        context=context,
        identity=identity,
        port=port,
        baudrate=9600,
        bytesize=8,
        parity="N",
        stopbits=1,
        framer=FramerType.RTU,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Modbus OT Simulator — Caldera-OT Blog Series",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 modbus_server.py                          # TCP :5020 (no sudo)
  sudo python3 modbus_server.py --port 502          # standard Modbus port
  python3 modbus_server.py --host 192.168.1.10      # specific NIC
  python3 modbus_server.py --serial /dev/ttyUSB0    # RTU mode
  python3 modbus_server.py --no-drift               # static data

Quick Python test:
  from pymodbus.client import ModbusTcpClient
  c = ModbusTcpClient('127.0.0.1', port=5020)
  c.connect()
  print(c.read_coils(0, 10).bits)
  print(c.read_discrete_inputs(0, 8).bits)
  print(c.read_holding_registers(0, 10).registers)
  print(c.read_input_registers(0, 10).registers)
  c.write_coil(0, False)       # FC05 - write single coil
  c.write_register(0, 2000)    # FC06 - write single register
  c.write_coils(10, [True, False, True])          # FC0F
  c.write_registers(0, [1800, 900, 270, 800])     # FC10
  c.close()
        """,
    )
    parser.add_argument("--host",     default="0.0.0.0",
                        help="TCP bind address (default: 0.0.0.0)")
    parser.add_argument("--port",     default=5020, type=int,
                        help="TCP port (default: 5020)")
    parser.add_argument("--serial",   default=None,
                        help="Serial port for RTU, e.g. /dev/ttyUSB0")
    parser.add_argument("--no-drift", action="store_true",
                        help="Disable live sensor simulation")
    args = parser.parse_args()

    context  = build_context()
    identity = build_identity()

    if not args.no_drift:
        Thread(target=simulate_sensor_drift, args=(context,), daemon=True).start()
    else:
        log.info("[server] Sensor drift DISABLED")

    mode = f"RTU @ {args.serial}" if args.serial else f"TCP @ {args.host}:{args.port}"
    print("\n" + "="*62)
    print("  MODBUS OT SIMULATOR — CALDERA-OT BLOG SERIES")
    print("="*62)
    print(f"  Mode  : {mode}")
    print(f"  Drift : {'OFF' if args.no_drift else 'ON  (1 s interval)'}")
    print()
    print("  Data Map:")
    print("  ┌───────────────────────────────────────────────────────────┐")
    print("  │ FC01  Coils           [addr 0–9999]  R/W  pumps/valves   │")
    print("  │ FC02  Discrete Inputs [addr 0–9999]  R    switches        │")
    print("  │ FC03  Holding Regs    [addr 0–9999]  R/W  setpoints      │")
    print("  │ FC04  Input Regs      [addr 0–9999]  R    live sensors    │")
    print("  └───────────────────────────────────────────────────────────┘")
    print()
    print("  Notable addresses:")
    print("    HR[0-3]   : setpoints (speed/pressure/temp/flow)")
    print("    HR[10-13] : live process values (updated by drift thread)")
    print("    HR[1000]  : firmware version register (0x0103 = v1.3)")
    print("    IR[0-6]   : sensor readings (RPM/pressure/temp/flow/V/A)")
    print("    CO[0-2]   : pump on/off     CO[10-13]: valve open/close")
    print("="*62 + "\n")

    loop = asyncio.get_event_loop()
    try:
        if args.serial:
            loop.run_until_complete(run_rtu(args.serial, context, identity))
        else:
            loop.run_until_complete(run_tcp(args.host, args.port, context, identity))
    except KeyboardInterrupt:
        log.info("[server] Stopped.")


if __name__ == "__main__":
    main()
