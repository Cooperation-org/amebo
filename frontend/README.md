# Slack Helper Bot - Frontend

⚛️ **Next.js 14 Frontend** - Modern React dashboard with TypeScript, Tailwind CSS, and real-time Q&A interface.

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     Pages       │    │   Components    │    │     Hooks       │
│                 │    │                 │    │                 │
│ • Dashboard     │◄──►│ • Q&A Interface │◄──►│ • useQA         │
│ • Workspaces    │    │ • File Upload   │    │ • useWorkspaces │
│ • Documents     │    │ • Team Mgmt     │    │ • useDocuments  │
│ • Settings      │    │ • Auth Forms    │    │ • useAuth       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                       ┌─────────────────┐
                       │   API Client    │
                       │                 │
                       │ • JWT Tokens    │
                       │ • HTTP Client   │
                       │ • Error Handle  │
                       └─────────────────┘
```

## 📋 Prerequisites

- **Node.js 18+**
- **npm or yarn**
- **Backend API** running on port 8000

## 🚀 Quick Setup

### 1. Environment Setup

```bash
# Navigate to frontend
cd frontend

# Install dependencies
npm install
# or
yarn install
```

### 2. Environment Configuration

```bash
# Copy environment template
cp .env.example .env.local

# Edit environment variables
nano .env.local
```

**Required Environment Variables:**

```env
# API Configuration
NEXT_PUBLIC_API_URL=http://localhost:8000

# Development
NODE_ENV=development
```

### 3. Start Development Server

```bash
# Start development server
npm run dev
# or
yarn dev

# Open browser
open http://localhost:3000
```

## 🎨 UI Components

### Design System
- **Tailwind CSS** - Utility-first CSS framework
- **shadcn/ui** - Modern React component library
- **Lucide Icons** - Beautiful SVG icons
- **Responsive Design** - Mobile-first approach

### Component Library

```
src/components/
├── ui/                    # Base UI components (shadcn/ui)
│   ├── button.tsx
│   ├── card.tsx
│   ├── input.tsx
│   └── ...
├── auth/                  # Authentication components
│   ├── LoginForm.tsx
│   ├── SignupForm.tsx
│   └── ProtectedRoute.tsx
├── qa/                    # Q&A interface components
│   ├── QuestionInput.tsx
│   ├── AnswerDisplay.tsx
│   ├── SourceCard.tsx
│   └── QueryHistory.tsx
├── workspaces/           # Workspace management
│   ├── WorkspaceCard.tsx
│   ├── AddWorkspaceModal.tsx
│   └── BackfillButton.tsx
├── documents/            # Document management
│   ├── FileUpload.tsx
│   ├── DocumentList.tsx
│   └── UploadProgress.tsx
└── team/                 # Team management
    ├── InviteUserModal.tsx
    ├── UserTable.tsx
    └── RoleSelector.tsx
```

## 📁 Project Structure

```
frontend/
├── app/                      # Next.js 14 App Router
│   ├── (auth)/              # Auth route group
│   │   ├── login/
│   │   └── signup/
│   ├── dashboard/           # Protected dashboard routes
│   │   ├── page.tsx        # Dashboard home
│   │   ├── qa/             # Q&A interface
│   │   ├── workspaces/     # Workspace management
│   │   ├── documents/      # Document upload
│   │   ├── team/           # Team management
│   │   └── settings/       # Organization settings
│   ├── layout.tsx          # Root layout
│   └── page.tsx           # Landing page
├── src/
│   ├── components/         # React components
│   ├── hooks/             # Custom React hooks
│   ├── lib/               # Utilities and configurations
│   │   ├── api.ts         # API client
│   │   ├── auth.ts        # JWT token management
│   │   └── validations.ts # Form validation schemas
│   └── store/             # State management
│       └── useAuthStore.ts # Authentication store
├── public/                # Static assets
├── package.json          # Dependencies and scripts
├── tailwind.config.js    # Tailwind CSS configuration
├── tsconfig.json         # TypeScript configuration
└── next.config.js        # Next.js configuration
```

## 🔧 Key Features

### 1. Authentication System
- **JWT Token Management** - Secure token storage and refresh
- **Protected Routes** - Route-level authentication guards
- **Persistent Sessions** - Automatic login state restoration

```typescript
// Example: Using authentication
import { useAuthStore } from '@/src/store/useAuthStore';

function MyComponent() {
  const { user, login, logout, isAuthenticated } = useAuthStore();
  
  if (!isAuthenticated) {
    return <LoginForm />;
  }
  
  return <Dashboard user={user} />;
}
```

### 2. Q&A Interface
- **Real-time Search** - Instant AI-powered responses
- **Source Attribution** - Links to original Slack messages
- **Query History** - Persistent search history
- **Confidence Scoring** - AI confidence indicators

```typescript
// Example: Q&A hook usage
import { useQA } from '@/src/hooks/useQA';

function QAInterface() {
  const { askQuestion, isLoading, response } = useQA();
  
  const handleSubmit = (question: string) => {
    askQuestion({
      question,
      workspace_id: 'selected-workspace',
      include_documents: true
    });
  };
  
  return (
    <div>
      <QuestionInput onSubmit={handleSubmit} isLoading={isLoading} />
      {response && <AnswerDisplay response={response} />}
    </div>
  );
}
```

### 3. Document Management
- **Drag & Drop Upload** - Intuitive file upload interface
- **Multi-format Support** - PDF, DOCX, TXT, Markdown
- **Upload Progress** - Real-time upload status
- **Workspace Tagging** - Associate documents with workspaces

### 4. Team Management
- **User Invitations** - Email-based team invitations
- **Role Management** - Admin, Member, Viewer roles
- **User Status** - Active/inactive user management

## 🎯 Custom Hooks

### Data Fetching Hooks

```typescript
// Authentication
const { user, login, logout, isAuthenticated } = useAuthStore();

