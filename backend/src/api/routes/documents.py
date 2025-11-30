"""
Documents routes - upload, list, delete documents
"""

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
import logging

from src.api.models import DocumentUploadResponse, DocumentListResponse
from src.api.auth_utils import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    workspace_id: str = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a document (PDF, DOCX, TXT, MD)
    Processes and stores in ChromaDB
    Can be tagged to a specific workspace
    """
    from src.db.connection import DatabaseConnection
    
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verify workspace if provided
        if workspace_id:
            cursor.execute("""
                SELECT workspace_id FROM workspaces 
                WHERE workspace_id = %s AND org_id = %s AND is_active = true
            """, (workspace_id, current_user.get("org_id", 1)))
            
            if not cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or inactive workspace"
                )
        
        # Mock document creation for now
        cursor.execute("""
            INSERT INTO documents (org_id, workspace_id, title, file_name, file_type, 
                                 file_size_bytes, chunk_count, uploaded_by, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING document_id, created_at
        """, (
            current_user.get("org_id", 1),
            workspace_id,
            file.filename,
            file.filename,
            file.content_type or "application/octet-stream",
            0,  # file_size_bytes - would be actual size
            0,  # chunk_count - would be calculated after processing
            current_user.get("user_id", 1),
            True
        ))
        
        result = cursor.fetchone()
        document_id, created_at = result
        
        conn.commit()
        
        return DocumentUploadResponse(
            document_id=document_id,
            title=file.filename,
            file_name=file.filename,
            file_type=file.content_type or "application/octet-stream",
            file_size_bytes=0,
            chunk_count=0,
            created_at=created_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload document"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    page_size: int = 20,
    workspace_id: str = None,
    current_user: dict = Depends(get_current_user)
):
    """
    List all documents for the organization
    Optionally filter by workspace
    """
    from src.db.connection import DatabaseConnection
    from src.api.models import DocumentResponse
    
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Build query with optional workspace filter
        where_clause = "WHERE org_id = %s AND is_active = true"
        params = [current_user.get("org_id", 1)]
        
        if workspace_id:
            where_clause += " AND workspace_id = %s"
            params.append(workspace_id)
        
        # Get total count
        cursor.execute(f"SELECT COUNT(*) FROM documents {where_clause}", params)
        total = cursor.fetchone()[0]
        
        # Get documents with pagination
        offset = (page - 1) * page_size
        cursor.execute(f"""
            SELECT document_id, org_id, workspace_id, title, file_name, file_type,
                   file_size_bytes, chunk_count, is_active, created_at, updated_at
            FROM documents {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])
        
        documents = []
        for row in cursor.fetchall():
            documents.append(DocumentResponse(
                document_id=row[0],
                org_id=row[1],
                workspace_id=row[2],
                title=row[3],
                file_name=row[4],
                file_type=row[5],
                file_size_bytes=row[6],
                chunk_count=row[7],
                is_active=row[8],
                created_at=row[9],
                updated_at=row[10]
            ))
        
        return DocumentListResponse(
            documents=documents,
            total=total,
            page=page,
            page_size=page_size
        )
        
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list documents"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a document (soft delete)
    """
    # TODO: Implement document deletion
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Document deletion coming soon"
    )
