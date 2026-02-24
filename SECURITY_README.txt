# Corporate Security Certificates Setup Guide

This folder contains the required SSL certificates needed to bypass corporate firewalls (like Zscaler) for the AI Transcriptor application.

## 1. What is included here?
- **custom_bundle.pem**: This is the compiled SSL certificate bundle. It contains the standard web certificates PLUS your company's specific Zscaler/Proxy intercept certificates. 

## 2. Default Setup (Automatic)
The AI Transcriptor application is hard-coded to automatically look for `custom_bundle.pem` in the same directory as the executable. As long as this file sits next to `main.py` or the built `.exe`, it will automatically bypass SSL errors.

## 3. Manual Setup (For new systems or new development environments)
If you are moving this project to a completely new laptop and want to run it via Python (not the built .exe), you must set the environment variables exactly as follows so Python can communicate over your corporate network:

### For Windows (System Environment Variables):
Add these User or System Variables:
*   **Variable Name**: `REQUESTS_CA_BUNDLE`
    **Variable Value**: `C:\Path\To\This\Folder\custom_bundle.pem`
*   **Variable Name**: `CURL_CA_BUNDLE`
    **Variable Value**: `C:\Path\To\This\Folder\custom_bundle.pem`
*   **Variable Name**: `SSL_CERT_FILE`
    **Variable Value**: `C:\Path\To\This\Folder\custom_bundle.pem`
*   **Variable Name**: `NO_PROXY` 
    **Variable Value**: `localhost,127.0.0.1`

### Python Library Fixes
If you ever run pip install and get SSL Verification Errors, use this command structure:
`pip install [package_name] --cert "C:\Path\To\This\Folder\custom_bundle.pem"`
