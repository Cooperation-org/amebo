# Amebo - AI-Powered Workspace Intelligence

🤖 **Your Workspace Padi & Gist Partner** - Transform scattered workplace conversations and documents into accessible, intelligent insights.

[![Built with Amazon Q Developer](https://img.shields.io/badge/Built%20with-Amazon%20Q%20Developer-FF9900?style=flat-square&logo=amazon-aws)](https://aws.amazon.com/q/developer/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-007ACC?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)

## 🎯 What is Amebo?

Amebo is an enterprise-grade SaaS platform that serves as your team's intelligent knowledge companion. It transforms your Slack conversations, uploaded documents, and institutional knowledge into a searchable, AI-powered Q&A system.

### 🚀 Key Benefits
- **Instant Knowledge Access** - Find answers in seconds, not minutes
- **Context-Aware Intelligence** - Understands conversation threads and document relationships
- **Multi-Workspace Support** - Manage multiple Slack workspaces from one dashboard
- **Enterprise Security** - Multi-tenant architecture with encrypted credential storage
- **Seamless Integration** - Works in Slack via `/ask` commands and web dashboard

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Next.js 14    │    │   FastAPI        │    │   PostgreSQL    │
│   Frontend       │◄──►│   Backend        │◄──►│   Database      │
│   Dashboard      │    │   API Server     │    │   Multi-tenant  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                       ┌────────┴────────┐
                       │                 │
                ┌──────▼──────┐   ┌─────▼─────┐
                │  ChromaDB   │   │   Slack   │
                │  Vector DB  │   │    API    │
                │  Semantic   │   │ Real-time │
                │   Search    │   │   Sync    │
                └─────────────┘   └───────────┘
```

## 📁 Project Structure

```
slack-helper/
├── 📂 backend/              # Python FastAPI backend
│   ├── src/
│   │   ├── api/             # REST API routes
│   │   ├── services/        # Business logic
│   │   ├── db/              # Database connections
│   │   └── models/          # Data models
│   ├── requirements.txt     # Python dependencies
│   └── README.md           # Backend setup guide
├── 📂 frontend/             # Next.js 14 frontend
│   ├── app/                # App router pages
│   ├── src/
│   │   ├── components/     # React components
│   │   ├── hooks/          # Custom React hooks
│   │   ├── lib/            # Utilities & API client
│   │   └── store/          # State management
│   ├── package.json        # Node dependencies
│   └── README.md          # Frontend setup guide
├── 📂 docs/                # Documentation
│   ├── ARCHITECTURE.md     # System architecture
│   ├── API.md             # API documentation
│   └── DEPLOYMENT.md      # Deployment guide
└── README.md              # This file
```

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Node.js 18+
- PostgreSQL 13+
- Slack App with Bot Token

### 1. Clone Repository
```bash
git clone <repository-url>
cd slack-helper
```

### 2. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your database and API keys

# Start backend
python run_server.py
```

### 3. Frontend Setup
```bash
cd frontend
npm install

# Set environment variables
cp .env.example .env.local
# Edit .env.local with your API URL

# Start frontend
npm run dev
```

### 4. Access Application
- **Frontend Dashboard**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## 🎯 Core Features

### ✅ Intelligent Q&A System
- Natural language processing with Anthropic Claude
- Context-aware responses from Slack messages and documents
- Source attribution with confidence scoring
- Real-time search across indexed content

### ✅ Multi-Workspace Management
- Secure workspace isolation with 4-layer architecture
- Multiple Slack workspace integration per organization
- Encrypted credential storage using Fernet encryption
- Automated message backfilling with configurable schedules

### ✅ Document Intelligence
- Multi-format support (PDF, DOCX, TXT, Markdown)
- Automatic text extraction and chunking
- Vector indexing for semantic search
- Workspace-specific document tagging

### ✅ Team Collaboration
- Role-based access control (Admin, Member, Viewer)
- User invitation system with email notifications
- Team management with activation/deactivation
- Organization-level settings and AI configuration

### ✅ Enterprise Security
- Multi-tenant data isolation
- JWT authentication with secure token handling
- Encrypted credential storage
- CORS protection and input validation

## 🛠️ Technology Stack

### Backend
- **FastAPI** - High-performance Python web framework
- **PostgreSQL** - Relational database for structured data
- **ChromaDB** - Vector database for semantic search
- **APScheduler** - Background task automation
- **Slack SDK** - Real-time Slack integration
- **Anthropic Claude** - AI language model for Q&A

### Frontend
- **Next.js 14** - React framework with App Router
- **TypeScript** - Type-safe JavaScript
- **Tailwind CSS** - Utility-first CSS framework
- **shadcn/ui** - Modern React component library
- **TanStack Query** - Data fetching and caching
- **Zustand** - Lightweight state management

### Infrastructure
- **Docker** - Containerization
- **PostgreSQL** - Primary database
- **ChromaDB** - Vector embeddings storage
- **JWT** - Authentication tokens

## 📚 Documentation

- **[Backend Setup Guide](backend/README.md)** - Detailed backend installation and configuration
- **[Frontend Setup Guide](frontend/README.md)** - Frontend development environment setup
- **[Architecture Documentation](docs/ARCHITECTURE.md)** - System design and component interactions
- **[API Documentation](docs/API.md)** - REST API endpoints and usage
- **[Deployment Guide](docs/DEPLOYMENT.md)** - Production deployment instructions

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [Amazon Q Developer](https://aws.amazon.com/q/developer/) for accelerated development
- Powered by [Anthropic Claude](https://www.anthropic.com/) for intelligent responses
- UI components from [shadcn/ui](https://ui.shadcn.com/)

---

**Made with ❤️ and Amazon Q Developer**
