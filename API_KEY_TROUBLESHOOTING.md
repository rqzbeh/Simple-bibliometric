# API Key Authentication Troubleshooting Guide

## Current Status

Your API keys for **Scopus**, **ScienceDirect**, and **WoS** are being rejected with **401 Unauthorized** errors. This indicates the keys themselves are invalid or not properly configured.

### Error Messages

- **Scopus & ScienceDirect**: `APIKEY_INVALID - The provided apiKey is invalid.`
- **WoS**: `Invalid authentication credentials`
- **Springer**: `API key is invalid or missing`

### Root Cause

The authentication endpoint (`https://api.elsevier.com/authenticate`) itself is returning **401 Unauthorized**, which means your API keys cannot authenticate with the provider's services.

## Solutions

### 1. **Verify Your API Keys**

Ensure your keys are:
- **Not expired** — Check the provider's dashboard for expiration dates
- **Properly configured** — Keys must be activated for API access
- **Correct scope** — Some keys are limited to specific databases or access levels

#### For Scopus/ScienceDirect (Elsevier):
1. Visit [Elsevier Developer Portal](https://dev.elsevier.com/)
2. Log in with your institutional or personal account
3. Navigate to **My API Keys**
4. Verify the key status is **Active**
5. Check that the key has **API access** permission (not just web access)
6. Confirm the key is set to access **all products** or specifically **Scopus** and **ScienceDirect**

#### For Web of Science (Clarivate):
1. Visit [Clarivate Developer Portal](https://developer.clarivate.com/)
2. Log in with your account
3. Verify your API key is **active** and **not revoked**
4. Ensure the key is assigned to the **WoS API** product

#### For Springer:
1. Visit [Springer API Console](https://dev.springernature.com/)
2. Check your API key status
3. Verify it's **active** and **registered**

### 2. **Institutional Access (IP-based)**

If your institution has a subscription to these databases, you may be able to use **IP-based entitlement** instead of API keys:

- **Elsevier (Scopus/ScienceDirect)**: If your request comes from an institution IP, you don't need an API key
- **WoS**: Supports IP-based authentication for institutional users

To test IP-based access:
1. Ensure you're on your institution's network or VPN
2. Set `SCOPUS_API_KEY=""` (empty string)
3. Set `SCIENCEDIRECT_API_KEY=""` (empty string)
4. Set `WOS_API_KEY=""` (empty string)
5. The system will attempt IP-based authentication

### 3. **Institutional Token (insttoken)**

For **Elsevier products** (Scopus/ScienceDirect), set the institutional token:

```bash
export ELS_INSTTOKEN="your-institutional-token-here"
```

Get your institutional token from:
1. [Elsevier API Portal](https://dev.elsevier.com/)
2. **My Settings** → **Institutional Settings**
3. Copy your institutional token

### 4. **Contact Support**

If your keys are recent and should be valid:

- **Elsevier**: support@elsevier.com or [API Support Form](https://dev.elsevier.com/support)
- **Clarivate**: [Support Portal](https://support.clarivate.com/)
- **Springer**: [Developer Support](https://dev.springernature.com/support)

### 5. **Test Authentication Endpoints**

Use these curl commands to test if your keys work:

#### Scopus/ScienceDirect:
```bash
curl -X GET "https://api.elsevier.com/authenticate?platform=SCOPUS" \
  -H "X-ELS-APIKey: YOUR_API_KEY"
```

#### WoS:
```bash
curl -X GET "https://api.clarivate.com/api/wos?databaseId=WOS&usrQuery=cancer&count=1" \
  -H "X-ApiKey: YOUR_WOS_API_KEY"
```

If you get a `401 Unauthorized` response, your key is not valid for that endpoint.

## Working Providers

Based on your current API keys, these providers are working:
- **PubMed** — No authentication required
- **Gene, Genome** — Working with NCBI token
- **SAGE** — Public access (limited)

## Next Steps

1. **Validate your API keys** at the respective provider portals
2. **Check entitlements** — Ensure your account has API access enabled
3. **Test endpoints** using the curl commands above
4. **Contact provider support** if keys should be valid but aren't working
5. **Update environment variables** once you have valid keys

## Code Changes Made

- ✅ Added verbose logging to authtoken exchange (`_get_authtoken()`)
- ✅ Added insttoken support for institutional access
- ✅ Added fallback to APIKey-only headers when authtoken fails
- ✅ Improved error messages and diagnostics

The code is now correctly attempting all supported authentication methods. The 401 responses you're seeing are from the **provider servers rejecting your credentials**, not from code issues.
