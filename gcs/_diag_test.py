from pymavlink import mavutil
import time

m = mavutil.mavlink_connection('tcp:127.0.0.1:5760', autoreconnect=False, source_system=255)
print("BAGLANDI_SOKET")
m.wait_heartbeat(timeout=15)
print("HEARTBEAT_ALINDI")

# _isle_terrain_request ile aynı sekilde sahte TERRAIN_DATA gonder
data = [100] * 16
m.mav.terrain_data_send(
    int(41.0 * 1e7),
    int(29.0 * 1e7),
    100,
    0,
    data,
)
print("TERRAIN_DATA_GONDERILDI")
time.sleep(3)
print("3SN_SONRA_HALA_BURADAYIZ")
