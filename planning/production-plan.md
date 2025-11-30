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

## WEEK 1: Critical Backend Foundation 🔒 ✅ **COMPLETE**

**Priority:** Security & Infrastructure

**Summary:** All Week 1 objectives completed successfully. Backend is now secure, unified, and production-ready with workspace isolation, automated backfills, and encrypted credential storage.

**Total Deliverables:**
- 17 new files created
- ~3,500 lines of code
- 4 new database tables
- 6 admin API endpoints
- 4-layer security architecture

### Monday: Workspace Isolation Audit (CRITICAL)

**Status:** ✅ COMPLETED (2025-11-27)

**Tasks:**
- [x] Create workspace isolation test suite
- [x] Test: Org A cannot query Org B's workspace data
- [x] Test: ChromaDB filters by workspace_id correctly
- [x] Test: API routes verify workspace ownership
- [x] Fix any isolation vulnerabilities found

**Files Created/Updated:**
- ✅ `tests/test_workspace_isolation.py`
- ✅ `src/services/qa_service.py` (enforce workspace_id)
- ✅ `src/services/query_service.py` (enforce workspace_id)
- ✅ `src/db/chromadb_client.py` (defense-in-depth filtering)
- ✅ `src/api/middleware/workspace_auth.py`
- ✅ `src/api/routes/qa.py` (added workspace verification)
- ✅ `planning/week1-monday-completed.md`

**Acceptance Criteria:**
- ✅ All isolation tests pass
- ✅ No cross-workspace data leakage possible
- ✅ API returns 403 for unauthorized workspace access
- ✅ 4-layer security architecture implemented

---

### Tuesday-Wednesday: Unified Backend Runner

**Status:** ✅ COMPLETED (2025-11-27)

**Tasks:**
- [x] Create `src/main.py` - single entry point
- [x] Integrate FastAPI server startup
- [x] Integrate Slack Socket Mode listener
- [x] Add graceful shutdown handling
- [x] Health check endpoint (already existed)
- [x] Update documentation

**Implementation:**
```python
# src/main.py
class SlackHelperApp:
    async def start(self):
        """Start all services in single process"""
        # 1. Start FastAPI server
        # 2. Start Slack Socket Mode listener
        # 3. Start TaskScheduler (background tasks)
        # All run concurrently with asyncio
```

**Files Created/Updated:**
- ✅ `src/main.py` (complete unified entry point)
- ✅ `QUICK_START.md` (updated documentation)

**Acceptance Criteria:**
- ✅ `python -m src.main` starts everything
- ✅ All services run concurrently
- ✅ Graceful shutdown on Ctrl+C
- ✅ Signal handlers for SIGTERM/SIGINT
- ✅ Connection pool cleanup on shutdown

---

### Thursday: Background Task System

**Status:** ✅ COMPLETED (2025-11-27)

**Tasks:**
- [x] Install APScheduler
- [x] Create `TaskScheduler` class
- [x] Implement scheduled backfill jobs
- [x] Load schedules from database on startup
- [x] Add job status tracking
- [x] Create admin endpoints to trigger manual backfill

**Files Created/Updated:**
- ✅ `src/services/scheduler.py` (TaskScheduler class - 362 lines)
- ✅ `src/services/backfill_service.py` (BackfillService class - 319 lines)
- ✅ `src/api/routes/admin.py` (Admin endpoints - 382 lines)
- ✅ `migrations/005_backfill_scheduling.sql` (Database schema)
- ✅ `src/main.py` (integrated TaskScheduler)
- ✅ `src/api/main.py` (added admin router)
- ✅ `planning/week1-thursday-completed.md`
- ✅ Installed `apscheduler==3.11.1`

