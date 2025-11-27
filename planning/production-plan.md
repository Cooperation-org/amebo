# 🚀 Slack Helper Bot - Production SaaS Plan

**Goal:** Transform the MVP into a complete, production-ready SaaS platform where businesses can sign up, manage workspaces, and use AI-powered Q&A.

**Timeline:** 6 weeks to launch

---

## 📊 Current State Analysis

### ✅ What's Working
- Backend API (FastAPI) with authentication
- Q&A service with improved formatting (citations, confidence, links)
- Slack Socket Mode integration
- ChromaDB + PostgreSQL hybrid storage
- User/organization management

### ❌ Critical Issues to Fix
1. **Fragmented Services:** Must run `start_slack_commands_simple.py` AND `src.run_server.py` separately
2. **Manual Backfill:** No automated data collection scheduling
3. **Workspace Isolation Risk:** Not fully verified - potential security vulnerability
4. **No Frontend:** Can only use via Slack or CLI scripts
5. **No Self-Service:** Can't add Slack credentials without editing .env

---

## 🎯 Production Requirements

### Backend Requirements
- ✅ Single unified process (one command to start everything)
- ✅ Automated scheduled backfills per organization
- ✅ Complete workspace data isolation (CRITICAL SECURITY)
- ✅ Encrypted credential storage
- ✅ Background task system
- ✅ Configurable AI settings per org

### Frontend Requirements
- ✅ User signup/login
- ✅ Organization onboarding with Slack credential input
- ✅ Web-based Q&A interface
- ✅ Workspace management UI
- ✅ Document upload interface
- ✅ Team management (invite users, roles)
- ✅ AI configuration settings
- ✅ Analytics dashboard

---

# 📅 6-Week Implementation Plan

## WEEK 1: Critical Backend Foundation 🔒

**Priority:** Security & Infrastructure

### Monday: Workspace Isolation Audit (CRITICAL)

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create workspace isolation test suite
- [ ] Test: Org A cannot query Org B's workspace data
- [ ] Test: ChromaDB filters by workspace_id correctly
- [ ] Test: API routes verify workspace ownership
- [ ] Fix any isolation vulnerabilities found

**Files to Create/Update:**
- `tests/test_workspace_isolation.py`
- `src/services/qa_service.py` (enforce workspace_id)
- `src/api/middleware/workspace_auth.py`

**Acceptance Criteria:**
- ✅ All isolation tests pass
- ✅ No cross-workspace data leakage possible
- ✅ API returns 403 for unauthorized workspace access

---

### Tuesday-Wednesday: Unified Backend Runner

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create `src/main.py` - single entry point
- [ ] Integrate FastAPI server startup
- [ ] Integrate Slack Socket Mode listener
- [ ] Add graceful shutdown handling
- [ ] Add health check endpoint
- [ ] Update documentation

**Implementation:**
```python
# src/main.py
async def main():
    """Start all services in single process"""
    # 1. Start APScheduler
    # 2. Start Slack listener (background)
    # 3. Start FastAPI server
```

**Files to Create/Update:**
- `src/main.py` (new)
- `src/services/slack_commands_simple.py` (make async-compatible)
- `README.md` (update startup instructions)

**Acceptance Criteria:**
- ✅ `python -m src.main` starts everything
- ✅ All services run concurrently
- ✅ Graceful shutdown on Ctrl+C
- ✅ Health check returns status of all services

---

### Thursday: Background Task System

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Install APScheduler
- [ ] Create `TaskScheduler` class
- [ ] Implement scheduled backfill jobs
- [ ] Load schedules from database on startup
- [ ] Add job status tracking
- [ ] Create admin endpoint to trigger manual backfill

**Files to Create/Update:**
- `src/services/scheduler.py` (new)
- `src/api/routes/admin.py` (new - trigger backfills)
- `requirements.txt` (add APScheduler)

