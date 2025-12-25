#!/bin/bash

# Amebo Deployment Script
# This script helps deploy Amebo to a server

set -e  # Exit on error

echo "========================================"
echo "  Amebo - Deployment Script"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${NC}ℹ $1${NC}"
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

print_success "Docker and Docker Compose are installed"

# Check if .env.production exists
if [ ! -f ".env.production" ]; then
    print_warning ".env.production not found"

    if [ -f ".env.production.example" ]; then
        print_info "Copying .env.production.example to .env.production"
        cp .env.production.example .env.production
        print_warning "Please edit .env.production with your actual values before proceeding"
        print_info "Run: nano .env.production"
        exit 1
    else
        print_error ".env.production.example not found"
        exit 1
    fi
fi

print_success ".env.production found"

# Check if backend/.env exists
if [ ! -f "backend/.env" ]; then
    print_warning "backend/.env not found"

    if [ -f "backend/.env.example" ]; then
        print_info "Copying backend/.env.example to backend/.env"
        cp backend/.env.example backend/.env
        print_warning "Please edit backend/.env with your actual values"
        print_info "Run: nano backend/.env"
        exit 1
    fi
fi

print_success "backend/.env found"

# Load environment variables
export $(cat .env.production | grep -v '^#' | xargs)

# Ask user what they want to do
echo ""
echo "What would you like to do?"
echo "1) Fresh deployment (build and start all services)"
echo "2) Update deployment (rebuild and restart)"
echo "3) Start services (without rebuilding)"
echo "4) Stop services"
echo "5) View logs"
echo "6) Backup database"
echo "7) Check status"
echo "8) Exit"
echo ""
read -p "Enter your choice [1-8]: " choice

case $choice in
    1)
        print_info "Starting fresh deployment..."
        echo ""
        print_info "This will build all Docker images and start services"
        read -p "Continue? (y/n): " confirm

        if [ "$confirm" = "y" ]; then
            print_info "Building and starting services..."
            docker-compose down -v
            docker-compose up -d --build
            print_success "Deployment complete!"
            echo ""
            print_info "Access points:"
            echo "  Frontend: http://localhost:3000"
            echo "  Backend API: http://localhost:8000"
            echo "  API Docs: http://localhost:8000/docs"
            echo ""
            print_info "View logs with: docker-compose logs -f"
        fi
        ;;

    2)
        print_info "Updating deployment..."
        docker-compose down
        docker-compose up -d --build
        print_success "Update complete!"
        ;;

    3)
        print_info "Starting services..."
        docker-compose up -d
        print_success "Services started!"
        ;;

    4)
        print_info "Stopping services..."
        docker-compose down
        print_success "Services stopped!"
        ;;

    5)
        print_info "Showing logs (Ctrl+C to exit)..."
        docker-compose logs -f
        ;;

    6)
        print_info "Creating database backup..."
        BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
        docker-compose exec -T postgres pg_dump -U postgres slack_helper > "$BACKUP_FILE"
        print_success "Database backed up to: $BACKUP_FILE"

        # Also backup ChromaDB
        print_info "Creating ChromaDB backup..."
        CHROMA_BACKUP="chromadb_backup_$(date +%Y%m%d_%H%M%S).tar.gz"
        docker-compose exec backend tar -czf /tmp/chroma_backup.tar.gz /app/chromadb_data 2>/dev/null || true
        docker cp amebo-backend:/tmp/chroma_backup.tar.gz "./$CHROMA_BACKUP" 2>/dev/null || true
        print_success "ChromaDB backed up to: $CHROMA_BACKUP"
        ;;

    7)
        print_info "Checking service status..."
        echo ""
        docker-compose ps
        echo ""

        # Health checks
        print_info "Running health checks..."

        # Backend health
        if curl -f -s http://localhost:8000/health > /dev/null 2>&1; then
            print_success "Backend is healthy"
        else
            print_error "Backend is not responding"
        fi

        # Frontend check
        if curl -f -s http://localhost:3000 > /dev/null 2>&1; then
            print_success "Frontend is accessible"
        else
            print_error "Frontend is not accessible"
        fi

        # PostgreSQL check
        if docker-compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
            print_success "PostgreSQL is ready"
        else
            print_error "PostgreSQL is not ready"
        fi
        ;;

    8)
        print_info "Exiting..."
        exit 0
        ;;

    *)
        print_error "Invalid choice"
        exit 1
        ;;
esac

echo ""
print_info "Done!"
