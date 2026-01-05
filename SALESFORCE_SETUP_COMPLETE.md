# Salesforce Integration Setup Guide

## Your Certificate Management System is now ready for Salesforce integration!

### App URL: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/

## Step 1: Test Salesforce Account ID Integration

Test with a sample Account ID:
- **URL**: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001
- **Expected**: Should show Certificate Management System with Account ID

## Step 2: Create Salesforce Visualforce Page

1. **Go to Setup** â†’ **Developer Console** (or **Setup** â†’ **Lightning App Builder**)

2. **Create New Visualforce Page**:
   - Name: `CertificateManager`
   - API Name: `CertificateManager`

3. **Copy this code**:

```apex
<apex:page standardController="Account">
    <head>
        <style>
            body { margin: 0; padding: 0; font-family: Arial, sans-serif; }
            .container { width: 100%; height: 100vh; }
            iframe { width: 100%; height: 100%; border: none; }
            .header { background: #0176d3; color: white; padding: 10px; text-align: center; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Certificate Management System - {!Account.Name}</h2>
            </div>
            <iframe src="https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/{!Account.Id}" 
                    title="Certificate Management System">
            </iframe>
        </div>
    </body>
</apex:page>
```

4. **Save the page**

## Step 3: Configure Remote Site Settings

1. **Go to Setup** â†’ **Security** â†’ **Remote Site Settings**
2. **Click "New Remote Site"**
3. **Fill in**:
   - **Remote Site Name**: `CertificateManager`
   - **Remote Site URL**: `https://pdfeditorsalesforce-49dc376497fd.herokuapp.com`
   - **Check**: "Active"
4. **Click "Save"**

## Step 4: Add to Account Page Layout

1. **Go to Setup** â†’ **Object Manager** â†’ **Account**
2. **Click "Page Layouts"**
3. **Edit your Account page layout**
4. **Add the Visualforce Page**:
   - Drag "Visualforce Pages" from the palette
   - Select "CertificateManager"
   - Position it where you want on the page
5. **Save the layout**

## Step 5: Test Integration

1. **Go to any Account record**
2. **You should see** the Certificate Management System embedded
3. **The Account ID** will be automatically passed to your app
4. **Upload ACORD templates** and manage certificates for that account

## Features Available:

âœ… **Account-Specific Data**: Each Salesforce Account has its own certificate data
âœ… **PDF Template Management**: Upload and manage ACORD forms
âœ… **Form Filling**: Fill PDFs with account-specific information
âœ… **Certificate Generation**: Create certificates for each account
âœ… **Salesforce Integration**: Seamlessly embedded in Account records

## Troubleshooting:

- **If iframe doesn't load**: Check Remote Site Settings
- **If Account ID not passed**: Verify the Visualforce page code
- **If app shows error**: Check Heroku logs

## Next Steps:

1. Upload your ACORD PDF templates through the web interface
2. Test form filling with sample data
3. Customize the interface as needed
4. Train users on the new Certificate Management System

Your Certificate Management System is now fully integrated with Salesforce! ðŸŽ‰
