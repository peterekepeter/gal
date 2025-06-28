A hackable web browser written in python. The implementation DOES NOT
aim to be COMPLETE and PROVIDES NO SECURITY GUARANTEES! USE AT YOUR OWN 
RISK! You have been warned!


## Features

- Tabbed browsing
    - tabs are restored after close
- Bookmarks
- History
- Browser Engine:
    - protocols: HTTP/1.1 HTTPS
    - encoding: chunked gzip
    - basic HTML/CSS support: div, input, button, forms
    - JavaScript: basic DOM manipulation


# Dependencies

You will need a python. If you don't know how to get it, get it from:
    
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


## Running

Run browser, user profile stored within current user's home directory.

    python main.py

The browser respectes the XDG standard cache goes into `~/.cache/gal`,
state goes into `~/.local/state/gal` and config/cookies/bookmarks are in
`~/.local/share/gal`

If you don't want the browser to store files on the disk then you can run in
private mode then everything stays in memory and is cleared during exit.

    python main.py --private

If you need multiple profiles on the same user stored on disk then you can 
also run the browser with a custom dir where all data gets written to:

    python main.py --profile somefolder


## Automated Testing

To run all automated tests in a stable way from hassle free

    python main.py --testall

To practice TDD and have a nice feedback loop I recommend using a nodemon
to watch sources and auto run the tests. This reruns the all tests and then 
starts the browser.

    nodemon -e py,html,js -x "python main.py --testall"

To run just one type of tests there are separate commands. The project 
contains multiple types of tests. They can be run with separate commands.

    python main.py --test
    python main.py --wtest
    python main.py --wstest

After test is run, the browser will start, if you want to avoid that there
is an extra argument to prevent it.

    python main.py --test --exit


## Manual Testing

Test example website

    python main.py https://example.org

Test with local server

    python -m http.server 8000 -d ./
    python main.py http://localhost:8000

Happy browsing!
