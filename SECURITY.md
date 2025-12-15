# Security Policy

## Supported Versions

We actively support the following versions with security updates:

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

### How to Report

If you discover a security vulnerability, please follow these steps:

1. **Email**: Send details to the repository maintainers (check GitHub profile for contact)
2. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if available)
3. **Timeline**: 
   - We aim to acknowledge reports within 48 hours
   - We'll provide a detailed response within 7 days
   - We'll work on a fix and keep you updated

### What to Expect

- **Acknowledgment**: We'll confirm receipt of your report
- **Assessment**: We'll evaluate the severity and impact
- **Fix Development**: We'll work on a patch
- **Disclosure**: We'll coordinate disclosure timing with you
- **Credit**: We'll credit you in the security advisory (unless you prefer anonymity)

## Security Best Practices

### For Users

#### API Key Management

**❌ Never:**
- Commit API keys to version control
- Share API keys in logs or error messages
- Use production keys in development
- Hardcode keys in source code
- Post keys in public forums or issues

**✅ Always:**
- Store keys in `.env` file (gitignored)
- Use environment variables in production
- Rotate keys regularly (quarterly recommended)
- Use separate keys for dev/staging/prod
- Use secrets management services in production

#### Configuration Security

**Production .env Security:**
```bash
# Set restrictive permissions
chmod 600 .env

# Ensure ownership
chown www-data:www-data .env
```

**Secrets Management:**
- AWS Secrets Manager
- HashiCorp Vault
- Azure Key Vault
- Google Cloud Secret Manager

#### Network Security

**Enable HTTPS:**
```nginx
# Force HTTPS redirection
server {
    listen 80;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
}
```

**Rate Limiting:**
```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

location /api {
    limit_req zone=api burst=20 nodelay;
}
```

#### Redis Security

**Secure Redis Configuration:**
```conf
# /etc/redis/redis.conf
bind 127.0.0.1
requirepass your-strong-password-here
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command CONFIG ""
```

**Use Redis Password:**
```env
REDIS_URL=redis://:your-password@localhost:6379/0
```

#### Input Validation

The application validates user input, but additional validation at the proxy level is recommended:

```nginx
# Limit request size
client_max_body_size 10M;

# Block suspicious patterns
if ($request_uri ~* "(\.\.\/|eval\(|base64_)") {
    return 403;
}
```

### For Developers

#### Secure Coding Practices

**Input Validation:**
```python
# Always validate and sanitize user input
def validate_query(query: str) -> str:
    if not query or len(query) > 1000:
        raise ValueError("Invalid query length")
    
    # Remove potentially dangerous characters
    sanitized = re.sub(r'[^\w\s\-]', '', query)
    return sanitized.strip()
```

**SQL Injection Prevention:**
```python
# Use parameterized queries
cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))

# Never use string formatting
# BAD: f"SELECT * FROM jobs WHERE id = {job_id}"
```

**Path Traversal Prevention:**
```python
import os

def safe_file_path(base_dir: str, filename: str) -> str:
    """Ensure file path is within base directory."""
    # Resolve to absolute path
    requested_path = os.path.abspath(os.path.join(base_dir, filename))
    
    # Check it's within base directory
    if not requested_path.startswith(os.path.abspath(base_dir)):
        raise ValueError("Invalid file path")
    
    return requested_path
```

**Command Injection Prevention:**
```python
# Use subprocess with list arguments
import subprocess

# SAFE
subprocess.run(["ls", "-la", directory])

# UNSAFE - vulnerable to injection
# subprocess.run(f"ls -la {directory}", shell=True)
```

#### Dependency Management

**Check for Vulnerabilities:**
```bash
# Install safety
pip install safety

# Check dependencies
safety check

# Or use pip-audit
pip install pip-audit
pip-audit
```

**Keep Dependencies Updated:**
```bash
# Check outdated packages
pip list --outdated

# Update all packages
pip install --upgrade -r requirements.txt

# Review changes before updating
pip-review
```

