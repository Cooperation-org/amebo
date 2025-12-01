# API Documentation

🔌 **Amebo REST API** - Complete API reference with endpoints, authentication, and examples.

## 🔐 Authentication

All API endpoints require JWT authentication except for login and signup.

### Headers
```http
Authorization: Bearer <jwt_token>
Content-Type: application/json
```

### Authentication Flow
```http
POST /api/auth/login
{
  "email": "user@example.com",
  "password": "password123"
}

Response:
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "user": {
    "user_id": 1,
    "email": "user@example.com",
    "full_name": "John Doe",
    "org_id": 1,
    "role": "admin"
  }
}
```

## 📋 Base URL
```
Development: http://localhost:8000
Production: https://api.slackhelper.com
```

## 🔑 Authentication Endpoints

### POST /api/auth/login
User login with email and password.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "access_token": "jwt_token_here",
  "token_type": "bearer",
  "user": {
    "user_id": 1,
    "email": "user@example.com",
    "full_name": "John Doe",
    "org_id": 1,
    "role": "admin"
  }
}
```

### POST /api/auth/signup
Register new user and organization.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "password123",
  "full_name": "John Doe",
  "org_name": "Acme Corp"
}
```

**Response:**
```json
{
  "message": "User created successfully",
  "user_id": 1,
  "org_id": 1
}
```

### GET /api/auth/me
Get current user information.

**Response:**
```json
{
  "user_id": 1,
  "email": "user@example.com",
  "full_name": "John Doe",
  "org_id": 1,
  "role": "admin",
  "is_active": true
}
```

## 🏢 Workspace Endpoints

### GET /api/workspaces
List all workspaces for the organization.

**Response:**
```json
{
  "workspaces": [
    {
      "workspace_id": "T1234567890",
      "team_name": "Acme Team",
      "team_domain": "acme",
      "is_active": true,
      "installed_at": "2024-01-01T00:00:00Z",
      "status": "active",
      "message_count": 1250,
      "channel_count": 15
    }
  ],
  "total": 1
}
```

### POST /api/workspaces
Add new Slack workspace.

**Request:**
```json
{
  "workspace_name": "My Slack Team",
  "bot_token": "xoxb-your-bot-token",
  "app_token": "xapp-your-app-token",
  "signing_secret": "your-signing-secret"
}
```

**Response:**
```json
{
  "workspace_id": "T1234567890",
  "team_name": "My Slack Team",
  "status": "created",
  "backfill_started": true
}
```

### PUT /api/workspaces/{workspace_id}
Update workspace credentials.

**Request:**
```json
{
  "team_name": "Updated Team Name",
  "bot_token": "xoxb-new-bot-token",
  "app_token": "xapp-new-app-token",
  "signing_secret": "new-signing-secret"
}
```

### DELETE /api/workspaces/{workspace_id}
Delete workspace and all associated data.

**Response:**
```json
{
  "status": "deleted",
  "workspace_id": "T1234567890",
  "documents_deleted": 5,
  "collections_deleted": ["org_1_workspace_T1234567890"]
}
```

### POST /api/workspaces/{workspace_id}/backfill
Trigger manual message backfill.

**Request:**
```json
{
  "days_back": 30
}
```

**Response:**
```json
{
  "success": true,
  "workspace_id": "T1234567890",
  "days_back": 30,
  "status": "backfill_started"
}
```

### POST /api/workspaces/test-connection
Test Slack workspace connection.

**Request:**
```json
{
  "bot_token": "xoxb-test-token",
  "app_token": "xapp-test-token",
  "signing_secret": "test-signing-secret"
}
```

**Response:**
```json
{
  "success": true,
  "team_name": "Test Team",
  "team_domain": "test-team",
  "team_id": "T1234567890",
  "bot_user_id": "U1234567890",
  "channel_count": 10,
  "channels": [
    {
      "id": "C1234567890",
      "name": "general",
      "is_private": false
    }
  ]
}
```

## 🤖 Q&A Endpoints

### POST /api/qa/ask
Ask AI-powered question.

**Request:**
```json
{
  "question": "How do we deploy the application?",
  "workspace_id": "T1234567890",
  "channel_filter": "C1234567890",
  "days_back": 30,
  "include_documents": true,
  "include_slack": true,
  "max_sources": 5
}
```

**Response:**
```json
{
  "answer": "Based on the team discussions, the application is deployed using Docker containers...",
  "confidence": 0.85,
  "confidence_explanation": "High confidence based on multiple recent discussions about deployment",
  "sources": [
    {
      "source_type": "slack_message",
      "text": "We use Docker for deployment with the following steps...",
      "metadata": {
        "channel_id": "C1234567890",
        "channel_name": "dev-team",
        "user_id": "U1234567890",
        "timestamp": "2024-01-01T12:00:00Z",
        "message_url": "https://acme.slack.com/archives/C1234567890/p1234567890"
      },
      "relevance_score": 0.92
    }
  ],
  "question": "How do we deploy the application?",
  "processing_time_ms": 1500
}
```

## 📄 Document Endpoints

### POST /api/documents/upload
Upload documents for AI indexing.

**Request (multipart/form-data):**
```
files: [file1.pdf, file2.docx]
workspace_id: T1234567890 (optional)
```

**Response:**
```json
{
  "success": true,
  "uploaded_count": 2,
  "failed_count": 0,
  "results": [
    {
      "filename": "deployment-guide.pdf",
      "status": "indexed",
      "document_id": 1,
      "chunks_created": 15
    },
    {
      "filename": "api-docs.docx",
      "status": "indexed",
      "document_id": 2,
      "chunks_created": 8
    }
  ]
}
```

