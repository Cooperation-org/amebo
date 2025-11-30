"""
Admin API Routes
Endpoints for system administration and management
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from src.api.auth_utils import get_current_user, require_admin
from src.api.middleware.workspace_auth import verify_workspace_access, get_workspace_ids_for_org
from src.db.connection import DatabaseConnection
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class CreateScheduleRequest(BaseModel):
    workspace_id: str = Field(..., min_length=1, max_length=20)
    cron_expression: str = Field(..., min_length=9, max_length=100)
    days_to_backfill: int = Field(default=7, ge=1, le=90)
    include_all_channels: bool = True


class BackfillScheduleResponse(BaseModel):
    schedule_id: int
    workspace_id: str
    cron_expression: str
    days_to_backfill: int
    include_all_channels: bool
    is_active: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime


class TriggerManualBackfillRequest(BaseModel):
    workspace_id: str = Field(..., min_length=1, max_length=20)
    days_to_backfill: int = Field(default=7, ge=1, le=90)
    include_all_channels: bool = True


class ManualBackfillResponse(BaseModel):
    job_id: str
    status: str
    message: str
    next_run_time: Optional[str] = None


class JobRunResponse(BaseModel):
    job_run_id: int
    workspace_id: str
    job_type: str
    status: str
    messages_collected: Optional[int]
    channels_processed: Optional[int]
    error_message: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]


class JobListResponse(BaseModel):
    jobs: List[dict]
    total: int


# ============================================================================
# BACKFILL SCHEDULE MANAGEMENT
# ============================================================================

@router.post("/backfill/schedules", response_model=BackfillScheduleResponse)
async def create_backfill_schedule(
    request: CreateScheduleRequest,
    current_user: dict = Depends(require_admin)
):
    """
    Create a scheduled backfill job for a workspace
    Requires admin role
    """
    org_id = current_user['org_id']

    # Verify workspace access
    verify_workspace_access(request.workspace_id, org_id)

    conn = DatabaseConnection.get_connection()
    cur = conn.cursor()

    try:
        # Check if schedule already exists for this workspace
        cur.execute("""
            SELECT schedule_id FROM backfill_schedules
            WHERE workspace_id = %s
        """, (request.workspace_id,))

        if cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"Backfill schedule already exists for workspace {request.workspace_id}"
            )

        # Create schedule
        cur.execute("""
            INSERT INTO backfill_schedules (
                org_id,
                workspace_id,
                cron_expression,
                days_to_backfill,
                include_all_channels,
                created_by
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING schedule_id, created_at
        """, (
            org_id,
            request.workspace_id,
            request.cron_expression,
            request.days_to_backfill,
            request.include_all_channels,
            current_user['user_id']
        ))

        schedule_id, created_at = cur.fetchone()
        conn.commit()

        logger.info(
            f"✅ Created backfill schedule {schedule_id} for workspace {request.workspace_id}"
        )

        # Note: The scheduler will pick this up on next restart or via reload endpoint
        # For immediate effect, call the reload endpoint or restart the scheduler

        return BackfillScheduleResponse(
            schedule_id=schedule_id,
            workspace_id=request.workspace_id,
            cron_expression=request.cron_expression,
            days_to_backfill=request.days_to_backfill,
            include_all_channels=request.include_all_channels,
            is_active=True,
            last_run_at=None,
            next_run_at=None,
            created_at=created_at
        )

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error creating backfill schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()


@router.get("/backfill/schedules", response_model=List[BackfillScheduleResponse])
async def list_backfill_schedules(
    current_user: dict = Depends(get_current_user)
):
    """List all backfill schedules for the organization"""
    org_id = current_user['org_id']

    conn = DatabaseConnection.get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                schedule_id,
                workspace_id,
                cron_expression,
                days_to_backfill,
                include_all_channels,
                is_active,
                last_run_at,
                next_run_at,
                created_at
            FROM backfill_schedules
            WHERE org_id = %s
            ORDER BY created_at DESC
        """, (org_id,))

        schedules = []
        for row in cur.fetchall():
            schedules.append(BackfillScheduleResponse(
                schedule_id=row[0],
                workspace_id=row[1],
                cron_expression=row[2],
                days_to_backfill=row[3],
                include_all_channels=row[4],
                is_active=row[5],
                last_run_at=row[6],
                next_run_at=row[7],
                created_at=row[8]
            ))

        return schedules

    finally:
        cur.close()
        conn.close()


