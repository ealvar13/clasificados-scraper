#!/bin/bash
# SETUP INSTRUCTIONS:
# 1. Copy this file to run_scraper.sh
# 2. Update the PROJECT_DIR path below
# 3. Update VENV_NAME if you use .venv instead of venv
# 4. Make executable: chmod +x run_scraper.sh
# 5. Test: ./run_scraper.sh
# 6. Add to crontab: 0 14 * * * /full/path/to/run_scraper.sh

cd /home/ubuntu/path_to/your_repo
source venv/bin/activate  # or .venv/bin/activate
python main.py >> logs/scraper.log 2>&1