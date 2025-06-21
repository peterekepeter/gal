# TODO implement check that form with CSRF protection
# works as expected
from test.lib import HttpServer, Html, ExitProcess

HttpServer(lambda x: (200, Html("<title>passed</title>"), ExitProcess())).listen()
