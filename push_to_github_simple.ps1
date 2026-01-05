# PowerShell script to push changes to GitHub
Write-Host "Pushing Certificate Management System changes to GitHub..." -ForegroundColor Green
Write-Host ""

# Check if we're in a git repository
if (Test-Path ".git") {
    Write-Host "Git repository detected" -ForegroundColor Green
} else {
    Write-Host "Not a git repository. Please use GitHub Desktop or web interface." -ForegroundColor Yellow
    Write-Host "Repository: https://github.com/loganwilliamstarp-web/pdf-editor" -ForegroundColor Cyan
    exit 1
}

# Try to use git if available
try {
    Write-Host "Adding all changes..." -ForegroundColor Yellow
    & git add .
    
    Write-Host "Committing changes..." -ForegroundColor Yellow
    & git commit -m "Fix PDF editor functionality and remove upload section"
    
    Write-Host "Pushing to GitHub..." -ForegroundColor Yellow
    & git push origin main
    
    Write-Host ""
    Write-Host "SUCCESS! Changes pushed to GitHub!" -ForegroundColor Green
    Write-Host "Repository: https://github.com/loganwilliamstarp-web/pdf-editor" -ForegroundColor Cyan
    Write-Host "Heroku will auto-deploy in 2-3 minutes..." -ForegroundColor Yellow
    Write-Host "Your app: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001" -ForegroundColor Green
    
} catch {
    Write-Host ""
    Write-Host "Git command failed. Manual steps required:" -ForegroundColor Red
    Write-Host ""
    Write-Host "MANUAL STEPS:" -ForegroundColor Yellow
    Write-Host "1. Open GitHub Desktop" -ForegroundColor White
    Write-Host "2. Navigate to: loganwilliamstarp-web/pdf-editor" -ForegroundColor White
    Write-Host "3. Review the changes" -ForegroundColor White
    Write-Host "4. Commit with message: Fix PDF editor functionality and remove upload section" -ForegroundColor White
    Write-Host "5. Push to GitHub" -ForegroundColor White
    Write-Host ""
    Write-Host "Or use GitHub web interface:" -ForegroundColor Cyan
    Write-Host "https://github.com/loganwilliamstarp-web/pdf-editor" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Your Certificate Management System updates are ready!" -ForegroundColor Green
Write-Host "Modified files: app.py, index.html" -ForegroundColor White
Write-Host "New features: PDF Editor, Database APIs, Template renaming" -ForegroundColor White
