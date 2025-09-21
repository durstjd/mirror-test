# SSL Certificate Setup Guide

This guide explains how to properly configure SSL certificates for Mirror Test, including LDAPS authentication and web server HTTPS.

## Table of Contents

1. [LDAPS Authentication Setup](#ldaps-authentication-setup)
2. [Web Server SSL Setup](#web-server-ssl-setup)
3. [System Trust Store Configuration](#system-trust-store-configuration)
4. [Troubleshooting](#troubleshooting)

## LDAPS Authentication Setup

### Prerequisites

- LDAP server with SSL/TLS enabled
- Access to the LDAP server's certificate
- Root/sudo access on the Mirror Test server

### Method 1: System Trust Store (Recommended)

This is the most secure and maintainable approach:

#### 1. Extract the LDAP Server Certificate

```bash
# Get the LDAP server's certificate
openssl s_client -connect your-ldap-server.com:636 -showcerts < /dev/null 2>/dev/null | openssl x509 -outform PEM > ldap-server.crt
```

#### 2. Add to System Trust Store

```bash
# Copy certificate to system trust store
sudo cp ldap-server.crt /etc/pki/ca-trust/source/anchors/

# Update the CA trust store
sudo update-ca-trust

# Verify the certificate was added
sudo trust list | grep -i your-domain
```

#### 3. Configure Mirror Test

Update your `~/.config/mirror-test/server-config.yaml`:

```yaml
ldaps:
  ldap_server: "your-ldap-server.com"
  ldap_port: 636
  ldap_use_ssl: true
  ldap_verify_cert: true
  ldap_ca_cert: "/etc/pki/ca-trust/source/anchors/ldap-server.crt"
  ldap_timeout: 10
  base_dn: "DC=example,DC=com"
  user_dn_template: "{username}@example.com"
  group_dn: "OU=Groups,{base_dn}"
```

### Method 2: Custom Certificate File

If you prefer to keep certificates in a custom location:

#### 1. Extract the LDAP Server Certificate

```bash
# Get the LDAP server's certificate
openssl s_client -connect your-ldap-server.com:636 -showcerts < /dev/null 2>/dev/null | openssl x509 -outform PEM > ~/.config/mirror-test/ssl/ldap-server.crt
```

#### 2. Configure Mirror Test

```yaml
ldaps:
  ldap_server: "your-ldap-server.com"
  ldap_port: 636
  ldap_use_ssl: true
  ldap_verify_cert: true
  ldap_ca_cert: "/home/username/.config/mirror-test/ssl/ldap-server.crt"
  ldap_timeout: 10
  base_dn: "DC=example,DC=com"
  user_dn_template: "{username}@example.com"
  group_dn: "OU=Groups,{base_dn}"
```

## Web Server SSL Setup

### Generate Self-Signed Certificate

For development or internal use:

```bash
# Create SSL directory
mkdir -p ~/.config/mirror-test/ssl

# Generate private key
openssl genrsa -out ~/.config/mirror-test/ssl/mirror-test.key 2048

# Generate certificate
openssl req -x509 -newkey rsa:2048 -keyout ~/.config/mirror-test/ssl/mirror-test.key -out ~/.config/mirror-test/ssl/mirror-test.crt -days 365 -nodes -subj "/CN=your-server-ip-or-hostname"
```

### Configure Web Server SSL

Update your `~/.config/mirror-test/server-config.yaml`:

```yaml
ssl:
  enabled: true
  cert_file: "/home/username/.config/mirror-test/ssl/mirror-test.crt"
  key_file: "/home/username/.config/mirror-test/ssl/mirror-test.key"
  require_ssl: true
  port: 8443
  verify_cert: false  # Set to true for production with valid certificates
```

## System Trust Store Configuration

### RHEL/CentOS/Fedora

```bash
# Add certificate to trust store
sudo cp certificate.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust

# Verify certificate is trusted
sudo trust list | grep -i your-domain
```

### Ubuntu/Debian

```bash
# Add certificate to trust store
sudo cp certificate.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates

# Verify certificate is trusted
openssl verify certificate.crt
```

### macOS

```bash
# Add certificate to keychain
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain certificate.crt
```

## Troubleshooting

### Common Issues

#### 1. "LDAP server is not available"

**Cause**: SSL certificate verification is failing.

**Solution**: 
- Ensure the certificate is in the system trust store
- Verify the certificate path in configuration
- Check that `ldap_verify_cert: true` is set

#### 2. "SSL certificate verification failed"

**Cause**: The certificate is not trusted by the system.

**Solution**:
- Add the certificate to the system trust store
- Restart the Mirror Test application
- Verify with `openssl verify certificate.crt`

#### 3. "Certificate verify failed: ok"

**Cause**: Browser or client doesn't trust the self-signed certificate.

**Solution**:
- Accept the certificate in your browser
- Add the certificate to the system trust store
- Use a valid certificate from a trusted CA

### Verification Commands

```bash
# Test LDAP connection
ldapsearch -H ldaps://your-ldap-server.com:636 -D "username@domain.com" -W -b "DC=domain,DC=com" -x

# Test with specific certificate
LDAPTLS_CACERT="/path/to/certificate.crt" ldapsearch -H ldaps://your-ldap-server.com:636 -D "username@domain.com" -W -b "DC=domain,DC=com" -x

# Verify certificate
openssl verify certificate.crt

# Check system trust store
sudo trust list | grep -i your-domain
```

### Security Best Practices

1. **Always use `ldap_verify_cert: true`** - Never disable certificate verification in production
2. **Use system trust store** - More secure than custom certificate files
3. **Regular certificate renewal** - Monitor certificate expiration dates
4. **Strong private keys** - Use at least 2048-bit RSA keys
5. **Proper file permissions** - Secure certificate files with appropriate permissions

## Support

If you encounter issues with SSL configuration:

1. Check the Mirror Test logs for detailed error messages
2. Verify certificate validity with `openssl verify`
3. Test LDAP connectivity with `ldapsearch`
4. Ensure all certificate paths are correct and accessible

