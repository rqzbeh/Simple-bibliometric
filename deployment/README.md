# Deployment Guide for Simple-bibliometric

This directory contains production deployment configuration files and guides.

## Files Overview

- `bibliometric-api.service` - Systemd service for the FastAPI server
- `bibliometric-worker@.service` - Systemd service template for RQ workers
- `nginx.conf` - Nginx reverse proxy configuration
- `production.env.example` - Example production environment variables

## Quick Deployment Options

### Option 1: Docker Compose (Recommended)

**Prerequisites:**
- Docker and Docker Compose installed
- `.env` file configured

**Steps:**
```bash
# 1. Create .env file
cp .env.example .env
# Edit .env with your API keys

# 2. Build and start services
docker-compose up -d

# 3. Check status
docker-compose ps
docker-compose logs -f

# 4. Scale workers if needed
docker-compose up -d --scale worker=4
```

**Access:**
- API: http://localhost:8000
- Streamlit: http://localhost:8501
- API Docs: http://localhost:8000/docs

### Option 2: Systemd (Ubuntu/Debian)

**Prerequisites:**
- Ubuntu 20.04+ or Debian 11+
- Python 3.8+
- Redis server
- Nginx

**Installation Steps:**

```bash
# 1. Install system dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv redis-server nginx

# 2. Create application directory
sudo mkdir -p /opt/Simple-bibliometric
cd /opt/Simple-bibliometric

# 3. Clone repository
sudo git clone https://github.com/rqzbeh/Simple-bibliometric.git .

# 4. Create virtual environment
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt

# 5. Configure environment
sudo cp .env.example .env
sudo nano .env  # Add your API keys

# 6. Set permissions
sudo chown -R www-data:www-data /opt/Simple-bibliometric
sudo chmod 600 /opt/Simple-bibliometric/.env

# 7. Install systemd services
sudo cp deployment/bibliometric-api.service /etc/systemd/system/
sudo cp deployment/bibliometric-worker@.service /etc/systemd/system/

# 8. Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable redis-server
sudo systemctl enable bibliometric-api
sudo systemctl enable bibliometric-worker@{1..2}  # 2 workers

sudo systemctl start redis-server
sudo systemctl start bibliometric-api
sudo systemctl start bibliometric-worker@{1..2}

# 9. Configure Nginx
sudo cp deployment/nginx.conf /etc/nginx/sites-available/bibliometric
sudo nano /etc/nginx/sites-available/bibliometric  # Update server_name
sudo ln -s /etc/nginx/sites-available/bibliometric /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# 10. Setup SSL with Let's Encrypt (optional but recommended)
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bibliometric.example.com
```

**Service Management:**
```bash
# Check status
sudo systemctl status bibliometric-api
sudo systemctl status bibliometric-worker@1
sudo systemctl status bibliometric-worker@2

# View logs
sudo journalctl -u bibliometric-api -f
sudo journalctl -u bibliometric-worker@1 -f

# Restart services
sudo systemctl restart bibliometric-api
sudo systemctl restart bibliometric-worker@{1..2}

# Stop services
sudo systemctl stop bibliometric-api
sudo systemctl stop bibliometric-worker@{1..2}
```

### Option 3: Kubernetes

**Prerequisites:**
- Kubernetes cluster
- kubectl configured
- Docker registry access

**Basic Deployment:**

1. Create namespace:
```bash
kubectl create namespace bibliometric
```

2. Create secret for environment variables:
```bash
kubectl create secret generic bibliometric-env \
  --from-env-file=.env \
  -n bibliometric
```

3. Deploy Redis:
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: bibliometric
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: bibliometric
spec:
  selector:
    app: redis
  ports:
  - port: 6379
EOF
```

4. Deploy API and Workers:
```bash
# Build and push image
docker build -t your-registry/bibliometric:latest .
docker push your-registry/bibliometric:latest

# Deploy
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bibliometric-api
  namespace: bibliometric
spec:
  replicas: 2
  selector:
    matchLabels:
      app: bibliometric-api
  template:
    metadata:
      labels:
        app: bibliometric-api
    spec:
      containers:
      - name: api
        image: your-registry/bibliometric:latest
        ports:
        - containerPort: 8000
        envFrom:
        - secretRef:
            name: bibliometric-env
        env:
        - name: BIB_USE_RQ
          value: "1"
        - name: REDIS_URL
          value: "redis://redis:6379/0"
---
apiVersion: v1
kind: Service
metadata:
  name: bibliometric-api
  namespace: bibliometric