**Database Schema:**
```sql
CREATE TABLE scheduled_jobs (
    job_id SERIAL PRIMARY KEY,
    org_id INT REFERENCES organizations(org_id),
    workspace_id VARCHAR(20) REFERENCES workspaces(workspace_id),
    job_type VARCHAR(50) NOT NULL,
    schedule_pattern VARCHAR(50) NOT NULL, -- cron format
    is_active BOOLEAN DEFAULT true,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    last_status VARCHAR(50),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Acceptance Criteria:**
- ✅ Backfills run automatically per schedule
- ✅ Schedules stored in database
- ✅ Failed jobs retry with exponential backoff
- ✅ Job status visible via API

---

### Friday: Database Schema Updates & Credential Storage

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create encryption utility functions
- [ ] Add `workspace_credentials` table
- [ ] Add `org_settings` table
- [ ] Create migration script
- [ ] Test credential encryption/decryption

**Files to Create/Update:**
- `src/utils/encryption.py` (new)
- `migrations/006_add_settings_tables.sql` (new)
- `src/api/routes/workspaces.py` (add credential endpoints)

**Database Schema:**
```sql
CREATE TABLE workspace_credentials (
    workspace_id VARCHAR(20) PRIMARY KEY REFERENCES workspaces(workspace_id),
    bot_token_encrypted TEXT NOT NULL,
    app_token_encrypted TEXT NOT NULL,
    signing_secret_encrypted TEXT NOT NULL,
    bot_user_id VARCHAR(20),
    is_valid BOOLEAN DEFAULT true,
    last_verified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE org_settings (
    org_id INT PRIMARY KEY REFERENCES organizations(org_id),
    -- AI Configuration
    ai_tone VARCHAR(50) DEFAULT 'professional',
    ai_response_length VARCHAR(50) DEFAULT 'balanced',
    confidence_threshold INT DEFAULT 40,
    custom_system_prompt TEXT,
    -- Backfill Settings
    backfill_schedule VARCHAR(50) DEFAULT '0 2 * * *',
    backfill_days_back INT DEFAULT 90,
    auto_backfill_enabled BOOLEAN DEFAULT true,
    -- Feature Flags
    slack_commands_enabled BOOLEAN DEFAULT true,
    web_qa_enabled BOOLEAN DEFAULT true,
    document_upload_enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**Acceptance Criteria:**
- ✅ Credentials encrypted at rest
- ✅ API endpoints to add/update credentials
- ✅ Settings table supports all config options
- ✅ Migration runs successfully

---

## WEEK 2: Frontend Foundation + Auth 🎨

**Priority:** Get users in the system

### Monday-Tuesday: Next.js Project Setup

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create Next.js 14 app with TypeScript
- [ ] Install dependencies (TanStack Query, Zustand, shadcn/ui)
- [ ] Setup Tailwind CSS configuration
- [ ] Create project structure
- [ ] Setup environment variables
- [ ] Create API client utility

**Tech Stack:**
- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS + shadcn/ui
- TanStack Query (data fetching)
- Zustand (state management)

**Project Structure:**
```
frontend/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── signup/page.tsx
│   ├── (dashboard)/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── qa/page.tsx
│   │   ├── workspaces/page.tsx
│   │   ├── documents/page.tsx
│   │   ├── team/page.tsx
│   │   └── settings/page.tsx
│   └── layout.tsx
├── components/
│   ├── ui/              # shadcn components
│   └── dashboard/
├── lib/
│   ├── api.ts
│   └── auth.ts
└── store/
    └── useAuthStore.ts
```

**Acceptance Criteria:**
- ✅ Project builds without errors
- ✅ Tailwind styling works
- ✅ Basic routing configured
- ✅ API client connects to backend

---

### Wednesday-Thursday: Authentication Pages

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Build signup page UI
- [ ] Build login page UI
- [ ] Implement form validation (react-hook-form)
- [ ] Connect to backend auth API
- [ ] Setup JWT token storage
- [ ] Create auth context/store
- [ ] Implement protected route wrapper

**Pages to Build:**
- `app/(auth)/signup/page.tsx` - User signup with org creation
- `app/(auth)/login/page.tsx` - User login
- `components/ProtectedRoute.tsx` - Auth guard

**Features:**
- Email/password signup
- Organization name input during signup
- JWT token storage in httpOnly cookies
- Auto-redirect to dashboard after login
- Logout functionality

**Acceptance Criteria:**
- ✅ Users can sign up and create org
- ✅ Users can log in
- ✅ JWT token stored securely
- ✅ Protected routes redirect to login
- ✅ Form validation works

---

### Friday: Onboarding Flow

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create onboarding wizard UI
- [ ] Build "Add Slack Workspace" form
- [ ] Add connection test functionality
- [ ] Create success/error states
- [ ] Add skip option (add workspace later)

**Components:**
- `components/onboarding/SlackWorkspaceForm.tsx`
- `components/onboarding/OnboardingWizard.tsx`

**Form Fields:**
- Workspace Name
- Bot Token (xoxb-...)
- App Token (xapp-...)
- Signing Secret
- Test Connection button

**Flow:**
1. User signs up
2. Redirected to onboarding
3. "Let's connect your Slack workspace"
4. Input credentials
5. Test connection
6. Save → Redirect to dashboard

**Acceptance Criteria:**
- ✅ Clean, intuitive UI
- ✅ Credentials validated before save
- ✅ Connection test works
- ✅ Error handling for invalid tokens
- ✅ Can skip and add workspace later

---

## WEEK 3: Q&A Interface (Main Feature) 💬

**Priority:** Core value proposition

### Monday-Tuesday: Q&A UI Components

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Build question input component
- [ ] Build answer display component
- [ ] Create source card component
- [ ] Add loading states
- [ ] Add error states
- [ ] Build filter sidebar

**Components:**
```
components/qa/
├── QuestionInput.tsx      # Text input with submit
├── AnswerDisplay.tsx      # Answer with confidence, sources
├── SourceCard.tsx         # Individual source message
├── ConfidenceBadge.tsx    # Visual confidence indicator
├── FilterSidebar.tsx      # Channel, date filters
└── QueryHistory.tsx       # Recent questions
```

**Design Features:**
- Auto-expanding textarea for questions
- Markdown rendering for answers
- Collapsible sources section
- Copy answer button
- Share link button
- Confidence visualization (progress bar + color)

**Acceptance Criteria:**
- ✅ Professional, clean UI
- ✅ Responsive design
- ✅ Accessible (ARIA labels)
- ✅ Smooth animations

---

### Wednesday-Thursday: Q&A Integration

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Connect to Q&A API endpoint
- [ ] Implement workspace selector
- [ ] Add channel filter
- [ ] Add date range filter
- [ ] Implement query history
- [ ] Add bookmark feature
- [ ] Create share functionality

**API Integration:**
```typescript
// lib/api/qa.ts
export async function askQuestion(params: {
  question: string;
  workspace_id: string;
  channel_filter?: string;
  days_back?: number;
}) {
  return apiClient.post('/api/qa/ask', params);
}
```

**Features:**
- Workspace dropdown (shows all user's workspaces)
- Channel filter (auto-populate from workspace)
- Date range picker
- Save queries to history
- Bookmark favorite answers
- Generate shareable link

**Acceptance Criteria:**
- ✅ Questions get answered correctly
- ✅ Filters work properly
- ✅ History persists
- ✅ Bookmarks save
- ✅ Share links work

---

### Friday: Q&A Polish & Testing

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Add keyboard shortcuts (Cmd+K to focus input)
- [ ] Implement citation click-to-highlight
- [ ] Add project links display
- [ ] Optimize performance
- [ ] Write E2E tests
- [ ] Fix bugs

**Enhancements:**
- Cmd+Enter to submit question
- Click source to expand full message
- Display extracted GitHub/docs links
- Lazy load query history
- Debounce search inputs

**Acceptance Criteria:**
- ✅ Fast, snappy UX
- ✅ No console errors
- ✅ Tests passing
- ✅ Works on mobile

---

## WEEK 4: Workspace Management 🔧

**Priority:** Self-service workspace setup

### Monday-Tuesday: Workspace List & Details

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create workspace list page
- [ ] Build workspace card component
- [ ] Show sync status
- [ ] Display message counts
- [ ] Add last sync timestamp
- [ ] Create workspace detail view

**Page:** `app/(dashboard)/workspaces/page.tsx`

**Features:**
- Grid/list view toggle
- Search workspaces
- Filter by status (active, syncing, error)
- Sort by name, messages, last sync
- Quick stats (messages, channels, users)

**Workspace Card Shows:**
- Workspace name
- Status badge (✅ Active, 🔄 Syncing, ❌ Error)
- Message count
- Last sync time
- Quick actions (Edit, Delete, Sync Now)

**Acceptance Criteria:**
- ✅ All workspaces displayed
- ✅ Real-time status updates
- ✅ Fast search/filter
- ✅ Clean, organized UI

---

### Wednesday: Add/Edit Workspace

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Build "Add Workspace" modal
- [ ] Create edit workspace form
- [ ] Implement credential update
- [ ] Add connection test
- [ ] Handle validation errors

**Components:**
- `components/workspaces/AddWorkspaceModal.tsx`
- `components/workspaces/EditWorkspaceForm.tsx`

**Features:**
- Add new workspace (same as onboarding)
- Edit existing workspace
- Update credentials (masked display)
- Re-test connection
- Delete workspace (with confirmation)

**Security:**
- Tokens shown as `xoxb-***-***-***` (masked)
- "Reveal" button to show full token
- Confirm password before showing tokens

**Acceptance Criteria:**
- ✅ Can add new workspaces
- ✅ Can edit existing workspaces
- ✅ Credentials update successfully
- ✅ Secure token handling

---

### Thursday-Friday: Backfill Configuration

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create schedule configuration UI
- [ ] Build cron expression builder
- [ ] Add manual trigger button
- [ ] Show backfill history
- [ ] Display job status

**Components:**
- `components/workspaces/BackfillScheduler.tsx`
- `components/workspaces/BackfillHistory.tsx`

**Features:**
- Visual cron builder (or predefined options)
  - Daily at 2 AM
  - Every 6 hours
  - Every hour
  - Custom cron expression
- Manual "Sync Now" button
- Backfill history table (last 10 runs)
- Status indicators (✅ Success, 🔄 Running, ❌ Failed)

**Backfill History Shows:**
- Started at
- Completed at
- Duration
- Messages synced
- Status
- Error details (if failed)

**Acceptance Criteria:**
- ✅ Schedule updates save correctly
- ✅ Manual sync triggers immediately
- ✅ History displays accurately
- ✅ Errors shown clearly

---

## WEEK 5: Settings & Team Management ⚙️

**Priority:** Configuration & collaboration

### Monday-Tuesday: AI Settings Page

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create settings page layout
- [ ] Build AI configuration form
- [ ] Add tone selector
- [ ] Add response length slider
- [ ] Add confidence threshold
- [ ] Implement custom instructions
- [ ] Add save/reset functionality

**Page:** `app/(dashboard)/settings/page.tsx`

**Settings Categories:**

**AI Configuration:**
- Tone: Professional | Casual | Technical
- Response Length: Concise | Balanced | Detailed
- Confidence Threshold: 0-100 slider
- Custom System Prompt: Textarea

**Data & Privacy:**
- Message retention period (days)
- Delete old messages button
- Export data button

**Notifications:**
- Email notifications for failed backfills
- Weekly digest email

**Acceptance Criteria:**
- ✅ Settings save successfully
- ✅ Changes reflect in Q&A immediately
- ✅ Form validation works
- ✅ Reset to defaults option

---

### Wednesday: Team Management - List & Roles

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create team page
- [ ] List all organization users
- [ ] Display user roles
- [ ] Show user status
- [ ] Add role change functionality

**Page:** `app/(dashboard)/team/page.tsx`

**User Table Columns:**
- Avatar + Name
- Email
- Role (Admin, Member, Viewer)
- Status (Active, Pending, Inactive)
- Last active
- Actions (Edit role, Remove)

**Role Descriptions:**
- **Admin:** Full access, can invite users, manage settings
- **Member:** Can use Q&A, upload documents
- **Viewer:** Read-only access to answers

**Acceptance Criteria:**
- ✅ All users displayed
- ✅ Role changes work
- ✅ Cannot remove last admin
- ✅ Proper permissions enforced

---

### Thursday-Friday: Team Invitations

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Build invite user modal
- [ ] Create invitation email template
- [ ] Implement invite link generation
- [ ] Add pending invitations section
- [ ] Create accept invitation flow

**Components:**
- `components/team/InviteUserModal.tsx`
- `components/team/PendingInvitations.tsx`
- `app/accept-invite/[token]/page.tsx`

**Invite Flow:**
1. Admin enters email + role
2. System generates invite token
3. Email sent with invite link
4. Recipient clicks link
5. If has account → Join org
6. If no account → Signup → Join org

**Email Template:**
```
Subject: You've been invited to join [Org Name] on Slack Helper Bot

[Admin Name] has invited you to join [Org Name]'s workspace.

Click here to accept: [Link]

Role: Member
```

**Acceptance Criteria:**
- ✅ Invites sent successfully
- ✅ Email delivered
- ✅ Invite links work
- ✅ Users join organization
- ✅ Can revoke pending invites

---

## WEEK 6: Polish, Testing & Deployment 🚀

**Priority:** Production readiness

### Monday-Tuesday: Document Upload

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create documents page
- [ ] Build file upload component
- [ ] Implement drag-and-drop
- [ ] Show upload progress
- [ ] List uploaded documents
- [ ] Add delete functionality

**Page:** `app/(dashboard)/documents/page.tsx`

**Features:**
- Drag & drop file upload
- Support PDF, DOCX, TXT
- Progress bar during upload
- Document list with:
  - File name
  - Type (PDF, DOCX)
  - Size
  - Upload date
  - Status (Indexed, Processing, Failed)
- Delete with confirmation

**Acceptance Criteria:**
- ✅ Upload works for all file types
- ✅ Progress shown accurately
- ✅ Documents indexed correctly
- ✅ Searchable in Q&A

---

### Wednesday: Dashboard Overview Page

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Create dashboard home page
- [ ] Add stats cards
- [ ] Build recent activity feed
- [ ] Add quick actions
- [ ] Create charts (optional)

**Page:** `app/(dashboard)/page.tsx`

**Widgets:**

**Stats Cards:**
- Total Workspaces
- Total Messages Indexed
- Queries This Month
- Documents Uploaded

**Recent Activity:**
- Recent Q&A queries
- Recent backfill jobs
- Recent team invitations

**Quick Actions:**
- Ask a Question (→ Q&A page)
- Add Workspace
- Upload Document
- Invite Team Member

**Acceptance Criteria:**
- ✅ Stats accurate
- ✅ Activity updates in real-time
- ✅ Quick actions work
- ✅ Responsive layout

---

### Thursday: Bug Fixes & Polish

**Status:** 🔴 Not Started

**Tasks:**
- [ ] Fix all console warnings
- [ ] Test all user flows
- [ ] Fix responsive design issues
- [ ] Optimize images
- [ ] Add loading skeletons
- [ ] Improve error messages
- [ ] Add success toasts

**Testing Checklist:**
- [ ] Signup → Onboarding → Dashboard flow
- [ ] Add workspace → Test connection
- [ ] Ask question → Get answer
- [ ] Invite user → User accepts
- [ ] Upload document → Document indexed
- [ ] Change settings → Settings applied
- [ ] Mobile responsiveness
- [ ] Browser compatibility (Chrome, Firefox, Safari)

**Acceptance Criteria:**
- ✅ Zero console errors
- ✅ All flows work smoothly
- ✅ Fast page loads
- ✅ Professional UX

---

### Friday: Deployment

**Status:** 🔴 Not Started

**Backend Deployment (Railway/Render):**
- [ ] Create Dockerfile
- [ ] Setup environment variables
- [ ] Configure PostgreSQL
- [ ] Configure ChromaDB persistence
- [ ] Setup Redis (if using Celery)
- [ ] Deploy backend
- [ ] Run migrations
- [ ] Test API endpoints

**Frontend Deployment (Vercel):**
- [ ] Connect GitHub repo
- [ ] Configure environment variables
- [ ] Deploy to production
- [ ] Setup custom domain (optional)
- [ ] Configure CORS

**Post-Deployment:**
- [ ] Setup monitoring (Sentry)
- [ ] Configure logging
- [ ] Setup database backups
- [ ] Create admin user
- [ ] Test production environment

**Acceptance Criteria:**
- ✅ Backend deployed and accessible
- ✅ Frontend deployed and accessible
- ✅ Database migrations applied
- ✅ HTTPS enabled
- ✅ No deployment errors

---

## 📊 Success Metrics

**Week 1:** Backend solid and secure
- ✅ Workspace isolation verified
- ✅ Single command starts all services
- ✅ Automated backfills running

**Week 2-3:** Users can get in and use core feature
- ✅ Signup/login working
- ✅ Onboarding smooth
- ✅ Q&A interface functional

**Week 4-5:** Self-service management
- ✅ Users can add/manage workspaces
- ✅ Team collaboration enabled
- ✅ Settings customizable

**Week 6:** Production ready
- ✅ All features working
- ✅ Deployed to production
- ✅ Ready for beta users

---

## 🎯 Definition of Done (Phase 1 Complete)

### Backend Checklist
- [ ] Single `python -m src.main` starts all services
- [ ] Workspace data isolation fully verified and tested
- [ ] Automatic scheduled backfills per organization
- [ ] Encrypted credential storage implemented
- [ ] AI settings configurable via API
- [ ] Background task system operational
- [ ] All API endpoints documented

### Frontend Checklist
- [ ] User signup/login functional
- [ ] Onboarding flow with Slack credential input
- [ ] Web-based Q&A interface working perfectly
- [ ] Workspace management (add/edit/delete)
- [ ] Document upload working
- [ ] Team management (invite, roles) functional
- [ ] Settings page for AI configuration
- [ ] Dashboard overview page
- [ ] Mobile responsive

### Production Checklist
- [ ] Backend deployed to production
- [ ] Frontend deployed to production
- [ ] HTTPS enabled
- [ ] Database backups configured
- [ ] Monitoring/logging setup (Sentry)
- [ ] Error tracking working
- [ ] Performance acceptable (<2s page loads)
- [ ] Security audit passed

### Documentation Checklist
- [ ] README updated with new setup instructions
- [ ] API documentation complete
- [ ] User guide created
- [ ] Admin guide created
- [ ] Deployment guide written

---

## 🚧 Known Issues & Technical Debt

### Current Known Issues
1. User names not populated in message metadata (empty strings)
   - **Impact:** Sources show "unknown" user
   - **Fix:** Update backfill to resolve user_id → user_name

2. ChromaDB not synced with recent PostgreSQL messages
   - **Impact:** Recent messages not searchable
   - **Fix:** Ensure backfill writes to both DBs

3. Slack emoji codes sometimes not cleaned from answers
   - **Impact:** Answers show `:emoji_code:` instead of emoji
   - **Fix:** Improve regex cleanup in qa_service.py

### Technical Debt to Address
- [ ] Add rate limiting to API endpoints
- [ ] Implement request caching
- [ ] Add database indexes for common queries
- [ ] Setup CI/CD pipeline
- [ ] Add E2E test suite
- [ ] Improve error handling in async tasks
- [ ] Add API versioning
- [ ] Implement feature flags system

---

## 🔄 Next Steps After Phase 1

### Phase 2: Advanced Features
- Slack Marketplace OAuth (replace manual credentials)
- Newsletter generation
- PR review automation
- Analytics dashboard with charts
- Export data functionality
- Webhook integrations
- Slack app directory listing

### Phase 3: Scale & Optimize
- Multi-region deployment
- Advanced caching layer
- Vector search optimization
- Custom LLM fine-tuning
- Enterprise features (SSO, audit logs)
- White-label options

---

## 📝 Notes & Decisions

### Technology Choices
- **Backend:** FastAPI (async, fast, good docs)
- **Frontend:** Next.js 14 (React, SSR, great DX)
- **Styling:** Tailwind + shadcn/ui (rapid development)
- **State:** Zustand (simple, lightweight)
- **Data Fetching:** TanStack Query (powerful, cached)
- **Task Scheduler:** APScheduler (Python-native, simple)
- **Database:** PostgreSQL + ChromaDB (hybrid storage)

### Security Decisions
- JWT tokens in httpOnly cookies (XSS protection)
- Encrypted credentials at rest (Fernet)
- Workspace isolation enforced at every layer
- Rate limiting on auth endpoints
- CORS properly configured
- SQL injection prevention (parameterized queries)

### Architecture Decisions
- Single unified backend process (simpler deployment)
- API-first design (frontend agnostic)
- Event-driven background tasks (scalable)
- Workspace-scoped everything (multi-tenancy)

---

## 📞 Questions & Blockers

### Open Questions
- [ ] Do we need Slack Marketplace OAuth now, or manual credentials OK for Phase 1?
  - **Answer:** Manual credentials for Phase 1

- [ ] What's the pricing model? (affects usage tracking)
  - **Answer:** TBD - need product decision

- [ ] Do we need real-time notifications? (websockets)
  - **Answer:** Not for Phase 1 - polling is fine

### Current Blockers
- None - ready to start!

---

**Last Updated:** 2025-11-24
**Status:** Planning Complete - Ready to Begin Week 1
**Next Action:** Start workspace isolation audit (Monday)
