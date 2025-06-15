# # web service test 01 - basic sanity check
from test.lib import HttpServer, Html, ExitProcess

HttpServer(lambda x: (200, Html("<title>passed</title>"), ExitProcess())).listen()
