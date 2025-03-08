

Test a module

    python main.py --test


Test example website

    python main.py https://example.org

Test with local server

    python -m http.server 8000 -d ./
    python main.py http://localhost:8000

Test redirection

    python main.py http://browser.engineering/redirect
    python main.py http://browser.engineering/redirect2
    python main.py http://browser.engineering/redirect3