// Workspaces
const { data: workspaces, isLoading } = useWorkspaces();
const addWorkspaceMutation = useAddWorkspace();

// Documents
const { data: documents } = useDocuments(workspaceId);
const uploadMutation = useUploadDocuments();

// Q&A
const { askQuestion, response, isLoading } = useQA();

// Team Management
const { data: members } = useTeamMembers();
const inviteMutation = useInviteUser();
```

### State Management

```typescript
// Zustand store for authentication
import { create } from 'zustand';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  login: async (email, password) => {
    // Login logic
  },
  logout: () => {
    // Logout logic
  }
}));
```

## 🎨 Styling Guide

### Tailwind CSS Classes

```css
/* Common patterns */
.btn-primary {
  @apply bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg;
}

.card {
  @apply bg-white rounded-lg shadow-sm border p-6;
}

.input {
  @apply border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500;
}
```

### Component Styling

```typescript
// Example: Styled component
function Button({ variant = 'primary', children, ...props }) {
  const baseClasses = 'px-4 py-2 rounded-lg font-medium transition-colors';
  const variantClasses = {
    primary: 'bg-blue-600 hover:bg-blue-700 text-white',
    secondary: 'bg-gray-200 hover:bg-gray-300 text-gray-900',
    outline: 'border border-gray-300 hover:bg-gray-50'
  };
  
  return (
    <button 
      className={`${baseClasses} ${variantClasses[variant]}`}
      {...props}
    >
      {children}
    </button>
  );
}
```

## 🔌 API Integration

### API Client Configuration

```typescript
// src/lib/api.ts
class ApiClient {
  private baseURL: string;
  
  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }
  
  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    
    const config: RequestInit = {
      headers: {
        'Content-Type': 'application/json',
        ...TokenManager.getAuthHeader(),
        ...options.headers,
      },
      ...options,
    };
    
    const response = await fetch(url, config);
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    
    return response.json();
  }
  
  // API methods
  async login(email: string, password: string) {
    return this.request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  }
}
```

## 🧪 Testing

```bash
# Run tests
npm test

# Run tests in watch mode
npm run test:watch

# Run tests with coverage
npm run test:coverage

# Type checking
npm run type-check

# Linting
npm run lint
```

### Testing Examples

```typescript
// Component test
import { render, screen } from '@testing-library/react';
import { LoginForm } from '@/src/components/auth/LoginForm';

test('renders login form', () => {
  render(<LoginForm />);
  expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
});

// Hook test
import { renderHook } from '@testing-library/react';
import { useAuthStore } from '@/src/store/useAuthStore';

test('authentication store', () => {
  const { result } = renderHook(() => useAuthStore());
  expect(result.current.isAuthenticated).toBe(false);
});
```

## 🚀 Production Build

```bash
# Build for production
npm run build

# Start production server
npm start

# Export static site (if needed)
npm run export
```

### Performance Optimization

- **Code Splitting** - Automatic route-based code splitting
- **Image Optimization** - Next.js Image component
- **Bundle Analysis** - Webpack bundle analyzer
- **Caching** - React Query for API response caching

## 🔧 Configuration Files

### TypeScript Configuration

```json
// tsconfig.json
{
  "compilerOptions": {
    "target": "es5",
    "lib": ["dom", "dom.iterable", "es6"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "baseUrl": ".",
    "paths": {
      "@/*": ["./*"]
    }
  }
}
```

### Tailwind Configuration

```javascript
// tailwind.config.js
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        }
      }
    },
  },
  plugins: [require('@tailwindcss/forms')],
}
```

## 🐛 Debugging

### Development Tools

```bash
# Enable React DevTools
npm install --save-dev @next/bundle-analyzer

# Analyze bundle size
ANALYZE=true npm run build

# Debug API calls
# Check Network tab in browser DevTools
```

### Common Issues

1. **Hydration Mismatch**
   ```typescript
   // Use dynamic imports for client-only components
   import dynamic from 'next/dynamic';
   
   const ClientOnlyComponent = dynamic(
     () => import('./ClientOnlyComponent'),
     { ssr: false }
   );
   ```

2. **CORS Issues**
   ```typescript
   // Check API_URL in .env.local
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

## 📱 Responsive Design

### Breakpoints

```css
/* Tailwind CSS breakpoints */
sm: 640px   /* Small devices */
md: 768px   /* Medium devices */
lg: 1024px  /* Large devices */
xl: 1280px  /* Extra large devices */
2xl: 1536px /* 2X large devices */
```

### Mobile-First Approach

```typescript
// Example: Responsive component
function ResponsiveGrid({ children }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {children}
    </div>
  );
}
```

## 🤝 Contributing

1. Follow React/Next.js best practices
2. Use TypeScript for all components
3. Write tests for new features
4. Follow the established component structure
5. Use Tailwind CSS for styling

## 📚 Additional Resources

- [Next.js Documentation](https://nextjs.org/docs)
- [React Documentation](https://react.dev/)
- [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- [shadcn/ui Components](https://ui.shadcn.com/)
- [TanStack Query Documentation](https://tanstack.com/query/latest)