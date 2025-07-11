from test.lib import HttpServer, Html, JavaScript, Header

server_2 = HttpServer(
    lambda x: (
        200,
        JavaScript("value=999"),
    ),
    port=0, # allocate random
)
server_2.listen_on_thread()

server_1 = HttpServer(
    lambda x: (
        200,
        Header("Content-Security-Policy", f"default-src {server_1.get_address()}"),
        Html(f"""<body>
            <script src=/jsvalue></script>
            <script src={server_2.get_address()}></script>
            <script src=/jscheck></script> 
        </body>"""),
    ) if x.method == "GET" and x.path == "/"
    else (
        200,
        JavaScript("value=1"),
    ) if x.method == "GET" and x.path == "/jsvalue"
    else ( 
        200, 
        JavaScript("document.title = value === 1 ? 'passed' : 'failed';")
    ) if x.method == "GET" and x.path == "/jscheck" 
    else (404),
)
server_1.listen()
