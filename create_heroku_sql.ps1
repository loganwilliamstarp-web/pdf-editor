# Create SQL file for Heroku PostgreSQL setup
$sql = @"
-- Certificate Management System Database Schema for Heroku PostgreSQL

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Master Templates Table
CREATE TABLE IF NOT EXISTS master_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_name VARCHAR(100) NOT NULL UNIQUE,
    template_type VARCHAR(50) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    file_size INTEGER,
    form_fields JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. Template Data by Account
CREATE TABLE IF NOT EXISTS template_data (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id VARCHAR(18) NOT NULL,
    template_id UUID REFERENCES master_templates(id),
    field_values JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    version INTEGER DEFAULT 1,
    UNIQUE(account_id, template_id)
);

-- 3. Generated Certificates
CREATE TABLE IF NOT EXISTS generated_certificates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id VARCHAR(18) NOT NULL,
    template_id UUID REFERENCES master_templates(id),
    certificate_name VARCHAR(255),
    storage_path VARCHAR(500),
    status VARCHAR(50) DEFAULT 'draft',
    generated_at TIMESTAMP DEFAULT NOW()
);

-- 4. Certificate Holders
CREATE TABLE IF NOT EXISTS certificate_holders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id VARCHAR(18) NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    address TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);
CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);
CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);
CREATE INDEX IF NOT EXISTS idx_generated_certificates_account ON generated_certificates(account_id);
CREATE INDEX IF NOT EXISTS idx_certificate_holders_account ON certificate_holders(account_id);
"@

$sql | Out-File -FilePath heroku_database_schema.sql -Encoding UTF8

Write-Host "Created heroku_database_schema.sql file" -ForegroundColor Green
Write-Host ""
Write-Host "To run this SQL on your Heroku PostgreSQL database:" -ForegroundColor Yellow
Write-Host "1. Install Heroku CLI if not already installed" -ForegroundColor White
Write-Host "2. Run: heroku pg:psql -a pdfeditorsalesforce-49dc376497fd < heroku_database_schema.sql" -ForegroundColor Cyan
Write-Host ""
Write-Host "Alternative: Copy and paste the SQL above into your Heroku dashboard" -ForegroundColor Yellow
Write-Host "1. Go to: https://dashboard.heroku.com/apps/pdfeditorsalesforce-49dc376497fd" -ForegroundColor White
Write-Host "2. Click on the Heroku Postgres addon" -ForegroundColor White
Write-Host "3. Go to 'Data' tab and click 'Query'" -ForegroundColor White
Write-Host "4. Paste the SQL and run it" -ForegroundColor White
