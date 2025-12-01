"""
Documents routes - upload, list, delete documents
"""

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form
from typing import List, Optional
import logging

from src.api.middleware.auth import get_current_user
from src.services.document_service import DocumentService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
    workspace_id: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload multiple documents (PDF, DOCX, TXT, MD)
    Processes and stores in ChromaDB
    Can be tagged to a specific workspace
    """
    from src.db.connection import DatabaseConnection
    
    try:
        # Verify workspace if provided
        if workspace_id:
            conn = DatabaseConnection.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT workspace_id FROM workspaces 
                WHERE workspace_id = %s AND org_id = %s AND is_active = true
            """, (workspace_id, current_user.get("org_id", 8)))
            
            if not cursor.fetchone():
                cursor.close()
                DatabaseConnection.return_connection(conn)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or inactive workspace"
                )
            
            cursor.close()
            DatabaseConnection.return_connection(conn)
        
        # Prepare file data
        file_data_list = []
        for file in files:
            content = await file.read()
            file_data_list.append({
                'filename': file.filename,
                'content_type': file.content_type,
                'content': content
            })
        
        # Process documents
        document_service = DocumentService()
        results = await document_service.process_documents(
            file_data_list,
            org_id=current_user.get("org_id", 8),
            user_id=current_user.get("user_id", 1),
            workspace_id=workspace_id
        )
        
        return {
            "success": True,
            "uploaded_count": len([r for r in results if r.get('status') == 'indexed']),
            "failed_count": len([r for r in results if r.get('status') == 'failed']),
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload documents: {str(e)}"
        )


@router.get("/")
async def list_documents(
    page: int = 1,
    page_size: int = 20,
    workspace_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    List all documents for the organization
    Optionally filter by workspace
    """
    from src.db.connection import DatabaseConnection
    
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Build query with optional workspace filter
        where_clause = "WHERE org_id = %s AND is_active = true"
        params = [current_user.get("org_id", 8)]
        
        if workspace_id:
            where_clause += " AND workspace_id = %s"
            params.append(workspace_id)
        
        # Get total count
        cursor.execute(f"SELECT COUNT(*) FROM documents {where_clause}", params)
        total = cursor.fetchone()[0]
        
        # Get documents with pagination
        offset = (page - 1) * page_size
        cursor.execute(f"""
            SELECT document_id, workspace_id, title, file_name, file_type,
                   file_size_bytes, chunk_count, created_at
            FROM documents {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])
        
        documents = []
        for row in cursor.fetchall():
            # Determine status based on chunk_count
            status = 'indexed' if row[6] > 0 else 'processing'
            
            documents.append({
                'id': str(row[0]),
                'filename': row[3],
                'file_type': row[4].split('/')[-1] if '/' in row[4] else row[4],
                'file_size': row[5],
                'status': status,
                'upload_date': row[7].isoformat() if row[7] else None,
                'workspace_id': row[1]
            })
        
        return {
            'documents': documents,
            'total': total,
            'page': page,
            'page_size': page_size
        }
        
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


@router.delete("/clear-all")
async def clear_all_documents(
    current_user: dict = Depends(get_current_user)
):
    """
    Clear all documents for the organization
    """
    from src.db.connection import DatabaseConnection
    
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Get ChromaDB collections to clean up
        cursor.execute("""
            SELECT chromadb_collection FROM documents 
            WHERE org_id = %s AND chromadb_collection IS NOT NULL
        """, (current_user.get("org_id", 8),))
        
        collections_to_delete = [row[0] for row in cursor.fetchall()]
        
        # Delete all documents for the organization
        cursor.execute("""
            DELETE FROM documents WHERE org_id = %s
        """, (current_user.get("org_id", 8),))
        
        deleted_count = cursor.rowcount
        conn.commit()
        
        # Clean up ChromaDB collections
        deleted_collections = []
        try:
            import chromadb
            chroma_client = chromadb.PersistentClient(path='./chroma_db')
            existing_collections = [col.name for col in chroma_client.list_collections()]
            
            for collection_name in collections_to_delete:
                if collection_name in existing_collections:
                    chroma_client.delete_collection(collection_name)
                    deleted_collections.append(collection_name)
                    logger.info(f"Deleted ChromaDB collection: {collection_name}")
        except Exception as chroma_error:
            logger.warning(f"ChromaDB cleanup failed: {chroma_error}")
        
        return {
            "success": True,
            "documents_deleted": deleted_count,
            "collections_deleted": deleted_collections
        }
        
    except Exception as e:
        logger.error(f"Error clearing documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear documents"
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
