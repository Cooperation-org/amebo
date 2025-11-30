"""
Q&A routes - ask questions against Slack + documents
"""

from fastapi import APIRouter, HTTPException, status, Depends
from psycopg2 import extras
import logging
import time

from src.api.models import QARequest, QAResponse, QASource
# from src.api.middleware.auth import get_current_user

# Simple auth for development
async def get_current_user():
    return {
        "user_id": 1,
        "org_id": 8,  # Updated to match the test user's org
        "email": "orjienekenechukwu@gmail.com"
    }
from src.api.middleware.workspace_auth import verify_workspace_access, get_workspace_ids_for_org
# from src.services.qa_service import QAService  # Disabled for demo
from src.db.connection import DatabaseConnection

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ask", response_model=QAResponse)
async def ask_question(
    request: QARequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Ask a question - searches Slack messages and documents
    Uses RAG with Claude for answer generation
    """
    start_time = time.time()

    try:
        # Get workspaces for this organization
        workspace_ids = get_workspace_ids_for_org(current_user.get('org_id', 1))
        workspace_id = None

        if workspace_ids:
            # Determine which workspace to query
            if request.workspace_id:
                # SECURITY: Verify user has access to this workspace
                verify_workspace_access(request.workspace_id, current_user.get('org_id', 1))
                workspace_id = request.workspace_id
            else:
                # Use first workspace
                workspace_id = workspace_ids[0]

        # Use main Q&A service
        from src.services.qa_service import QAService
        
        qa_service = QAService(workspace_id=workspace_id or "W_DEFAULT")
        result = qa_service.answer_question(
            question=request.question,
            n_context_messages=request.max_sources
        )

        # Format sources
        sources = []
        for msg in result.get('sources', []):
            sources.append(QASource(
                source_type='slack_message',
                text=msg.get('text', ''),
                metadata={
                    'channel': msg.get('channel', 'unknown'),
                    'user': msg.get('user', 'unknown'),
                    'timestamp': msg.get('timestamp', ''),
                    'reference_number': msg.get('reference_number', 0),
                    'workspace_id': workspace_id
                },
                relevance_score=msg.get('distance')  # ChromaDB distance score
            ))

        # Calculate processing time
        processing_time = (time.time() - start_time) * 1000  # Convert to ms

        # Log usage for billing/analytics
        _log_query_usage(current_user.get('org_id', 1), workspace_id, request.question)

        return QAResponse(
            answer=result['answer'],
            confidence=result.get('confidence', 50),
            confidence_explanation=result.get('confidence_explanation', 'No explanation'),
            project_links=result.get('project_links', []),
            sources=sources,
            question=request.question,
            processing_time_ms=processing_time
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Q&A error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process question: {str(e)}"
        )


def _log_query_usage(org_id: int, workspace_id: str, question: str):
    """Log query for usage tracking and analytics"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            # Update usage metrics
            cur.execute(
                """
                INSERT INTO usage_metrics (org_id, metric_type, count, period_start, period_end)
                VALUES (%s, 'queries', 1, CURRENT_DATE, CURRENT_DATE + INTERVAL '1 day')
                ON CONFLICT (org_id, metric_type, period_start)
                DO UPDATE SET count = usage_metrics.count + 1
                """,
                (org_id,)
            )

            # Log query in audit logs
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, action, resource_type, resource_id, details)
                VALUES (%s, 'qa_query', 'workspace', %s, %s)
                """,
                (org_id, workspace_id, extras.Json({'question_length': len(question)}))
            )

            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to log usage: {e}")
        conn.rollback()
    finally:
        DatabaseConnection.return_connection(conn)


@router.get("/history")
async def get_query_history(
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """
    Get recent Q&A query history for the organization
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    action,
                    resource_type,
                    resource_id as workspace_id,
                    details,
                    created_at
                FROM audit_logs
                WHERE org_id = %s AND action = 'qa_query'
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (current_user.get('org_id', 1), limit)
            )
            history = cur.fetchall()

            return {
                "queries": history,
                "total": len(history)
            }
    finally:
        DatabaseConnection.return_connection(conn)


@router.get("/stats")
async def get_qa_stats(current_user: dict = Depends(get_current_user)):
    """
    Get Q&A usage statistics for the organization
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Get queries this month
            cur.execute(
                """
                SELECT COALESCE(SUM(count), 0) as total_queries
                FROM usage_metrics
                WHERE org_id = %s
                  AND metric_type = 'queries'
                  AND period_start >= DATE_TRUNC('month', CURRENT_DATE)
                """,
                (current_user.get('org_id', 1),)
            )
            stats = cur.fetchone()

            # Get queries today
            cur.execute(
                """
                SELECT COALESCE(SUM(count), 0) as queries_today
                FROM usage_metrics
                WHERE org_id = %s
                  AND metric_type = 'queries'
                  AND period_start = CURRENT_DATE
                """,
                (current_user.get('org_id', 1),)
            )
            today_stats = cur.fetchone()

            return {
                "total_queries_this_month": stats['total_queries'],
                "queries_today": today_stats['queries_today'],
                "org_id": current_user.get('org_id', 1)
            }
    finally:
        DatabaseConnection.return_connection(conn)
