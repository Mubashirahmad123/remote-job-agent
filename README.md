# Remote Job Agent

An AI-powered job scraping and application automation system that scrapes remote developer jobs from multiple job boards, curates them, and generates personalized cover letters using CrewAI and Google Gemini.

## 🚀 Features

- **Multi-Source Job Scraping**: Scrapes jobs from 30+ remote job boards including:
  - Remotive, RemoteOK, Arbeitnow (API-based)
  - WeWorkRemotely, Remote.co, JustRemote, Himalayas, NoDesk, Wellfound (HTML-based)
  - And many more...

- **Intelligent Curation**: 
  - Removes duplicate job listings
  - Filters out senior/lead positions (targets junior/mid-level)
  - Ranks jobs by quality (salary, company, tech stack)
  - Saves curated jobs to Google Sheets

- **AI-Powered Cover Letters**:
  - Generates personalized cover letters using Google Gemini
  - Saves cover letters as professional PDFs
  - Highlights relevant skills (Node.js, Django, React, etc.)

- **Automated Scheduling**:
  - Runs automatically every Monday and Thursday at 9:00 AM
  - Logs all activities to `logs/scraper.log`

## 📋 Prerequisites

- Python 3.11+
- Google Cloud Service Account with Sheets API access
- Google Gemini API Key
- Google Sheet for job storage

## 🛠️ Installation

1. **Clone the repository**:
```bash
git clone <repository-url>
cd remote-job-agent
```

2. **Create virtual environment**:
```bash
python -m venv venv
venv\Scripts\activate  # On Windows
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Configure environment**:
   - Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   
   - Edit `.env` with your credentials:
   ```env
   GOOGLE_SHEETS_ID=your_google_sheet_id
   GOOGLE_SERVICE_ACCOUNT=path/to/your-service-account.json
   GEMINI_API_KEY=your_gemini_api_key
   MODEL=gemini/gemini-2.0-flash
   RUN_MODE=crewai
   ```

5. **Set up Google Service Account**:
   - Download your service account JSON key
   - Save it as `keys.json` (or reference it in `.env`)
   - Share your Google Sheet with the service account email

## 📁 Project Structure

```
remote-job-agent/
├── agents/
│   ├── __init__.py
│   ├── scrapper.py      # Job scraping logic for 30+ boards
│   ├── curator.py       # Job curation and Google Sheets integration
│   └── gemini_tools.py  # AI cover letter generation
├── tools/
│   ├── sheet_writer.py  # Google Sheets operations
│   └── scraper_utils.py # Utility functions
├── cover_letters/       # Generated PDF cover letters
├── logs/                # Scheduler execution logs
├── main.py              # CrewAI pipeline orchestration
├── scheduler.py         # Automated scheduling (cron-like)
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (not tracked)
├── .env.example         # Environment template
├── keys.json            # Service account key (not tracked)
└── scraped_jobs.json    # Scraped jobs data (generated)
```

## 🎯 Usage

### Run the Full Pipeline (CrewAI Mode)

```bash
python main.py
```

This will:
1. Scrape jobs from all configured boards
2. Curate and save to Google Sheets
3. Generate a personalized cover letter as PDF

### Run in Simple Mode (Testing)

```bash
python main.py
```
Set `RUN_MODE=simple` in `.env`

### Run Tests

```bash
python main.py
```
Set `RUN_MODE=test` in `.env`

### Run the Scheduler

```bash
python scheduler.py
```

The scheduler runs automatically every:
- **Monday at 9:00 AM**
- **Thursday at 9:00 AM**

## 📊 Output

### Scraped Jobs (`scraped_jobs.json`)
```json
{
  "job_title": "Full Stack Developer",
  "company": "Tech Company",
  "salary": "$80,000 - $100,000",
  "tech_stack": "node, react, python",
  "timezone": "Remote",
  "apply_url": "https://...",
  "summary": "Exciting opportunity...",
  "posted_date_iso": "2024-01-15",
  "source": "Remotive"
}
```

### Google Sheet
Jobs are saved to the "LIVE Remote Jobs Tracker" worksheet with columns:
- job_title, company, salary, tech_stack, timezone, apply_url, summary, posted_date_iso

### Cover Letters (`cover_letters/`)
PDF files named: `{JobTitle}_{YYYY-MM-DD_HH-MM-SS}.pdf`

## 🤖 Agents

The system uses CrewAI with three specialized agents:

1. **Senior Job Scraper**: Discovers remote developer jobs from multiple boards
2. **Job Curator Specialist**: Filters duplicates, ranks quality, saves to Google Sheets
3. **Professional Cover Letter Writer**: Generates tailored applications using Gemini AI

## 🔧 Configuration

### Modify Job Boards
Edit `agents/scrapper.py`:
- Update `MASTER_BOARDS` dictionary
- Add custom parsers for new sites

### Adjust Filters
Modify these patterns in `agents/scrapper.py`:
```python
TECH_FILTER = r"(?i)(node|django|react|...)"  # Tech keywords to match
EXCLUDE_FILTER = r"\b(senior|lead|principal|manager)\b"  # Exclude senior roles
```

## 🐛 Troubleshooting

**Google Sheets connection fails**:
- Verify `GOOGLE_SERVICE_ACCOUNT` path is correct
- Ensure service account has editor access to the sheet
- Check `GOOGLE_SHEETS_ID` is correct

**Gemini API errors**:
- Verify `GEMINI_API_KEY` is set in `.env`
- Check API quota limits

**No jobs found**:
- Run with `debug=True` in `scrape_all()`
- Check individual scraper logs
- Verify job board HTML/API structure hasn't changed

## 📝 License

MIT License - see LICENSE file for details.

## 👤 Author

**Mubashir** - Remote Job Agent Developer

## 🙏 Acknowledgments

- CrewAI for the agent framework
- Google Gemini for AI capabilities
- All job boards for public API/HTML access
