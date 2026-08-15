import os
import sys
import socket
import uvicorn

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = 8080
    
    print("=" * 65)
    print("🌤️  ECOWITT & SAINLOGIC WEATHER HUB - SVILUPPO LOCALE")
    print("=" * 65)
    print(f"👉 Dashboard su questo PC:   http://localhost:{port}")
    print(f"👉 Dashboard in Rete Locale: http://{local_ip}:{port}")
    print(f"👉 Endpoint Ricezione Dati:  http://{local_ip}:{port}/api/ecowitt")
    print(f"👉 Albo dei Record:          http://localhost:{port}/records")
    print(f"👉 Grafici & Analisi:        http://localhost:{port}/charts")
    print("=" * 65)
    print("💡 Nota: Tutte le modifiche al codice o template si ricaricano a caldo!")
    print("=" * 65)

    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
