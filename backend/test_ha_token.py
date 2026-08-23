import json
import urllib.request

correct_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyMDI2OTBjZDkyYmY0NjI3YTY2ODEwYWI1YTUzY2UwZCIsImlhdCI6MTc4NzQ5MjMxNSwiZXhwIjoyMTAyODUyMzE1fQ.GDXuF99qNZ3zoQa3ElrVdR5pELmHratjzmr1KlTspvg"

# Test /api/states
req_states = urllib.request.Request("http://192.168.1.250:8123/api/states", headers={"Authorization": f"Bearer {correct_jwt}"})
with urllib.request.urlopen(req_states) as resp:
    data = json.loads(resp.read().decode())
    print(f"DISCOVERED {len(data)} ENTITIES IN HOME ASSISTANT:")
    for ent in data:
        ent_id = ent.get('entity_id', '')
        name = ent.get('attributes', {}).get('friendly_name', ent_id)
        state = ent.get('state', '')
        print(f"  [{ent_id}] '{name}' -> State: {state}")
