"""
Modulo per la gestione di Timer e Programmazioni per dispositivi Smart Home.
Supporta ritardi temporizzati relativi (es. tra 30 min, tra 1h, tra 5h) oppure
orari assoluti (ISO timestamp). Gestisce l'esecuzione automatica, la persistenza
su SQLite e l'invio di notifiche all'attivazione/spegnimento.
"""

from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from backend.database import (
    save_scheduled_task,
    get_due_scheduled_tasks,
    get_active_scheduled_tasks,
    get_device_active_schedules,
    cancel_scheduled_task,
    mark_scheduled_task_completed,
    to_local_datetime_str
)
from backend.tuya_service import tuya_service
from backend.thinq_service import thinq_service
from backend.smartthings_service import smartthings_service
from backend.notifier import NotificationService

logger = logging.getLogger("weather_hub.device_scheduler")
notifier = NotificationService()

class DeviceScheduler:
    def __init__(self):
        self._running = False
        self._check_interval_sec = 5

    def create_schedule(
        self,
        ecosystem: str,
        device_id: str,
        device_name: str,
        action: str,
        delay_minutes: Optional[float] = None,
        target_time_iso: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Crea e programma un nuovo task per un dispositivo.
        """
        now_utc = datetime.now(timezone.utc)
        
        if delay_minutes is not None and float(delay_minutes) > 0:
            exec_dt = now_utc + timedelta(minutes=float(delay_minutes))
            execute_at_iso = exec_dt.isoformat()
        elif target_time_iso:
            execute_at_iso = target_time_iso
        else:
            raise ValueError("Specificare delay_minutes o target_time_iso")

        task_id = "sched_" + uuid.uuid4().hex[:12]
        
        saved = save_scheduled_task(
            task_id=task_id,
            ecosystem=ecosystem.lower().strip(),
            device_id=device_id.strip(),
            device_name=device_name.strip() or "Dispositivo Smart",
            action=action.lower().strip(),
            execute_at=execute_at_iso,
            payload=payload
        )
        
        logger.info(
            f"⏱️ [SCHEDULER] Programmata azione '{action}' per '{device_name}' ({ecosystem}) alle {to_local_datetime_str(execute_at_iso)}"
        )
        return saved

    def cancel_schedule(self, task_id: str) -> bool:
        """Annulla un'azione programmata pendente."""
        success = cancel_scheduled_task(task_id)
        if success:
            logger.info(f"🚫 [SCHEDULER] Task {task_id} annullato.")
        return success

    def get_schedules(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Restituisce le programmazioni attive generali o filtrate per singolo dispositivo."""
        if device_id:
            return get_device_active_schedules(device_id)
        return get_active_scheduled_tasks()

    async def execute_due_tasks(self) -> int:
        """Controlla ed esegue tutti i task scaduti."""
        due_tasks = get_due_scheduled_tasks()
        if not due_tasks:
            return 0

        executed_count = 0
        for task in due_tasks:
            task_id = task["task_id"]
            ecosystem = task["ecosystem"]
            device_id = task["device_id"]
            device_name = task["device_name"]
            action = task["action"]
            payload = task.get("payload") or {}

            logger.info(f"🚀 [SCHEDULER] Esecuzione programmata {task_id} -> {device_name} ({action})")
            
            target_state = True if action in ("turn_on", "on", "start") else False
            result = None
            is_success = False
            error_msg = None

            try:
                if ecosystem == "tuya":
                    result = await tuya_service.toggle_device(device_id, target_state)
                    is_success = bool(result.get("success"))
                    if not is_success:
                        error_msg = result.get("error") or "Comando Tuya non riuscito"

                elif ecosystem == "thinq":
                    ctrl_payload = {"power": target_state}
                    if "target_temp" in payload:
                        ctrl_payload["target_temp"] = payload["target_temp"]
                    if "mode" in payload:
                        ctrl_payload["mode"] = payload["mode"]
                    result = await thinq_service.control_device(device_id, ctrl_payload)
                    is_success = bool(result.get("success"))
                    if not is_success:
                        error_msg = result.get("error") or "Comando LG ThinQ non riuscito"

                elif ecosystem == "smartthings":
                    cmd = "on" if target_state else "off"
                    res = await smartthings_service.execute_command(device_id, "switch", cmd)
                    is_success = bool(res)
                    result = {"success": res}
                    if not is_success:
                        error_msg = "Comando SmartThings non riuscito"

                elif ecosystem in ("homeassistant", "hass"):
                    from backend.homeassistant_service import homeassistant_service
                    res = await homeassistant_service.toggle_device(device_id, target_state)
                    is_success = bool(res.get("success"))
                    result = res
                    if not is_success:
                        error_msg = res.get("error") or "Comando Home Assistant non riuscito"

                else:
                    error_msg = f"Ecosistema '{ecosystem}' non supportato"

            except Exception as e:
                logger.error(f"❌ [SCHEDULER] Errore esecuzione task {task_id}: {e}", exc_info=True)
                error_msg = str(e)
                result = {"error": str(e)}

            # Aggiorna stato nel DB
            final_status = "executed" if is_success else "failed"
            mark_scheduled_task_completed(task_id, final_status, result)
            executed_count += 1

            # Invia notifica all'utente
            action_desc = "acceso 🟢" if target_state else "spento 🔴"
            if is_success:
                notifier.send_alert(
                    alert_type="device_scheduled_action",
                    title="⏱️ Timer Programmato Eseguito",
                    message=f"Il dispositivo '{device_name}' è stato {action_desc} come programmato.",
                    priority="normal",
                    extra_data={"task_id": task_id, "device_id": device_id, "ecosystem": ecosystem}
                )
            else:
                notifier.send_alert(
                    alert_type="device_scheduled_action_failed",
                    title="⚠️ Errore Timer Programmato",
                    message=f"Impossibile eseguire l'azione programmata su '{device_name}': {error_msg}",
                    priority="high",
                    extra_data={"task_id": task_id, "device_id": device_id, "error": error_msg}
                )

        return executed_count

    async def worker_loop(self):
        """Loop in background per la verifica continua dei timer programmabili."""
        self._running = True
        logger.info("⏱️ [SCHEDULER] Avvio worker loop timer & programmazione dispositivi...")
        
        while self._running:
            try:
                await self.execute_due_tasks()
            except asyncio.CancelledError:
                logger.info("⏱️ [SCHEDULER] Worker loop interrotto.")
                break
            except Exception as e:
                logger.error(f"Errore non gestito nello scheduler loop: {e}")

            await asyncio.sleep(self._check_interval_sec)

    def stop(self):
        self._running = False

device_scheduler = DeviceScheduler()
