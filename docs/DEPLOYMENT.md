# Deployment Guide - Amebo

This guide covers deploying Amebo to a production server using Docker.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Server Setup](#server-setup)
- [Deployment Steps](#deployment-steps)
- [Environment Configuration](#environment-configuration)
- [Running the Application](#running-the-application)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### Server Requirements

- **OS**: Ubuntu 20.04+ or similar Linux distribution
- **RAM**: Minimum 4GB (8GB recommended)
- **CPU**: 2+ cores
- **Storage**: 20GB+ available
- **Network**: Open ports 80, 443 (for web traffic)

### Software Requirements

Install on your server:

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install docker-compose -y

# Add your user to docker group (logout and login after this)
sudo usermod -aG docker $USER

# Install Git
sudo apt install git -y
```

## Server Setup

### 1. Clone the Repository

```bash
cd ~
git clone <your-repository-url> amebo
cd amebo
```

### 2. Configure Environment Variables

Create production environment file:

```bash
cp .env.production.example .env.production
nano .env.production
```

Fill in all required values (see [Environment Configuration](#environment-configuration) below).

Also update the backend environment:

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

### 3. Generate Security Keys

```bash
# Generate encryption key for Fernet
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Generate JWT secret (or use openssl)
openssl rand -hex 32
```

Add these to your `.env.production` and `backend/.env` files.

## Environment Configuration

### Critical Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | Database password | `secure_db_pass_123` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:password@postgres:5432/slack_helper` |
| `SLACK_BOT_TOKEN` | Slack bot token | `xoxb-...` |
| `SLACK_APP_TOKEN` | Slack app token for Socket Mode | `xapp-...` |
| `ANTHROPIC_API_KEY` | Claude API key | `sk-ant-...` |
| `ENCRYPTION_KEY` | Fernet encryption key | Generated from above |
| `JWT_SECRET_KEY` | JWT signing key | Generated from above |
| `NEXT_PUBLIC_API_URL` | Backend API URL | `http://your-ip:8000` or `https://api.yourdomain.com` |

### Email Configuration

For production, use a reliable SMTP service:

- **SendGrid**: Professional email delivery
- **AWS SES**: Cost-effective for AWS users
- **Mailgun**: Easy to set up

Example for Gmail (less reliable for production):

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-specific-password
FROM_EMAIL=noreply@yourdomain.com
```

## Deployment Steps

### 1. Build and Start Services

```bash
# Load environment variables
source .env.production

# Build and start all services
docker-compose up -d --build
```

This will:
- Build backend and frontend Docker images
- Start PostgreSQL database
- Start ChromaDB vector database
- Start backend API server
- Start frontend web application

### 2. Verify Services

Check if all containers are running:

```bash
docker-compose ps
```

You should see:
- `amebo-postgres` - healthy
- `amebo-chromadb` - healthy
- `amebo-backend` - running
- `amebo-frontend` - running

### 3. View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
```

### 4. Initialize Database

The database will auto-initialize on first run. Verify:

```bash
docker-compose exec backend python -c "from src.db.connection import DatabaseConnection; print('DB Connected')"
```

## Running the Application

### Access Points

- **Frontend**: `http://your-server-ip:3000`
- **Backend API**: `http://your-server-ip:8000`
- **API Docs**: `http://your-server-ip:8000/docs`

### Set Up Nginx Reverse Proxy (Recommended)

For production with SSL:

```bash
sudo apt install nginx certbot python3-certbot-nginx -y
```

Create Nginx config:

```bash
sudo nano /etc/nginx/sites-available/amebo
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # Backend API
    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Enable and get SSL:

```bash
sudo ln -s /etc/nginx/sites-available/amebo /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
sudo certbot --nginx -d your-domain.com
```

## Maintenance

### Updating the Application

```bash
cd ~/amebo
git pull
docker-compose down
docker-compose up -d --build
```

### Backing Up Data

```bash
# Backup PostgreSQL
docker-compose exec postgres pg_dump -U postgres slack_helper > backup_$(date +%Y%m%d).sql

# Backup ChromaDB
docker-compose exec backend tar -czf /tmp/chromadb_backup.tar.gz /app/chromadb_data
docker cp amebo-backend:/tmp/chromadb_backup.tar.gz ./chromadb_backup_$(date +%Y%m%d).tar.gz
```

### Viewing Logs

```bash
# Real-time logs
docker-compose logs -f backend

# Last 100 lines
docker-compose logs --tail=100 backend

# Export logs
docker-compose logs backend > backend_logs.txt
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart backend
docker-compose restart frontend
```

## Troubleshooting

### Container Won't Start

```bash
# Check container logs
docker-compose logs backend

# Check container status
docker-compose ps

# Rebuild from scratch
docker-compose down -v
docker-compose up -d --build
```

### Database Connection Issues

```bash
# Check PostgreSQL is running
docker-compose exec postgres pg_isready

# Check connection from backend
docker-compose exec backend python -c "
from src.db.connection import DatabaseConnection
db = DatabaseConnection.get_connection()
print('Connected successfully')
"
```

### Frontend Can't Reach Backend

1. Check `NEXT_PUBLIC_API_URL` in `.env.production`
2. Ensure it uses your server's public IP or domain
3. Verify backend is accessible: `curl http://your-server:8000/health`

### Slack Commands Not Working

1. Verify Socket Mode is enabled in Slack App settings
2. Check `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are correct
3. View backend logs: `docker-compose logs -f backend`
4. Look for "Slack listener ready" message

### Out of Memory

```bash
# Check memory usage
docker stats

# Increase swap space
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### ChromaDB Issues

```bash
# Reset ChromaDB (WARNING: Deletes all vector data)
docker-compose down
docker volume rm slack-helper_chromadb_data
docker-compose up -d
```

## Security Best Practices

1. **Never commit `.env` or `.env.production`** - keep secrets secure
2. **Use strong passwords** - generate random passwords for production
3. **Enable firewall** - only allow necessary ports
   ```bash
   sudo ufw allow 22    # SSH
   sudo ufw allow 80    # HTTP
   sudo ufw allow 443   # HTTPS
   sudo ufw enable
   ```
4. **Regular updates** - keep Docker and system packages updated
5. **Monitor logs** - set up log monitoring and alerts
6. **Backup regularly** - automate database backups

## Monitoring

### Health Checks

```bash
# Backend health
curl http://localhost:8000/health

# ChromaDB health
curl http://localhost:8001/api/v1/heartbeat

# PostgreSQL health
docker-compose exec postgres pg_isready
```

### Resource Monitoring

```bash
# Container stats
docker stats

# Disk usage
df -h
docker system df
```

## Support

For issues and questions:

1. Check logs: `docker-compose logs -f`
2. Review [Architecture Documentation](./ARCHITECTURE.md)
3. Check [API Documentation](./API.md)
4. Open an issue on GitHub

---

**Production Ready Checklist:**

- [ ] Environment variables configured
- [ ] Security keys generated
- [ ] Database initialized
- [ ] SSL certificate installed
- [ ] Firewall configured
- [ ] Backup strategy in place
- [ ] Monitoring set up
- [ ] Slack app configured
- [ ] Domain/DNS configured
- [ ] Email SMTP tested
