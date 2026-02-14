# Deployment Guide

This guide covers deploying Smith in production environments.

## Production Considerations

### System Requirements

**Minimum:**
- Python 3.10+
- 512MB RAM
- 1 CPU core
- 100MB disk space

**Recommended:**
- Python 3.11+
- 2GB RAM
- 2+ CPU cores
- 1GB disk space (for logs and traces)

### Environment Setup

#### Production Environment Variables

```ini
# Required
GROQ_API_KEY=your_production_key

# Optional Tool APIs
GOOGLE_API_KEY=your_key
SEARCH_ENGINE_ID=your_cx

# Production Settings
SMITH_ENV=production
SMITH_LOG_LEVEL=INFO
SMITH_MAX_RETRIES=3
SMITH_DEFAULT_TIMEOUT=60

# Rate Limiting
SMITH_ENABLE_RATE_LIMITING=true

# Sub-Agent Configuration
SMITH_MAX_SUBAGENT_DEPTH=3
SMITH_MAX_FLEET_SIZE=5
```

#### Logging Configuration

```python
# config.py
import logging

if os.getenv("SMITH_ENV") == "production":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("smith.log"),
            logging.StreamHandler()
        ]
    )
```

---

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy application
COPY src/ ./src/
COPY .env .env

# Expose port if running as service
EXPOSE 8000