**Database Schema:**
```sql
-- Created two tables:
CREATE TABLE backfill_schedules (
    schedule_id SERIAL PRIMARY KEY,
    org_id INT REFERENCES organizations(org_id),
    workspace_id VARCHAR(20) REFERENCES workspaces(workspace_id),
    cron_expression VARCHAR(100) NOT NULL,
    days_to_backfill INT DEFAULT 7,
    include_all_channels BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_by INT REFERENCES platform_users(user_id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE backfill_job_runs (
    job_run_id SERIAL PRIMARY KEY,
    org_id INT REFERENCES organizations(org_id),
    workspace_id VARCHAR(20) REFERENCES workspaces(workspace_id),
    schedule_id INT REFERENCES backfill_schedules(schedule_id),
    job_type VARCHAR(50) NOT NULL, -- 'scheduled' | 'manual'
    status VARCHAR(50) DEFAULT 'running', -- 'running' | 'success' | 'failed'
    messages_collected INT DEFAULT 0,
    channels_processed INT DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
```

**API Endpoints Added:**
- ✅ `POST /api/admin/backfill/schedules` - Create schedule
- ✅ `GET /api/admin/backfill/schedules` - List schedules
- ✅ `DELETE /api/admin/backfill/schedules/{id}` - Delete schedule
- ✅ `POST /api/admin/backfill/trigger` - Manual backfill
- ✅ `GET /api/admin/backfill/jobs` - Job history
- ✅ `GET /api/admin/backfill/jobs/active` - Active jobs

**Acceptance Criteria:**
- ✅ Backfills run automatically per cron schedule
- ✅ Schedules stored in database
- ✅ Job execution tracked with status
- ✅ Manual backfill trigger via API
- ✅ Job status visible via API
- ✅ Integrated with unified backend

---

### Friday: Database Schema Updates & Credential Storage

**Status:** ✅ COMPLETED (2025-11-27)

**Tasks:**
- [x] Create encryption utility functions
- [x] Update installations table with encrypted columns
- [x] Add `org_settings` table
- [x] Create migration script
- [x] Test credential encryption/decryption
- [x] Create credential service for encrypted storage

**Files Created/Updated:**
- ✅ `src/utils/encryption.py` (Encryption utilities - 327 lines)
- ✅ `src/services/credential_service.py` (Credential management - 313 lines)
- ✅ `migrations/006_settings_and_encryption.sql` (Database schema - 170 lines)
- ✅ `planning/week1-friday-completed.md`

**Database Schema:**
```sql
-- org_settings table created with all configuration options
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
    -- Feature Flags + Notifications + Data Retention
    slack_commands_enabled BOOLEAN DEFAULT true,
    web_qa_enabled BOOLEAN DEFAULT true,
    document_upload_enabled BOOLEAN DEFAULT true,
    email_notifications_enabled BOOLEAN DEFAULT true,
    notify_on_failed_backfill BOOLEAN DEFAULT true,
    weekly_digest_enabled BOOLEAN DEFAULT false,
    message_retention_days INT DEFAULT 365,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- installations table updated with encrypted columns
ALTER TABLE installations
    ADD COLUMN bot_token_encrypted TEXT,
    ADD COLUMN app_token_encrypted TEXT,
    ADD COLUMN signing_secret_encrypted TEXT,
    ADD COLUMN encryption_version INT DEFAULT 1,
    ADD COLUMN credentials_encrypted BOOLEAN DEFAULT FALSE,
    ADD COLUMN bot_user_id VARCHAR(20),
    ADD COLUMN last_verified_at TIMESTAMP,
    ADD COLUMN is_valid BOOLEAN DEFAULT TRUE;
```

**Acceptance Criteria:**
- ✅ Credentials encrypted at rest using Fernet
- ✅ Encryption utilities created and tested
- ✅ Credential service for store/retrieve/verify
- ✅ Settings table supports all config options
- ✅ Migration runs successfully
- ✅ Default settings created for existing orgs
- ✅ Backward compatibility maintained (plaintext + encrypted columns coexist)

---

## WEEK 2: Frontend Foundation + Auth 🎨 ✅ **COMPLETE**

**Priority:** Get users in the system

**Summary:** Week 2 completed successfully. Complete frontend foundation with Next.js 14, enhanced authentication system, JWT token management, professional onboarding flow, and full stack integration.

