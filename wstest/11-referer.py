# check default referer and referer policy
from test.lib import HttpServer, Html, Header

server_2 = HttpServer(
    lambda x: (
        200,
        Html("<title>passed</title>"),
    )
    if x.path == "/" and x.headers.get('referer') is None
    else (
        404
    ),
    port=0, # allocate random
)
server_2.listen_on_thread()

server = HttpServer(
    lambda x: (
        200,
        Html("""
            <a id=lnk href=/step2>click</a>
            <script>lnk.click()</script>
        """),
    ) if x.path == "/" else (
        200,
        Header("Referrer-Policy", "same-origin"),
        Html("""
            <a id=lnk href=/step3>click</a>
            <script>lnk.click()</script>
        """),
    ) if x.path == "/step2" and x.headers.get('referer').endswith('/') else (
        200,
        Header("Referrer-Policy", "no-referrer"),
        Html("""
            <a id=lnk href=/step4>click</a>
            <script>lnk.click()</script>
        """),
    ) if x.path == "/step3" and x.headers.get('referer').endswith('/step2') else (
        200,
        Header("Referrer-Policy", "same-origin"),
        Html(f"""
            <a id=lnk href={server_2.get_address()}>click</a>
            <script>lnk.click()</script>
        """),
    ) if x.path == "/step4" and x.headers.get('referer') is None else (
        404,
    )
)
server.listen()