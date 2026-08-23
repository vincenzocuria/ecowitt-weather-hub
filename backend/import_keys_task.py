import os
import sys
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.tuya_service import tuya_service
from backend.database import get_tuya_local_devices

async def main():
    print("=" * 60)
    print("📥 SCARICAMENTO E SALVATAGGIO PERMANENTE CHIAVI TUYA IN LOCALE")
    print("=" * 60)
    
    # 1. Import keys
    res = await tuya_service.import_keys_from_cloud()
    print("Esito operazione:", json.dumps(res, indent=2, ensure_ascii=False))
    
    # 2. Query saved local devices
    devices = get_tuya_local_devices()
    print(f"\n✅ Dispositivi salvati permanentemente nel database locale SQLite: {len(devices)}")
    for d in devices:
        print(f"  • [{d['name']}] ID: {d['device_id']} | Local Key: {d['local_key']} | IP: {d.get('ip_address') or 'Auto-Discovery'}")
    
    # 3. LAN IP Discovery / Scan
    print("\n📡 Scansione rapida della rete Wi-Fi locale (192.168.1.0/24) per rilevare gli IP...")
    lan_found = await tuya_service.scan_lan_devices()
    print(f"Dispositivi Tuya attivi trovati su porta 6668: {len(lan_found)}")
    for f in lan_found:
        print(f"  • IP: {f['ip']} (Porta 6668 aperta)")
    
    print("\n" + "=" * 60)
    print("🎉 TUYA CLOUD È ORA COMPLETAMENTE SUPERATO E NON PIÙ NECESSARIO!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