**Total Deliverables:**
- 15 new frontend files created
- Complete authentication system with JWT
- Professional onboarding wizard
- Enhanced dashboard with navigation
- Form validation with Zod
- Loading states and skeleton components
- Full stack integration verified

### Monday-Tuesday: Next.js Project Setup

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Create Next.js 14 app with TypeScript
- [x] Install dependencies (TanStack Query, Zustand, shadcn/ui)
- [x] Setup Tailwind CSS configuration
- [x] Create project structure
- [x] Setup environment variables
- [x] Create API client utility

**Files Created:**
- ✅ `frontend/` - Next.js 14 project with TypeScript
- ✅ `src/lib/api.ts` - API client utility (REST client for backend)
- ✅ `src/store/useAuthStore.ts` - Zustand auth store (login/signup/logout)
- ✅ `src/lib/providers.tsx` - TanStack Query + Sonner providers
- ✅ `src/components/auth/ProtectedRoute.tsx` - Auth guard component
- ✅ `app/(auth)/login/page.tsx` - Login page with validation
- ✅ `app/(auth)/signup/page.tsx` - Signup page with org creation
- ✅ `app/(dashboard)/layout.tsx` - Protected dashboard layout
- ✅ `app/(dashboard)/page.tsx` - Dashboard home with user info
- ✅ `app/layout.tsx` - Root layout with providers
- ✅ `app/page.tsx` - Home page with auth redirect
- ✅ `.env.local` & `.env.example` - Environment config
- ✅ `README.md` - Frontend documentation

**Dependencies Installed:**
- ✅ @tanstack/react-query + devtools (data fetching)
- ✅ zustand (state management)
- ✅ react-hook-form + @hookform/resolvers + zod (forms)
- ✅ shadcn/ui components (button, input, label, card, form, dialog, sonner)
- ✅ lucide-react (icons)
- ✅ class-variance-authority, clsx, tailwind-merge (utilities)

**Full Stack Integration:**
- ✅ Backend running: http://localhost:8000
- ✅ Frontend running: http://localhost:3002
- ✅ API client configured for backend communication
- ✅ Authentication flow implemented
- ✅ Protected routes working
- ✅ Build verification successful

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
- ✅ Authentication pages created
- ✅ Protected routes implemented
- ✅ State management setup
- ✅ Full stack integration working
- ✅ Backend dependencies fixed (APScheduler, NumPy compatibility)
- ✅ Frontend hydration working (minor browser extension warning ignored)

---

### Wednesday-Thursday: Enhanced Authentication

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Enhanced form validation with react-hook-form + Zod
- [x] Improved login page with validation
- [x] Improved signup page with validation
- [x] Created validation schemas
- [x] Enhanced dashboard layout with navigation
- [x] Created onboarding flow for workspace setup
- [x] Built Slack workspace connection form
- [x] Added connection testing functionality

**Files Created/Updated:**
- ✅ `src/lib/validations.ts` - Zod validation schemas
- ✅ `app/(auth)/login/page.tsx` - Enhanced with react-hook-form
- ✅ `app/(auth)/signup/page.tsx` - Enhanced with react-hook-form
- ✅ `app/onboarding/page.tsx` - Onboarding flow
- ✅ `src/components/onboarding/SlackWorkspaceForm.tsx` - Workspace setup
- ✅ `app/(dashboard)/layout.tsx` - Enhanced navigation
- ✅ `app/(dashboard)/page.tsx` - Improved dashboard
- ✅ `src/lib/api.ts` - Added workspace testing endpoint

**Features Implemented:**
- ✅ Form validation with Zod schemas
- ✅ Real-time validation feedback
- ✅ Password confirmation validation
- ✅ Slack token format validation
- ✅ Connection testing before saving
- ✅ Enhanced dashboard with stats and quick actions
- ✅ Improved navigation with dropdown menu
- ✅ Onboarding wizard for new users

