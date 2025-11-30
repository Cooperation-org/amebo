"""
Background Task Scheduler
Manages scheduled backfill jobs for each organization
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from src.db.connection import DatabaseConnection
from src.services.backfill_service import BackfillService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Background task scheduler for automated backfills

    Features:
    - Cron-based scheduling per organization
    - Load schedules from database on startup
    - Job status tracking
    - Manual job triggering via API
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone='UTC')
        self.jobs: Dict[str, Any] = {}  # job_id -> job mapping

    async def start(self):
        """Start the scheduler and load jobs from database"""
        logger.info("🚀 Starting task scheduler...")

        # Load scheduled jobs from database
        await self.load_scheduled_jobs()

        # Start the scheduler
        self.scheduler.start()
        logger.info("✅ Task scheduler started successfully")

    async def stop(self):
        """Stop the scheduler gracefully"""
        logger.info("🛑 Stopping task scheduler...")
        self.scheduler.shutdown(wait=True)
        logger.info("✅ Task scheduler stopped")

    async def load_scheduled_jobs(self):
        """Load all scheduled backfill jobs from database"""
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        try:
            # Get all active backfill schedules
            cur.execute("""
                SELECT
                    bs.schedule_id,
                    bs.org_id,
                    bs.workspace_id,
                    bs.schedule_type,
                    bs.cron_expression,
                    bs.days_to_backfill,
                    bs.include_all_channels,
                    o.org_name
                FROM backfill_schedules bs
                JOIN organizations o ON bs.org_id = o.org_id
                WHERE bs.is_active = TRUE
            """)

            schedules = cur.fetchall()
            logger.info(f"📋 Loading {len(schedules)} scheduled jobs from database")

            for schedule in schedules:
                (schedule_id, org_id, workspace_id, schedule_type,
                 cron_expr, days, include_all, org_name) = schedule

                await self.add_backfill_job(
                    schedule_id=schedule_id,
                    org_id=org_id,
                    workspace_id=workspace_id,
                    cron_expression=cron_expr,
                    days_to_backfill=days,
                    include_all_channels=include_all,
                    org_name=org_name
                )

            logger.info(f"✅ Loaded {len(self.jobs)} scheduled jobs")

        except Exception as e:
            logger.error(f"❌ Error loading scheduled jobs: {e}", exc_info=True)
        finally:
            cur.close()
            conn.close()

    async def add_backfill_job(
        self,
        schedule_id: int,
        org_id: int,
        workspace_id: str,
        cron_expression: str,
        days_to_backfill: int = 7,
        include_all_channels: bool = True,
        org_name: str = "Unknown"
    ):
        """Add a scheduled backfill job"""
        job_id = f"backfill_org{org_id}_ws{workspace_id}_sch{schedule_id}"

        try:
            # Parse cron expression (e.g., "0 2 * * *" = daily at 2 AM UTC)
            trigger = CronTrigger.from_crontab(cron_expression, timezone='UTC')

            # Add job to scheduler
            job = self.scheduler.add_job(
                func=self._run_backfill,
                trigger=trigger,
                id=job_id,
                args=[org_id, workspace_id, days_to_backfill, include_all_channels, schedule_id],
                name=f"Backfill: {org_name} ({workspace_id})",
                replace_existing=True,
                max_instances=1  # Prevent concurrent runs of same job
            )

            self.jobs[job_id] = job

            logger.info(
                f"📅 Scheduled backfill job: {job_id}\n"
                f"   Organization: {org_name} (ID: {org_id})\n"
                f"   Workspace: {workspace_id}\n"
                f"   Schedule: {cron_expression}\n"
                f"   Days to backfill: {days_to_backfill}\n"
                f"   Next run: {job.next_run_time}"
            )

        except Exception as e:
            logger.error(f"❌ Error adding backfill job {job_id}: {e}", exc_info=True)

    async def trigger_manual_backfill(
        self,
        org_id: int,
        workspace_id: str,
        days_to_backfill: int = 7,
        include_all_channels: bool = True
    ) -> Dict[str, Any]:
        """
        Trigger a manual backfill (bypasses schedule)
        Returns job status
        """
        logger.info(
            f"🔧 Manual backfill triggered:\n"
            f"   Org ID: {org_id}\n"
            f"   Workspace: {workspace_id}\n"
            f"   Days: {days_to_backfill}"
        )

        # Create unique job ID for manual run
        job_id = f"manual_backfill_org{org_id}_ws{workspace_id}_{int(datetime.now(timezone.utc).timestamp())}"

        try:
            # Schedule immediate run
            job = self.scheduler.add_job(
                func=self._run_backfill,
                trigger=DateTrigger(run_date=datetime.now(timezone.utc)),
                id=job_id,
                args=[org_id, workspace_id, days_to_backfill, include_all_channels, None],
                name=f"Manual Backfill: Org {org_id} ({workspace_id})",
                max_instances=1
            )

            return {
                "job_id": job_id,
                "status": "scheduled",
                "message": "Manual backfill job scheduled",
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
            }

        except Exception as e:
            logger.error(f"❌ Error triggering manual backfill: {e}", exc_info=True)
            return {
                "job_id": job_id,
                "status": "failed",
                "message": str(e)
            }

    async def _run_backfill(
        self,
        org_id: int,
        workspace_id: str,
        days: int,
        include_all: bool,
        schedule_id: Optional[int] = None
    ):
        """
        Execute backfill task
        This is the actual job function that gets scheduled
        """
        job_type = "scheduled" if schedule_id else "manual"
        logger.info(
            f"▶️  Starting {job_type} backfill:\n"
            f"   Org ID: {org_id}\n"
            f"   Workspace: {workspace_id}\n"
            f"   Days: {days}\n"
            f"   All channels: {include_all}"
        )

        # Track job execution in database
        job_run_id = await self._record_job_start(org_id, workspace_id, schedule_id, job_type)

        try:
            # Get workspace credentials from database
            credentials = await self._get_workspace_credentials(workspace_id)

            if not credentials:
                raise ValueError(f"No credentials found for workspace {workspace_id}")

            # Initialize backfill service
            backfill_service = BackfillService(
                workspace_id=workspace_id,
                bot_token=credentials['bot_token']
            )

            # Run backfill
            result = await backfill_service.backfill_messages(
                days=days,
                include_all_channels=include_all
            )

            # Record success
            await self._record_job_completion(
                job_run_id=job_run_id,
                status="success",
                messages_collected=result.get('total_messages', 0),
                channels_processed=result.get('channels_processed', 0),
                error_message=None
            )

            logger.info(
                f"✅ Backfill completed successfully:\n"
                f"   Messages collected: {result.get('total_messages', 0)}\n"
                f"   Channels processed: {result.get('channels_processed', 0)}"
            )

        except Exception as e:
            logger.error(f"❌ Backfill job failed: {e}", exc_info=True)

            # Record failure
            await self._record_job_completion(
                job_run_id=job_run_id,
                status="failed",
                messages_collected=0,
                channels_processed=0,
                error_message=str(e)
            )

    async def _get_workspace_credentials(self, workspace_id: str) -> Optional[Dict[str, str]]:
        """Get workspace credentials from database"""
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT bot_token, app_token
                FROM installations
                WHERE workspace_id = %s AND is_active = TRUE
            """, (workspace_id,))

            row = cur.fetchone()
            if row:
                return {
                    'bot_token': row[0],
                    'app_token': row[1]
                }
            return None

        finally:
            cur.close()
            conn.close()

    async def _record_job_start(
        self,
        org_id: int,
        workspace_id: str,
        schedule_id: Optional[int],
        job_type: str
    ) -> int:
        """Record job execution start in database"""
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO backfill_job_runs (
                    org_id,
                    workspace_id,
                    schedule_id,
                    job_type,
                    status,
                    started_at
                ) VALUES (%s, %s, %s, %s, 'running', NOW())
                RETURNING job_run_id
            """, (org_id, workspace_id, schedule_id, job_type))

            job_run_id = cur.fetchone()[0]
            conn.commit()
            return job_run_id

        except Exception as e:
            logger.error(f"Error recording job start: {e}")
            conn.rollback()
            return -1
        finally:
            cur.close()
            conn.close()

    async def _record_job_completion(
        self,
        job_run_id: int,
        status: str,
        messages_collected: int,
        channels_processed: int,
        error_message: Optional[str]
    ):
        """Record job completion in database"""
        if job_run_id == -1:
            return

        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                UPDATE backfill_job_runs
                SET
                    status = %s,
                    messages_collected = %s,
                    channels_processed = %s,
                    error_message = %s,
                    completed_at = NOW()
                WHERE job_run_id = %s
            """, (status, messages_collected, channels_processed, error_message, job_run_id))

            conn.commit()

        except Exception as e:
            logger.error(f"Error recording job completion: {e}")
            conn.rollback()
        finally:
            cur.close()
            conn.close()

    def get_scheduled_jobs(self) -> list:
        """Get all currently scheduled jobs"""
        jobs_info = []
        for job in self.scheduler.get_jobs():
            jobs_info.append({
                'job_id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            })
        return jobs_info

    async def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job"""
        try:
            self.scheduler.remove_job(job_id)
            if job_id in self.jobs:
                del self.jobs[job_id]
            logger.info(f"🗑️  Removed job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error removing job {job_id}: {e}")
            return False
