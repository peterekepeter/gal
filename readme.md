Is a hackable web browser written in python. The implementation does not
aim to be complete and PROVIDES NO SECURITY GUARANTEES! USE AT YOUR OWN 
RISK! You have been warned!

## Features

- Tabbed browsing
    - tabs are restored after close
- Bookmarks
- History
- Browser Engine:
    - protocols: HTTP/1.1 HTTPS
    - encoding: chunked gzip
    - basic HTML support: div, input, button, forms
    - basic CSS support: background, color, font
    - JavaScript: basic DOM manipulation

## Running

Run browser, user profile stored within current user's home directory:

    python main.py

Run a private browser where no data is read or stored to disk:

    python main.py --private

Run browser with a custom dir where all data gets saved/cached:

    python main.py --profile somefolder

## Testing

Run unit tests

    python main.py --test

Run web tests

    python main.py --wtest

Test example website

    python main.py https://example.org

Test with local server

    python -m http.server 8000 -d ./
    python main.py http://localhost:8000

Test redirection

    python main.py http://browser.engineering/redirect
    python main.py http://browser.engineering/redirect2
    python main.py http://browser.engineering/redirect3


# Dependencies

You will need a python. You can get it from:
    
    https://www.python.org/downloads/

For HTTPS support, your python needs to be built with SSL module. This
should be done by default.

For GUI your python will need tk tookit built. This is again by default
should come with a complete installation of python but some stripped
down versions of python you may need to install separately or build
python from sourcw with Tk enabled.

For JavaScript support, you will need the dukpy pip pacakge installed 
and avaiable within your python environment:

    pip install dukpy

Happy browsing!