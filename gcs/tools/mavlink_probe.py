"""
Minimal MAVLink probe for quick connection testing.

Usage example:
  python mavlink_probe.py --conn udp:127.0.0.1:14550
"""

import argparse
import time

from pymavlink import mavutil


def _format_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal MAVLink probe")
    parser.add_argument("--conn", default="udp:127.0.0.1:14550",
                        help="Connection string (udp/tcp/serial).")
    parser.add_argument("--duration", type=int, default=15,
                        help="Listen duration in seconds.")
    parser.add_argument("--heartbeat-timeout", type=int, default=10,
                        help="Heartbeat wait timeout in seconds.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print all message types.")
    args = parser.parse_args()

    conn = args.conn

    try:
        mav = mavutil.mavlink_connection(conn, autoreconnect=False, source_system=255)
    except Exception as exc:
        print(f"Connection failed: {exc}")
        return 2

    try:
        mav.wait_heartbeat(timeout=args.heartbeat_timeout)
    except Exception:
        print("No heartbeat received.")
        return 2

    print(f"Connected: {conn}")

    try:
        mav.mav.request_data_stream_send(
            mav.target_system,
            mav.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            10,
            1,
        )
    except Exception:
        pass

    start = time.time()
    counts: dict[str, int] = {}

    while time.time() - start < args.duration:
        msg = mav.recv_match(blocking=True, timeout=1)
        if msg is None:
            continue
        mtype = msg.get_type()
        if mtype == "BAD_DATA":
            continue

        counts[mtype] = counts.get(mtype, 0) + 1

        if mtype == "HEARTBEAT":
            armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            print(f"[HEARTBEAT] mode={msg.custom_mode} armed={armed}")
        elif mtype == "STATUSTEXT":
            text = _format_text(msg.text)
            print(f"[STATUSTEXT] sev={msg.severity} {text}")
        elif mtype == "SYS_STATUS":
            volt = msg.voltage_battery / 1000.0 if msg.voltage_battery != 65535 else 0.0
            amp = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
            bat = msg.battery_remaining
            print(f"[SYS_STATUS] V={volt:.2f} A={amp:.2f} pct={bat}")
        elif mtype == "VFR_HUD":
            print(
                f"[VFR_HUD] alt={msg.alt:.1f} gs={msg.groundspeed:.1f} climb={msg.climb:.1f}"
            )
        elif mtype == "GPS_RAW_INT":
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            print(f"[GPS_RAW_INT] fix={msg.fix_type} sats={msg.satellites_visible} lat={lat:.6f} lon={lon:.6f}")
        elif mtype == "EKF_STATUS_REPORT":
            print(f"[EKF_STATUS_REPORT] flags=0x{msg.flags:04x} vel_var={msg.velocity_variance:.2f}")
        elif args.verbose:
            print(f"[{mtype}]")

    print("--- Summary ---")
    for key in sorted(counts.keys()):
        print(f"{key}: {counts[key]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
