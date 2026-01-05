# Database Setup Instructions for Supabase
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host "SUPABASE DATABASE SETUP INSTRUCTIONS" -ForegroundColor Yellow
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "STEP 1: Open Supabase Dashboard" -ForegroundColor Green
Write-Host "Go to: https://supabase.com/dashboard/project/lpvzcfvcfckgdeuhzhrj" -ForegroundColor White
Write-Host ""
Write-Host "STEP 2: Open SQL Editor" -ForegroundColor Green
Write-Host "1. Click 'SQL Editor' in the left sidebar" -ForegroundColor White
Write-Host "2. Click 'New Query'" -ForegroundColor White
Write-Host ""
Write-Host "STEP 3: Copy and Paste This SQL Code:" -ForegroundColor Green
Write-Host "==================================================================================" -ForegroundColor Yellow

$sql = @"
-- Certificate Management System Database Schema
CREATE TABLE IF NOT EXISTS master_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_name VARCHAR(100) NOT NULL UNIQUE,
    template_type VARCHAR(50) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    file_size INTEGER,
    form_fields JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS template_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(18) NOT NULL,
    template_id UUID REFERENCES master_templates(id),
    field_values JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    version INTEGER DEFAULT 1,
    UNIQUE(account_id, template_id)
);

CREATE TABLE IF NOT EXISTS generated_certificates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(18) NOT NULL,
    template_id UUID REFERENCES master_templates(id),
    certificate_name VARCHAR(255),
    storage_path VARCHAR(500),
    status VARCHAR(50) DEFAULT 'draft',
    generated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS certificate_holders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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

-- Insert sample template data
INSERT INTO master_templates (template_name, template_type, storage_path, file_size, form_fields) VALUES
('ACORD 25 - Certificate of Liability Insurance', 'acord25', 'master_templates/acord25.pdf', 1024, '{"fields": []}'),
('ACORD 27 - Evidence of Property Insurance', 'acord27', 'master_templates/acord27.pdf', 1024, '{"fields": []}'),
('ACORD 28 - Evidence of Commercial Property Insurance', 'acord28', 'master_templates/acord28.pdf', 1024, '{"fields": []}')
ON CONFLICT (template_name) DO NOTHING;
"@

Write-Host $sql -ForegroundColor White
Write-Host ""
Write-Host "==================================================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "STEP 4: Execute the SQL" -ForegroundColor Green
Write-Host "1. Click 'Run' button in Supabase SQL Editor" -ForegroundColor White
Write-Host "2. Wait for success message" -ForegroundColor White
Write-Host ""
Write-Host "STEP 5: Verify Tables Created" -ForegroundColor Green
Write-Host "You should see 4 tables created:" -ForegroundColor White
Write-Host "- master_templates" -ForegroundColor Cyan
Write-Host "- template_data" -ForegroundColor Cyan
Write-Host "- generated_certificates" -ForegroundColor Cyan
Write-Host "- certificate_holders" -ForegroundColor Cyan
Write-Host ""
Write-Host "STEP 6: Test Template Upload" -ForegroundColor Green
Write-Host "After creating tables, run: python upload_simple.py" -ForegroundColor White
Write-Host ""
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host "Once tables are created, your Certificate Management System will be fully functional!" -ForegroundColor Yellow
Write-Host "==================================================================================" -ForegroundColor Cyan