# Run Smith
CMD ["python", "-m", "smith.cli.main"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  smith:
    build: .
    env_file:
      - .env
    volumes:
      - ./logs:/app/logs
      - ./traces:/app/traces
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

### Building and Running

```bash
# Build image
docker build -t smith:latest .

# Run container
docker run -d \
  --name smith \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  smith:latest
```

---

## Cloud Deployment

### AWS Deployment

#### EC2 Instance

```bash
# Launch EC2 instance (Ubuntu 22.04)
# t3.medium recommended (2 vCPU, 4GB RAM)

# SSH into instance
ssh -i key.pem ubuntu@instance-ip

# Install dependencies
sudo apt update
sudo apt install -y python3.11 python3-pip git

# Clone and install Smith
git clone https://github.com/Karunya-Muddana/project-smith.git
cd project-smith
pip3 install -e .

# Configure environment
nano .env  # Add API keys

# Run as service (see systemd section)
```

#### AWS Lambda

Smith can run as Lambda function for event-driven execution:

```python
# lambda_handler.py
import json
from smith.core.orchestrator import smith_orchestrator

def lambda_handler(event, context):
    task = event.get('task', '')
    
    result = None
    for evt in smith_orchestrator(task):
        if evt["type"] == "final_answer":
            result = evt["payload"]["response"]
    
    return {
        'statusCode': 200,
        'body': json.dumps({'result': result})
    }
```

### Google Cloud Platform

#### Cloud Run

```yaml
# cloudbuild.yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/smith', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/smith']
  - name: 'gcr.io/cloud-builders/gcloud'
    args:
      - 'run'
      - 'deploy'
      - 'smith'
      - '--image=gcr.io/$PROJECT_ID/smith'
      - '--platform=managed'
      - '--region=us-central1'
```

### Azure Deployment

#### Container Instances

```bash
# Create resource group
az group create --name smith-rg --location eastus

# Deploy container
az container create \
  --resource-group smith-rg \
  --name smith \
  --image smith:latest \
  --cpu 2 \
  --memory 4 \
  --environment-variables \
    GROQ_API_KEY=$GROQ_API_KEY
```

---

## Process Management

### systemd Service

Create `/etc/systemd/system/smith.service`:

```ini
[Unit]
Description=Smith Agent Runtime
After=network.target

[Service]
Type=simple
User=smith
WorkingDirectory=/opt/smith
Environment="PATH=/opt/smith/venv/bin"
EnvironmentFile=/opt/smith/.env
ExecStart=/opt/smith/venv/bin/python -m smith.cli.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable smith
sudo systemctl start smith
sudo systemctl status smith
```

### Supervisor

```ini
[program:smith]
command=/opt/smith/venv/bin/python -m smith.cli.main
directory=/opt/smith
user=smith
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/smith/smith.log
```

---

## Monitoring and Logging

### Structured Logging

```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        return json.dumps(log_data)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
```

### Metrics Collection

```python
# Track execution metrics
from prometheus_client import Counter, Histogram

task_counter = Counter('smith_tasks_total', 'Total tasks executed')
task_duration = Histogram('smith_task_duration_seconds', 'Task duration')

# In orchestrator
task_counter.inc()
with task_duration.time():
    # Execute task
    pass
```

### Health Checks

```python
# health_check.py
def health_check():
    try:
        from smith.core.orchestrator import smith_orchestrator
        # Quick test
        for event in smith_orchestrator("test"):
            if event["type"] in ["final_answer", "error"]:
                return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

---

## Security Best Practices

### API Key Management

**Use Secret Management:**
```bash
# AWS Secrets Manager
aws secretsmanager create-secret \
  --name smith/groq-api-key \
  --secret-string "your-key"

# Retrieve in code
import boto3
client = boto3.client('secretsmanager')
response = client.get_secret_value(SecretId='smith/groq-api-key')
```

### Network Security

```bash
# Firewall rules (UFW)
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 8000/tcp  # Smith API (if applicable)
sudo ufw enable
```

### Input Sanitization

```python
def sanitize_input(user_input: str) -> str:
    # Remove potentially dangerous characters
    import re
    return re.sub(r'[^\w\s\-.,?!]', '', user_input)
```

---

## Scaling Strategies

### Horizontal Scaling

Deploy multiple Smith instances behind load balancer:

```yaml
# docker-compose.yml
version: '3.8'

services:
  smith-1:
    build: .
    env_file: .env
  
  smith-2:
    build: .
    env_file: .env
  
  smith-3:
    build: .
    env_file: .env
  
  nginx:
    image: nginx
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - smith-1
      - smith-2
      - smith-3
```

### Vertical Scaling

Increase resources for single instance:
- More CPU cores for parallel execution
- More RAM for large traces
- SSD storage for faster I/O

### Caching

Implement result caching for deterministic tools:

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_tool_call(tool_name, **kwargs):
    # Execute tool
    pass
```

---

## Backup and Recovery

### Trace Backup

```bash
# Backup traces
tar -czf traces-$(date +%Y%m%d).tar.gz /app/traces/

# Upload to S3
aws s3 cp traces-*.tar.gz s3://smith-backups/
```

### Configuration Backup

```bash
# Backup configuration
cp .env .env.backup
cp src/smith/tools/registry.json registry.json.backup
```

---

## Performance Tuning

### Optimize Tool Timeouts

```python
# Reduce timeouts for fast tools
DEFAULT_TIMEOUT = 30  # seconds

# Increase for slow tools
SLOW_TOOL_TIMEOUT = 120
```

### Connection Pooling

```python
import requests
from requests.adapters import HTTPAdapter

session = requests.Session()
adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
session.mount('https://', adapter)
```

### Memory Management

```python
# Limit trace size
MAX_TRACE_SIZE = 1000  # entries

if len(trace) > MAX_TRACE_SIZE:
    # Write to disk and clear
    with open(f"trace_{timestamp}.json", "w") as f:
        json.dump(trace, f)
    trace.clear()
```

---

## Troubleshooting Production Issues

### High Memory Usage

```bash
# Monitor memory
top -p $(pgrep -f smith)

# Reduce fleet size
export SMITH_MAX_FLEET_SIZE=2
```

### API Rate Limiting

```python
# Increase rate limit delays
DEFAULT_LIMITS = {
    "llm_caller": 2.0,  # Increase from 1.0
    "google_search": 1.0,
}
```

### Slow Execution

```bash
# Enable profiling
python -m cProfile -o smith.prof -m smith.cli.main

# Analyze
python -m pstats smith.prof
```

---

## Maintenance

### Log Rotation

```bash
# logrotate config
/var/log/smith/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### Dependency Updates

```bash
# Update dependencies
pip install --upgrade -e .

# Test after update
pytest
```

### Monitoring Checklist

- [ ] API key expiration dates
- [ ] Disk space for logs and traces
- [ ] Memory usage trends
- [ ] API quota consumption
- [ ] Error rates
- [ ] Average execution time