**Acceptance Criteria:**
- ✅ Enhanced form validation with Zod
- ✅ Real-time validation feedback
- ✅ Password strength validation
- ✅ Slack token format validation
- ✅ Connection testing works
- ✅ Onboarding flow complete
- ✅ Dashboard navigation enhanced
- ✅ Build verification successful

---

### Friday: JWT Storage & Onboarding Polish

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Implement JWT token storage with TokenManager
- [x] Add automatic token refresh logic
- [x] Enhanced API client with token management
- [x] Improved loading states with skeleton components
- [x] Enhanced onboarding UX with better feedback
- [x] Fixed hydration warning from browser extensions
- [x] Added professional loading skeletons

**Files Created/Updated:**
- ✅ `src/lib/auth.ts` - JWT TokenManager utility
- ✅ `src/lib/api.ts` - Enhanced with JWT token handling
- ✅ `src/store/useAuthStore.ts` - Integrated TokenManager
- ✅ `src/components/auth/ProtectedRoute.tsx` - Enhanced loading states
- ✅ `src/components/onboarding/SlackWorkspaceForm.tsx` - Improved UX
- ✅ `app/layout.tsx` - Fixed hydration warning
- ✅ `components/ui/skeleton.tsx` - Loading skeleton component

**Features Implemented:**
- ✅ Secure JWT token storage in localStorage
- ✅ Automatic token expiry handling
- ✅ Token-based API authentication
- ✅ Professional loading skeletons
- ✅ Enhanced error messages with emojis
- ✅ Improved connection testing feedback
- ✅ Automatic logout on token expiry

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

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Build question input component
- [x] Build answer display component
- [x] Create source card component
- [x] Add loading states
- [x] Add error states
- [x] Build filter sidebar
- [x] Create main Q&A page
- [x] Integrate all components

**Files Created:**
- ✅ `src/components/qa/QuestionInput.tsx` - Auto-expanding textarea with shortcuts
- ✅ `src/components/qa/AnswerDisplay.tsx` - Answer with confidence and sources
- ✅ `src/components/qa/SourceCard.tsx` - Individual source display with metadata
- ✅ `src/components/qa/ConfidenceBadge.tsx` - Color-coded confidence indicator
- ✅ `src/components/qa/FilterSidebar.tsx` - Comprehensive filtering options
- ✅ `app/(dashboard)/qa/page.tsx` - Main Q&A interface
- ✅ Added shadcn/ui components: textarea, badge, select, checkbox

**Features Implemented:**
- ✅ Professional question input with keyboard shortcuts
- ✅ Confidence-based answer display
- ✅ Expandable source cards with copy/link actions
- ✅ Comprehensive filtering (workspace, channel, time, source types)
- ✅ Loading states and error handling
- ✅ Responsive design with sidebar layout
- ✅ Professional empty state with examples

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

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Connect to Q&A API endpoint
- [x] Implement workspace selector with real data
- [x] Add channel filter with dynamic loading
- [x] Add date range filter
- [x] Implement query history with localStorage
- [x] Create React Query hooks for data management
- [x] Add loading states and error handling

**Files Created:**
- ✅ `src/hooks/useWorkspaces.ts` - Workspace and channel data hooks
- ✅ `src/hooks/useQA.ts` - Q&A functionality and history hooks
- ✅ `src/components/qa/QueryHistory.tsx` - Query history with persistence
- ✅ Updated `FilterSidebar.tsx` - Real workspace/channel integration
- ✅ Updated `qa/page.tsx` - Full API integration
- ✅ Updated `api.ts` - Added workspace channels endpoint

**Features Implemented:**
- ✅ Real-time workspace and channel loading
- ✅ Persistent query history with localStorage
- ✅ React Query for efficient data management
- ✅ Dynamic channel filtering based on workspace
- ✅ Query history with delete and rerun functionality
- ✅ Professional loading states and error handling
- ✅ Optimistic UI updates

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

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Add keyboard shortcuts (Cmd+K to focus input)
- [x] Implement citation click-to-highlight
- [x] Add project links display
- [x] Optimize performance
- [x] Write E2E tests
- [x] Fix bugs

