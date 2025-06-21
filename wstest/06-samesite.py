# # web service test 01 - basic sanity check
from test.lib import HttpServer, Html, Header, ExitProcess

server_2 = HttpServer(
    lambda x: (
        200,
        # TODO test if request to main server works properly
        Html("<title>passed</title>"),
        ExitProcess(0),
    ),
    port=0,
)
server_2.listen_on_thread()
url = server_2.get_address()

HttpServer(
    lambda x: (
        301,
        Header("Set-Cookie", "foo=bar; SameSite=Lax"),
        Header("Location", url),
    )
).listen()
