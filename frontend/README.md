# Slack Helper Bot - Frontend

Next.js 14 frontend for the Slack Helper Bot SaaS platform.

## Tech Stack

- **Framework:** Next.js 14 (App Router)
- **Language:** TypeScript
- **Styling:** Tailwind CSS + shadcn/ui
- **State Management:** Zustand
- **Data Fetching:** TanStack Query
- **Forms:** React Hook Form + Zod
- **Notifications:** Sonner

## Project Structure

```
src/
├── components/
│   ├── auth/           # Authentication components
│   ├── dashboard/      # Dashboard-specific components
│   └── ui/            # shadcn/ui components
├── lib/
│   ├── api.ts         # API client
│   └── providers.tsx  # Global providers
└── store/
    └── useAuthStore.ts # Authentication state

app/
├── (auth)/
│   ├── login/         # Login page
│   └── signup/        # Signup page
├── (dashboard)/       # Protected dashboard routes
│   ├── layout.tsx     # Dashboard layout
│   └── page.tsx       # Dashboard home
├── layout.tsx         # Root layout
└── page.tsx          # Home page (redirects)
```

## Getting Started

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Setup environment:**
   ```bash
   cp .env.example .env.local
   # Edit .env.local with your backend URL
   ```

3. **Start development server:**
   ```bash
   npm run dev
   ```

4. **Open browser:**
   Navigate to [http://localhost:3000](http://localhost:3000)

## Environment Variables

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_NAME="Slack Helper Bot"
```

## Features Implemented

### ✅ Week 2 Monday-Tuesday: Project Setup
- [x] Next.js 14 project with TypeScript
- [x] Tailwind CSS + shadcn/ui components
- [x] TanStack Query + Zustand setup
- [x] API client utility
- [x] Project structure created
- [x] Environment variables configured

### 🔄 Next Steps (Week 2 Wednesday-Friday)
- [ ] Authentication pages (login/signup)
- [ ] Form validation with react-hook-form
- [ ] JWT token storage
- [ ] Protected route wrapper
- [ ] Onboarding flow

## API Integration

The frontend connects to the FastAPI backend running on `http://localhost:8000`. 

Key endpoints:
- `POST /api/auth/login` - User login
- `POST /api/auth/signup` - User signup + org creation
- `GET /api/auth/me` - Get current user
- `POST /api/qa/ask` - Ask questions
- `GET /api/workspaces` - List workspaces

## Development

```bash
# Start development server
npm run dev

# Build for production
npm run build

# Start production server
npm start

# Run linting
npm run lint
```

## Components

### Authentication
- `ProtectedRoute` - Guards dashboard routes
- Login/Signup pages with form validation
- Auth state management with Zustand

### UI Components (shadcn/ui)
- Button, Input, Label, Card
- Form components with validation
- Dialog modals
- Toast notifications (Sonner)

## Status

**Current:** Week 2 Monday-Tuesday ✅ COMPLETE
**Next:** Week 2 Wednesday-Friday - Authentication implementation