#### Secrets in Code

**Use Environment Variables:**
```python
import os
from dotenv import load_dotenv

load_dotenv()

# Good
api_key = os.getenv("API_KEY")

# Bad - hardcoded secret
# api_key = "sk-1234567890abcdef"
```

**Secret Detection:**
```bash
# Use git-secrets to prevent commits with secrets
git clone https://github.com/awslabs/git-secrets
cd git-secrets
make install
cd /path/to/Simple-bibliometric
git secrets --install
git secrets --register-aws
```

#### Logging Security

**Don't Log Sensitive Data:**
```python
import logging

logger = logging.getLogger(__name__)

# Good
logger.info(f"User {user_id} made request")

# Bad - logs API key
# logger.debug(f"Using API key: {api_key}")
```

**Sanitize Error Messages:**
```python
try:
    result = api_call(api_key)
except Exception as e:
    # Good - generic message
    logger.error("API call failed")
    
    # Bad - exposes internal details
    # logger.error(f"API call failed with key {api_key}: {e}")
```

#### Authentication & Authorization

**API Token Validation:**
```python
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def verify_token(credentials = Security(security)):
    token = credentials.credentials
    
    if not is_valid_token(token):
        raise HTTPException(status_code=403, detail="Invalid token")
    
    return token
```

**Rate Limiting:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/analyze")
@limiter.limit("10/minute")
async def analyze_endpoint():
    # Implementation
    pass
```

## Known Security Considerations

### Current Security Features

✅ API keys stored in environment variables  
✅ Input validation on user queries  
✅ Rate limiting support in crawlers  
✅ Secure file path handling  
✅ CORS configuration available  
✅ Redis authentication support  
✅ TLS/SSL support via reverse proxy  

### Recommendations for Production

1. **Enable HTTPS**: Use Let's Encrypt or commercial SSL certificate
2. **Implement Authentication**: Add API key or OAuth2 authentication
3. **Enable Rate Limiting**: Prevent abuse and DoS attacks
4. **Secure Redis**: Enable password, bind to localhost
5. **Monitor Logs**: Set up log monitoring and alerting
6. **Regular Updates**: Keep all dependencies current
7. **Backup Encryption**: Encrypt backups containing sensitive data
8. **Network Segmentation**: Use VPC/firewall rules to isolate services

## Compliance

### Data Privacy

- **GDPR**: If handling EU user data, implement appropriate controls
- **User Data**: Minimize collection and storage of personal data
- **Data Retention**: Implement policies for data deletion
- **Third-party APIs**: Respect terms of service for all data sources

### API Terms of Service

When using this software, ensure compliance with:
- Groq API Terms: https://groq.com/terms/
- NCBI Usage Guidelines: https://www.ncbi.nlm.nih.gov/home/about/policies/
- Elsevier Developer Policies: https://dev.elsevier.com/
- Clarivate Terms: https://clarivate.com/legal/
- IEEE Terms: https://www.ieee.org/terms
- And terms for other data sources used

## Security Updates

Security updates will be released as patches to supported versions. Updates will be announced via:

- GitHub Security Advisories
- Release notes
- Project README

## Security Checklist for Deployment

Before deploying to production:

- [ ] API keys stored securely (not in code)
- [ ] `.env` file has restrictive permissions (600)
- [ ] HTTPS enabled with valid certificate
- [ ] Redis password configured
- [ ] Rate limiting enabled
- [ ] CORS properly configured (not `allow_origins=["*"]`)
- [ ] Firewall rules configured
- [ ] Monitoring and alerting set up
- [ ] Regular backup schedule configured
- [ ] Dependencies are up to date
- [ ] Vulnerability scan performed
- [ ] Security headers configured in Nginx
- [ ] Log monitoring enabled
- [ ] Incident response plan documented

## Contact

For security concerns, please check the repository's Security tab on GitHub or contact the maintainers directly.

---

**Thank you for helping keep Simple-bibliometric and its users safe!**
