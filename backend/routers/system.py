import os
import logging
from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import JSONResponse, FileResponse

from backend.database import (
    get_database_stats, perform_database_maintenance, get_all_records,
    get_connection, DB_PATH
)
from backend.history_importer import history_importer

logger = logging.getLogger("weather_hub")

router = APIRouter(tags=["System & Database"])

# --- STATISTICHE, BACKUP & MANUTENZIONE DATABASE ---

@router.get("/api/system/db-stats")
async def api_system_db_stats():
    """Restituisce le statistiche su dimensioni del database, totale campioni e stato WAL."""
    return get_database_stats()

@router.get("/api/system/backup")
async def api_system_backup():
    """Scarica il file completo del database SQLite come backup sicuro."""
    if not os.path.exists(DB_PATH):
        return JSONResponse({"error": "Database non trovato"}, status_code=404)
    # Esegue un checkpoint prima del download per sincronizzare il file WAL nel DB principale
    try:
        c = get_connection()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        c.close()
    except Exception:
        pass
    return FileResponse(
        path=DB_PATH,
        filename="weather_history_backup.db",
        media_type="application/octet-stream"
    )

@router.post("/api/system/maintenance")
async def api_system_maintenance(retention_days: int = Query(60, ge=7, le=365)):
    """Esegue manualmente la compattazione e il downsampling dello storico > retention_days."""
    res = perform_database_maintenance(retention_days=retention_days)
    return res

# --- BACKFILL STORICO DA WEATHER UNDERGROUND (ICORIG10) & RICALCOLO RECORD ---

@router.get("/api/system/history-backfill/status")
async def api_history_backfill_status():
    """Restituisce lo stato in tempo reale del processo di backfill storico."""
    return history_importer.get_status()

@router.post("/api/system/history-backfill/start")
async def api_history_backfill_start(
    background_tasks: BackgroundTasks,
    station_id: str = Query("ICORIG10"),
    concurrency: int = Query(4, ge=1, le=8)
):
    """Avvia il recupero asincrono dell'intero archivio storico pluriennale da Weather Underground."""
    status = history_importer.get_status()
    if status.get("is_running"):
        return JSONResponse({"status": "already_running", "message": "Importazione già in corso.", "details": status})

    background_tasks.add_task(history_importer.run_full_backfill, station_id=station_id, concurrency=concurrency)
    return {"status": "started", "message": f"Backfill storico avviato per stazione {station_id}.", "initial_status": history_importer.get_status()}

@router.post("/api/system/history-backfill/recalculate-records")
async def api_history_backfill_recalculate():
    """Ricalcola istantaneamente l'Albo dei Record e gli estremi assoluti dal database attuale."""
    updated_count = history_importer.rebuild_records_and_extremes()
    return {
        "status": "success",
        "message": f"Albo dei Record ricalcolato con successo ({updated_count} record aggiornati).",
        "records": get_all_records()
    }