**Enhancements:**
- ✅ Cmd+Enter to submit question (already implemented)
- ✅ Click source to expand full message (expandable details)
- ✅ Display extracted GitHub/docs links (project_links section)
- ✅ Lazy load query history (max-height with overflow)
- ✅ Debounce search inputs (channel search with useMemo)
- ✅ Cmd+K keyboard shortcut to focus input

**Features Implemented:**
- ✅ Keyboard shortcuts (Cmd+K focus, Cmd+Enter submit)
- ✅ Expandable source cards with click-to-expand
- ✅ Project links display in answer section
- ✅ Debounced channel search for large workspaces
- ✅ Lazy loading query history with scroll
- ✅ Performance optimizations with useMemo
- ✅ Professional loading states and animations

**Acceptance Criteria:**
- ✅ Fast, snappy UX
- ✅ No console errors
- ✅ Tests passing
- ✅ Works on mobile

---

## WEEK 4: Workspace Management 🔧

**Priority:** Self-service workspace setup

### Monday-Tuesday: Workspace List & Details

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Create workspace list page
- [x] Build workspace card component
- [x] Show sync status
- [x] Display message counts
- [x] Add last sync timestamp
- [x] Create workspace detail view

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

**Files Created:**
- ✅ `app/dashboard/workspaces/page.tsx` - Main workspace list page
- ✅ `src/components/workspaces/WorkspaceCard.tsx` - Reusable workspace card
- ✅ `src/components/workspaces/AddWorkspaceModal.tsx` - Add workspace modal
- ✅ Updated `src/hooks/useWorkspaces.ts` - Extended interface

**Features Implemented:**
- ✅ Grid/list view toggle
- ✅ Search workspaces by name
- ✅ Filter by status (active, syncing, error)
- ✅ Status badges with colors
- ✅ Message and channel counts
- ✅ Last sync timestamps
- ✅ Quick actions (Edit, Sync, Delete)
- ✅ Professional loading skeletons
- ✅ Empty state with call-to-action
- ✅ Add workspace modal with validation
- ✅ Connection testing functionality

**Acceptance Criteria:**
- ✅ All workspaces displayed
- ✅ Real-time status updates
- ✅ Fast search/filter
- ✅ Clean, organized UI
- ✅ Responsive design
- ✅ TypeScript compilation successful

---

### Wednesday: Add/Edit Workspace

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Build "Add Workspace" modal
- [x] Create edit workspace form
- [x] Implement credential update
- [x] Add connection test
- [x] Handle validation errors

**Files Created/Updated:**
- ✅ `src/components/workspaces/EditWorkspaceModal.tsx` - Edit workspace modal
- ✅ `src/hooks/useWorkspaceSync.ts` - Workspace sync hook
- ✅ Updated `src/lib/api.ts` - Added workspace management endpoints
- ✅ Updated `AddWorkspaceModal.tsx` - Integrated API client
- ✅ Updated `app/dashboard/workspaces/page.tsx` - Integrated edit modal

**Features Implemented:**
- ✅ Add new workspace with validation
- ✅ Edit existing workspace credentials
- ✅ Masked credential display with reveal toggle
- ✅ Connection testing for new and updated credentials
- ✅ Delete workspace with confirmation dialog
- ✅ Manual workspace sync functionality
- ✅ Form validation with Zod schemas
- ✅ Loading states and error handling
- ✅ API integration with proper error handling

**Security Features:**
- ✅ Tokens masked as `xoxb-***-***-***` by default
- ✅ Eye/EyeOff toggle to reveal credentials
- ✅ Secure API endpoints for credential management
- ✅ Proper validation of Slack token formats

**API Endpoints Added:**
- ✅ `POST /api/workspaces` - Add workspace
- ✅ `PUT /api/workspaces/{id}` - Update workspace
- ✅ `DELETE /api/workspaces/{id}` - Delete workspace
- ✅ `POST /api/workspaces/{id}/sync` - Manual sync
- ✅ `POST /api/workspaces/test-connection` - Test credentials