@router.delete("/backfill/schedules/{schedule_id}")
async def delete_backfill_schedule(
    schedule_id: int,
    current_user: dict = Depends(require_admin)
):
    """Delete a backfill schedule"""
    org_id = current_user['org_id']

    conn = DatabaseConnection.get_connection()
    cur = conn.cursor()

    try:
        # Verify ownership
        cur.execute("""
            SELECT workspace_id FROM backfill_schedules
            WHERE schedule_id = %s AND org_id = %s
        """, (schedule_id, org_id))

        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Schedule not found")

        # Delete
        cur.execute("""
            DELETE FROM backfill_schedules
            WHERE schedule_id = %s
        """, (schedule_id,))

        conn.commit()

        logger.info(f"🗑️  Deleted backfill schedule {schedule_id}")

        return {"message": "Schedule deleted successfully"}

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error deleting schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()


# ============================================================================
# MANUAL BACKFILL TRIGGER
# ============================================================================

@router.post("/backfill/trigger", response_model=ManualBackfillResponse)
async def trigger_manual_backfill(
    request: TriggerManualBackfillRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Trigger a manual backfill job (bypasses schedule)
    Available to all authenticated users for their own workspaces
    """
    org_id = current_user['org_id']

    # Verify workspace access
    verify_workspace_access(request.workspace_id, org_id)

    # Import scheduler instance (will be set by main.py)
    from src.main import app_instance

    if not app_instance or not app_instance.scheduler:
        raise HTTPException(
            status_code=503,
            detail="Scheduler not available. Please ensure the application is running."
        )

    try:
        result = await app_instance.scheduler.trigger_manual_backfill(
            org_id=org_id,
            workspace_id=request.workspace_id,
            days_to_backfill=request.days_to_backfill,
            include_all_channels=request.include_all_channels
        )

        logger.info(
            f"🔧 Manual backfill triggered by user {current_user['user_id']} "
            f"for workspace {request.workspace_id}"
        )

        return ManualBackfillResponse(**result)

    except Exception as e:
        logger.error(f"❌ Error triggering manual backfill: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# JOB HISTORY
# ============================================================================

@router.get("/backfill/jobs", response_model=List[JobRunResponse])
async def list_job_runs(
    workspace_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user)
):
    """List backfill job execution history"""
    org_id = current_user['org_id']

    # If workspace_id specified, verify access
    if workspace_id:
        verify_workspace_access(workspace_id, org_id)

    conn = DatabaseConnection.get_connection()
    cur = conn.cursor()

    try:
        # Build query
        query = """
            SELECT
                job_run_id,
                workspace_id,
                job_type,
                status,
                messages_collected,
                channels_processed,
                error_message,
                started_at,
                completed_at
            FROM backfill_job_runs
            WHERE org_id = %s
        """
        params = [org_id]

        if workspace_id:
            query += " AND workspace_id = %s"
            params.append(workspace_id)

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY started_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)

        jobs = []
        for row in cur.fetchall():
            jobs.append(JobRunResponse(
                job_run_id=row[0],
                workspace_id=row[1],
                job_type=row[2],
                status=row[3],
                messages_collected=row[4],
                channels_processed=row[5],
                error_message=row[6],
                started_at=row[7],
                completed_at=row[8]
            ))

        return jobs

    finally:
        cur.close()
        conn.close()


@router.get("/backfill/jobs/active")
async def list_active_jobs(current_user: dict = Depends(get_current_user)):
    """Get currently scheduled jobs from the scheduler"""
    from src.main import app_instance

    if not app_instance or not app_instance.scheduler:
        raise HTTPException(
            status_code=503,
            detail="Scheduler not available"
        )

    jobs = app_instance.scheduler.get_scheduled_jobs()

    return JobListResponse(
        jobs=jobs,
        total=len(jobs)
    )
