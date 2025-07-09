# # web service test 01 - basic sanity check
from test.lib import HttpServer, Html, ExitProcess

HttpServer(
    lambda x: (
        200,
        Html("""
            <body><a href=other>link</a></body>
            <script>document.body.onload = function() { 
                var link = document.querySelectorAll('a')[0];
                link.click() 
            }</script>
        """),
    ) if x.path == "/" else (
        200,
        Html("<title>passed</title>"),
        ExitProcess(0),
    )
).listen()