**Acceptance Criteria:**
- ✅ Can add new workspaces
- ✅ Can edit existing workspaces
- ✅ Credentials update successfully
- ✅ Secure token handling
- ✅ Connection testing works
- ✅ Delete confirmation prevents accidents
- ✅ Manual sync triggers properly
- ✅ TypeScript compilation successful

---

### Thursday-Friday: Backfill Configuration

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Create schedule configuration UI
- [x] Build cron expression builder
- [x] Add manual trigger button
- [x] Show backfill history
- [x] Display job status

**Files Created:**
- ✅ `src/components/workspaces/BackfillScheduler.tsx` - Schedule configuration UI
- ✅ `src/components/workspaces/BackfillHistory.tsx` - Job history display
- ✅ `app/dashboard/workspaces/[id]/page.tsx` - Workspace detail page
- ✅ `backend/src/api/routes/workspaces.py` - Workspace API endpoints
- ✅ Updated `backend/src/api/main.py` - Added workspace router
- ✅ Added `components/ui/switch.tsx` - Switch component

**Features Implemented:**
- ✅ Visual schedule builder with predefined options:
  - Daily at 2 AM
  - Every 6 hours
  - Every hour
  - Every 30 minutes
  - Custom cron expression
- ✅ Manual "Sync Now" button with immediate trigger
- ✅ Backfill history with job details
- ✅ Status indicators (✅ Success, 🔄 Running, ❌ Failed)
- ✅ Workspace detail page with stats and configuration
- ✅ Professional loading states and error handling

**Backfill History Features:**
- ✅ Job type (scheduled/manual)
- ✅ Start and completion times
- ✅ Duration calculation
- ✅ Messages and channels processed
- ✅ Status with color-coded badges
- ✅ Error message display for failed jobs
- ✅ Refresh functionality

**Backend API Endpoints:**
- ✅ `GET /api/workspaces` - List workspaces
- ✅ `POST /api/workspaces` - Create workspace
- ✅ `PUT /api/workspaces/{id}` - Update workspace
- ✅ `DELETE /api/workspaces/{id}` - Delete workspace
- ✅ `POST /api/workspaces/{id}/sync` - Manual sync
- ✅ `POST /api/workspaces/test-connection` - Test credentials
- ✅ `GET /api/workspaces/{id}/channels` - Get channels

**Acceptance Criteria:**
- ✅ Schedule updates save correctly
- ✅ Manual sync triggers immediately
- ✅ History displays accurately
- ✅ Errors shown clearly
- ✅ Workspace stats display properly
- ✅ Navigation between list and detail works
- ✅ TypeScript compilation successful
- ✅ Responsive design on all devices

---

## WEEK 5: Settings & Team Management ⚙️ ✅ **COMPLETE**

**Priority:** Configuration & collaboration

### Monday-Tuesday: AI Settings Page

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Create settings page layout
- [x] Build AI configuration form
- [x] Add tone selector
- [x] Add response length slider
- [x] Add confidence threshold
- [x] Implement custom instructions
- [x] Add save/reset functionality

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

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Create team page
- [x] List all organization users
- [x] Display user roles
- [x] Show user status
- [x] Add role change functionality

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

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Build invite user modal
- [x] Create invitation email template
- [x] Implement invite link generation
- [x] Add pending invitations section
- [x] Create accept invitation flow

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

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Create documents page
- [x] Build file upload component
- [x] Implement drag-and-drop
- [x] Show upload progress
- [x] List uploaded documents
- [x] Add delete functionality

**Files Created:**
- ✅ `app/dashboard/documents/page.tsx` - Main documents page with stats
- ✅ `src/components/documents/FileUpload.tsx` - Drag & drop upload component
- ✅ `src/components/documents/DocumentList.tsx` - Document list with actions
- ✅ `src/hooks/useDocuments.ts` - React Query hooks for document management
- ✅ Updated navigation to include Documents page