### GET /api/documents
List uploaded documents.

**Query Parameters:**
- `page`: Page number (default: 1)
- `page_size`: Items per page (default: 20)
- `workspace_id`: Filter by workspace (optional)

**Response:**
```json
{
  "documents": [
    {
      "id": "1",
      "filename": "deployment-guide.pdf",
      "file_type": "pdf",
      "file_size": 2048576,
      "status": "indexed",
      "upload_date": "2024-01-01T12:00:00Z",
      "workspace_id": "T1234567890"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### DELETE /api/documents/clear-all
Clear all documents for the organization.

**Response:**
```json
{
  "success": true,
  "documents_deleted": 10,
  "collections_deleted": ["org_1_workspace_T1234567890"]
}
```

## 👥 Team Management Endpoints

### GET /api/team/members
List team members.

**Response:**
```json
{
  "members": [
    {
      "user_id": 1,
      "email": "admin@example.com",
      "full_name": "Admin User",
      "role": "admin",
      "is_active": true,
      "created_at": "2024-01-01T00:00:00Z"
    },
    {
      "user_id": 2,
      "email": "member@example.com",
      "full_name": "Team Member",
      "role": "member",
      "is_active": true,
      "created_at": "2024-01-02T00:00:00Z"
    }
  ],
  "total": 2
}
```

### POST /api/team/invite
Invite new team member.

**Request:**
```json
{
  "email": "newuser@example.com",
  "role": "member"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Invitation sent successfully",
  "email": "newuser@example.com"
}
```

### PUT /api/team/members/{user_id}/role
Update user role.

**Request:**
```json
{
  "role": "admin"
}
```

**Response:**
```json
{
  "success": true,
  "user_id": 2,
  "new_role": "admin"
}
```

### PUT /api/team/members/{user_id}/deactivate
Deactivate user account.

**Response:**
```json
{
  "success": true,
  "user_id": 2,
  "status": "deactivated"
}
```

### DELETE /api/team/members/{user_id}
Permanently delete user.

**Response:**
```json
{
  "success": true,
  "user_id": 2,
  "status": "deleted"
}
```

## 📊 Error Responses

### Standard Error Format
```json
{
  "detail": "Error message description",
  "error_code": "SPECIFIC_ERROR_CODE",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### Common HTTP Status Codes

| Code | Description | Example |
|------|-------------|---------|
| 200 | Success | Request completed successfully |
| 201 | Created | Resource created successfully |
| 400 | Bad Request | Invalid request parameters |
| 401 | Unauthorized | Invalid or missing authentication |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource not found |
| 422 | Validation Error | Request validation failed |
| 429 | Rate Limited | Too many requests |
| 500 | Server Error | Internal server error |

### Example Error Responses

**401 Unauthorized:**
```json
{
  "detail": "Invalid authentication credentials",
  "error_code": "INVALID_TOKEN"
}
```

**422 Validation Error:**
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**404 Not Found:**
```json
{
  "detail": "Workspace not found",
  "error_code": "WORKSPACE_NOT_FOUND"
}
```

## 🔄 Rate Limiting

API endpoints are rate limited to prevent abuse:

- **Authentication**: 5 requests per minute per IP
- **Q&A**: 10 requests per minute per user
- **Document Upload**: 5 requests per minute per user
- **General API**: 100 requests per minute per user

Rate limit headers are included in responses:
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1640995200
```

## 📝 Request/Response Examples

### cURL Examples

**Login:**
```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123"}'
```

**Ask Question:**
```bash
curl -X POST "http://localhost:8000/api/qa/ask" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{"question": "How do we deploy?", "workspace_id": "T1234567890"}'
```

**Upload Document:**
```bash
curl -X POST "http://localhost:8000/api/documents/upload" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "files=@document.pdf" \
  -F "workspace_id=T1234567890"
```

## 🔧 SDK Examples

### JavaScript/TypeScript
```typescript
import { ApiClient } from './api-client';

const client = new ApiClient('http://localhost:8000');

// Login
const { access_token } = await client.login('user@example.com', 'password');
client.setToken(access_token);

// Ask question
const response = await client.askQuestion({
  question: 'How do we deploy the application?',
  workspace_id: 'T1234567890'
});

console.log(response.answer);
```

### Python
```python
import requests

class SlackHelperClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.token = None
    
    def login(self, email, password):
        response = requests.post(f"{self.base_url}/api/auth/login", 
                               json={"email": email, "password": password})
        data = response.json()
        self.token = data["access_token"]
        return data
    
    def ask_question(self, question, workspace_id=None):
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"question": question}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        
        response = requests.post(f"{self.base_url}/api/qa/ask", 
                               json=payload, headers=headers)
        return response.json()

# Usage
client = SlackHelperClient("http://localhost:8000")
client.login("user@example.com", "password123")
result = client.ask_question("How do we deploy?", "T1234567890")
print(result["answer"])
```

## 🔍 API Testing

### Interactive Documentation
Visit `http://localhost:8000/docs` for interactive Swagger UI documentation where you can test endpoints directly.

### Postman Collection
Import the Postman collection for easy API testing:
```json
{
  "info": {
    "name": "Amebo API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "auth": {
    "type": "bearer",
    "bearer": [{"key": "token", "value": "{{jwt_token}}"}]
  }
}
```