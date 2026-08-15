import base64

code = open("backend/app_standalone.py", "rb").read()
b64_str = base64.b64encode(code).decode("ascii")

compose = f"""services:
  ecowitt-hub:
    image: python:3.11-slim
    container_name: ecowitt-hub
    restart: unless-stopped
    ports:
      - "8090:8080"
    environment:
      - TZ=${TZ:-Europe/Rome}
      - TIMEZONE=${TIMEZONE:-Europe/Rome}
      - DATA_DIR=/data
      - SOIL_MOISTURE_LOW_THRESHOLD=${SOIL_MOISTURE_LOW_THRESHOLD:-25.0}
      - LIGHTNING_MAX_DISTANCE_KM=${LIGHTNING_MAX_DISTANCE_KM:-30.0}
      - TEMP_FREEZE_THRESHOLD_C=${TEMP_FREEZE_THRESHOLD_C:-1.0}
      - TEMP_HEAT_THRESHOLD_C=${TEMP_HEAT_THRESHOLD_C:-38.0}
      - LATITUDE=${LATITUDE:-41.9028}
      - LONGITUDE=${LONGITUDE:-12.4964}
      - NTFY_TOPIC=${NTFY_TOPIC:-}
    volumes:
      - ecowitt-data:/data
    command: >
      sh -c "pip install --no-cache-dir fastapi uvicorn requests python-multipart tzdata &&
             python -c \\"import base64; exec(base64.b64decode('{b64_str}').decode('utf-8'))\\""

  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared-meteo
    restart: unless-stopped
    command: tunnel --no-autoupdate --protocol http2 run --token ${CLOUDFLARE_TUNNEL_TOKEN}

volumes:
  ecowitt-data:
"""

with open("docker-compose-qnap.yml", "w", encoding="utf-8") as f:
    f.write(compose)

with open("b64.txt", "w", encoding="utf-8") as f:
    f.write(b64_str)

print("Generated standalone docker-compose-qnap.yml with Cloudflared tunnel successfully")