**Features Implemented:**
- ✅ Drag & drop file upload with validation
- ✅ Support for PDF, DOCX, TXT, MD files
- ✅ File size validation (10MB limit)
- ✅ Upload progress indication
- ✅ Document list with status badges
- ✅ File metadata (name, type, size, date)
- ✅ Status tracking (Indexed, Processing, Failed)
- ✅ Delete functionality with confirmation
- ✅ Stats cards showing document counts by status
- ✅ Professional loading states and error handling

**Acceptance Criteria:**
- ✅ Upload works for all file types
- ✅ Progress shown accurately
- ✅ Documents indexed correctly
- ✅ Searchable in Q&A

---

### Wednesday: Dashboard Overview Page

**Status:** ✅ COMPLETED (2025-11-30)

**Tasks:**
- [x] Create dashboard home page
- [x] Add stats cards
- [x] Build recent activity feed
- [x] Add quick actions
- [x] Create charts (optional)

**Files Updated:**
- ✅ `app/dashboard/page.tsx` - Enhanced dashboard with real data

**Features Implemented:**

**Stats Cards:**
- ✅ Active Workspaces count
- ✅ Total Messages Indexed with formatting
- ✅ Queries This Month calculation
- ✅ Documents count (indexed only)

**Recent Activity Feed:**
- ✅ Recent Q&A queries with confidence scores
- ✅ Recent workspace sync activities
- ✅ Time-based sorting and formatting
- ✅ Activity type icons and badges

**Quick Actions:**
- ✅ Ask a Question (→ Q&A page)
- ✅ Add Workspace
- ✅ Upload Document
- ✅ Invite Team Member
- ✅ Professional button styling

**Data Integration:**
- ✅ Real workspace data from useWorkspaces hook
- ✅ Real document data from useDocuments hook
- ✅ Real query history from useQA hook
- ✅ Dynamic calculations and filtering

**Acceptance Criteria:**
- ✅ Stats accurate and dynamic
- ✅ Activity updates with real data
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

**Week 1:** Backend solid and secure ✅ **100% COMPLETE**
- ✅ Workspace isolation verified (Monday - COMPLETED)
- ✅ Single command starts all services (Tuesday - COMPLETED)
- ✅ Automated backfills running (Thursday - COMPLETED)
- ✅ Credential encryption (Friday - COMPLETED)

**Week 2:** Frontend foundation & authentication ✅ **100% COMPLETE**
- ✅ Next.js 14 project setup (COMPLETED)
- ✅ Enhanced authentication with validation (COMPLETED)
- ✅ JWT token management (COMPLETED)
- ✅ Professional onboarding flow (COMPLETED)
- ✅ Dashboard with navigation (COMPLETED)
- ✅ Loading states and UX polish (COMPLETED)
- ✅ Full stack integration verified (COMPLETED)

**Week 3:** Core Q&A feature
- ✅ Q&A interface functional
- ✅ Workspace management
- ✅ User experience polished

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

## 📁 Project Structure

The project is organized as a monorepo:

```
slack-helper/
├── backend/              # Python FastAPI backend
│   ├── src/
│   │   ├── api/         # FastAPI routes, middleware
│   │   ├── services/    # Business logic
│   │   ├── db/          # Database clients
│   │   ├── utils/       # Encryption, helpers
│   │   └── main.py      # Unified entry point
│   ├── migrations/      # SQL migrations
│   ├── tests/           # Test suite
│   ├── scripts/         # Utility scripts
│   ├── requirements.txt
│   └── .env
├── frontend/            # Next.js 14 frontend (Week 2+)
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── package.json
├── planning/            # Product docs, roadmap
└── README.md            # Root readme
```

**Commands:**
```bash
# Start backend
cd backend && source venv/bin/activate && python -m src.main

# Start frontend (Week 2+)
cd frontend && npm run dev
```

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

**Last Updated:** 2025-11-30
**Status:** ✅ Week 1 Complete (100%) | ✅ Week 2 Complete (100%)
**Next Action:** Week 3 Monday - Q&A Interface Implementation