spec:
  selector:
    app: bibliometric-api
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
EOF
```

## Production Checklist

- [ ] Configure all required API keys in `.env`
- [ ] Set `LOG_LEVEL=INFO` or `WARNING` in production
- [ ] Enable Redis persistence (`appendonly yes`)
- [ ] Configure SSL/TLS certificates
- [ ] Set up monitoring (Prometheus, Grafana)
- [ ] Configure log rotation
- [ ] Set up automated backups for Redis and job outputs
- [ ] Configure firewall rules
- [ ] Set up rate limiting
- [ ] Configure CORS appropriately
- [ ] Enable security headers
- [ ] Set up health checks and alerting
- [ ] Document incident response procedures

## Monitoring

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# Redis health
redis-cli ping

# RQ queue status
rq info --url redis://localhost:6379/0
```

### Metrics to Monitor

- API response times
- Queue length (RQ)
- Failed job count
- Memory usage (Redis, API, Workers)
- CPU usage
- Disk space (especially `/app/analysis_outputs`)
- Network bandwidth
- Error rates

### Logging

Application logs are written to:
- Systemd: `journalctl -u bibliometric-api`
- Docker: `docker-compose logs -f`
- Nginx: `/var/log/nginx/bibliometric-*.log`

## Backup and Recovery

### Backup Redis Data
```bash
# Trigger Redis save
redis-cli SAVE

# Copy dump file
cp /var/lib/redis/dump.rdb /backup/redis-$(date +%Y%m%d-%H%M%S).rdb
```

### Backup Job Outputs
```bash
tar -czf /backup/jobs-$(date +%Y%m%d-%H%M%S).tar.gz \
  /opt/Simple-bibliometric/analysis_outputs
```

### Automated Backup Script
```bash
#!/bin/bash
# /opt/Simple-bibliometric/scripts/backup.sh

BACKUP_DIR="/backup/bibliometric"
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p $BACKUP_DIR

# Backup Redis
redis-cli SAVE
cp /var/lib/redis/dump.rdb "$BACKUP_DIR/redis-$DATE.rdb"

# Backup job outputs
tar -czf "$BACKUP_DIR/jobs-$DATE.tar.gz" \
  /opt/Simple-bibliometric/analysis_outputs

# Cleanup old backups (keep last 7 days)
find $BACKUP_DIR -name "*.rdb" -mtime +7 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete
```

### Schedule with Cron
```bash
# Add to crontab
0 2 * * * /opt/Simple-bibliometric/scripts/backup.sh
```

## Scaling

### Horizontal Scaling

**Docker Compose:**
```bash
docker-compose up -d --scale worker=4
```

**Kubernetes:**
```bash
kubectl scale deployment bibliometric-api --replicas=4 -n bibliometric
kubectl scale deployment bibliometric-worker --replicas=8 -n bibliometric
```

### Vertical Scaling

**Increase worker resources:**
```yaml
# docker-compose.yml
worker:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 4G
```

## Troubleshooting

### High Memory Usage
```bash
# Check Redis memory
redis-cli INFO memory

# Clear old jobs
redis-cli DEL rq:job:* rq:finished:*

# Restart services
sudo systemctl restart bibliometric-worker@{1..2}
```

### Jobs Stuck in Queue
```bash
# Check queue
rq info --url redis://localhost:6379/0

# Empty failed queue
rq empty failed --url redis://localhost:6379/0

# Restart workers
sudo systemctl restart bibliometric-worker@{1..2}
```

### API Not Responding
```bash
# Check logs
sudo journalctl -u bibliometric-api -n 100

# Check if port is in use
sudo netstat -tulpn | grep 8000

# Restart service
sudo systemctl restart bibliometric-api
```

## Security Notes

1. **Never commit `.env` files** to version control
2. **Use strong Redis passwords** in production
3. **Enable SSL/TLS** for all external connections
4. **Regularly update dependencies**: `pip install --upgrade -r requirements.txt`
5. **Monitor for security vulnerabilities**: Use tools like `pip-audit`
6. **Implement rate limiting** to prevent abuse
7. **Restrict CORS origins** to known domains
8. **Use secrets management** (AWS Secrets Manager, HashiCorp Vault) for production

## Support

For deployment issues:
1. Check logs for error messages
2. Verify all configuration files
3. Ensure all dependencies are installed
4. Review the main README.md troubleshooting section
5. Open an issue on GitHub with deployment details
