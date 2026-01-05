Write-Host "Alternative: Using Heroku CLI" -ForegroundColor Yellow
Write-Host "================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "If you have Heroku CLI installed, you can run:" -ForegroundColor White
Write-Host ""
Write-Host "1. heroku pg:psql -a pdfeditorsalesforce-49dc376497fd" -ForegroundColor Cyan
Write-Host "2. Then paste the SQL commands one by one" -ForegroundColor White
Write-Host ""
Write-Host "Or run the SQL file directly:" -ForegroundColor White
Write-Host "heroku pg:psql -a pdfeditorsalesforce-49dc376497fd < heroku_database_schema.sql" -ForegroundColor Cyan
Write-Host ""
Write-Host "But the easiest way is through the Heroku Dashboard as described above." -ForegroundColor Green
