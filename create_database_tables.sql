-- Certificate Management System Database Schema
-- Run this SQL in your Supabase SQL Editor

-- 1. Master Templates Table - Templates stored once, reused for all accounts
CREATE TABLE IF NOT EXISTS master_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_name VARCHAR(100) NOT NULL UNIQUE,
    template_type VARCHAR(50) NOT NULL,
    storage_path VARCHAR(500),
    file_size INTEGER,
    pdf_blob BYTEA,
    form_fields JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. Template Data by Account - Account-specific filled data
ALTER TABLE master_templates ADD COLUMN IF NOT EXISTS pdf_blob BYTEA;

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

-- 3. Generated Certificates - Track generated certificates
CREATE TABLE IF NOT EXISTS generated_certificates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(18) NOT NULL,
    template_id UUID REFERENCES master_templates(id),
    certificate_name VARCHAR(255),
    storage_path VARCHAR(500),
    status VARCHAR(50) DEFAULT 'draft',
    generated_at TIMESTAMP DEFAULT NOW()
);

-- 4. Certificate Holders - People who receive certificates
CREATE TABLE IF NOT EXISTS certificate_holders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(18) NOT NULL,
    name VARCHAR(255) NOT NULL,
    master_remarks TEXT,
    address_line1 VARCHAR(255),
    city VARCHAR(120),
    state VARCHAR(2),
    email VARCHAR(255),
    phone VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS master_remarks TEXT;
ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(255);
ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS city VARCHAR(120);
ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS state VARCHAR(2);
ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS phone VARCHAR(50);
ALTER TABLE certificate_holders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
ALTER TABLE certificate_holders ALTER COLUMN name SET NOT NULL;
UPDATE certificate_holders SET updated_at = COALESCE(updated_at, created_at, NOW());

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_certificate_holders_account_id_len'
    ) THEN
        ALTER TABLE certificate_holders
        ADD CONSTRAINT ck_certificate_holders_account_id_len
        CHECK (char_length(account_id) IN (15, 18));
    END IF;
END $$;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_template_data_account ON template_data(account_id);
CREATE INDEX IF NOT EXISTS idx_template_data_template ON template_data(template_id);
CREATE INDEX IF NOT EXISTS idx_master_templates_type ON master_templates(template_type);
CREATE INDEX IF NOT EXISTS idx_generated_certificates_account ON generated_certificates(account_id);
CREATE INDEX IF NOT EXISTS idx_certificate_holders_account ON certificate_holders(account_id);

-- Insert some sample data to test
INSERT INTO master_templates (template_name, template_type, storage_path, file_size, pdf_blob, form_fields) VALUES
('ACORD 25 - Certificate of Liability Insurance', 'acord25', 'master_templates/acord25.pdf', 1024, NULL, '{"fields": []}'),
('ACORD 27 - Evidence of Property Insurance', 'acord27', 'master_templates/acord27.pdf', 1024, NULL, '{"fields": []}'),
('ACORD 28 - Evidence of Commercial Property Insurance', 'acord28', 'master_templates/acord28.pdf', 1024, NULL, '{"fields": []}')
ON CONFLICT (template_name) DO NOTHING;

-- Show the created tables
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE '%template%' OR table_name LIKE '%certificate%';
