import asyncio
import socket
import json
import tinytuya

async def scan():
    print("1. Scansione TCP porta 6668 sulla subnet 192.168.1.0/24...")
    async def check(ip):
        try:
            conn = asyncio.open_connection(ip, 6668)
            reader, writer = await asyncio.wait_for(conn, timeout=0.6)
            writer.close()
            await writer.wait_closed()
            return ip
        except Exception:
            return None

    tasks = [check(f"192.168.1.{i}") for i in range(1, 255)]
    results = await asyncio.gather(*tasks)
    found = [ip for ip in results if ip]
    print(f"IP con porta Tuya 6668 aperta trovati ({len(found)}): {found}")

    print("\n2. Scansione broadcast UDP porta 6666/6667...")
    try:
        devs = tinytuya.deviceScan(verbose=False, maxretry=1)
        print("Dispositivi broadcast UDP:")
        print(json.dumps(devs, indent=2))
    except Exception as e:
        print("Errore UDP:", e)

if __name__ == "__main__":
    asyncio.run(scan())

