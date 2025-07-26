(function () {
    var window = new Function('return this;')();
    /** @type {Record<number,Record<string,function[]>>} */
    var LISTENERS = {};
    var py = call_python;
    
    Object.defineProperties(window, {
        'location': { set: function(value) { py("location_set", value); } }
    })

    window.Event = function Event(type,options) { options=options||{}; this.type = type; this.do_default = true; this.bubbles=options.bubbles==true; this.trusted=false; this.eventPhase=Node.NONE; }
    Event.prototype.preventDefault = function () { this.do_default = false; }
    Event.prototype.stopPropagation = function () { this.bubbles = false; }
    Event.prototype.NONE = 0;
    Event.prototype.CAPTURING_PHASE = 1;
    Event.prototype.AT_TARGET = 2;
    Event.prototype.BUBBLING_PHASE = 3;

    function Node(handle) { this.handle = handle; }
    Node.prototype.getAttribute = function(name) { return py("getAttribute", this.handle, name) }
    Node.prototype.setAttribute = function(name, value) { py("setAttribute", this.handle, name, value); }
    Node.prototype.appendChild = function(child) { py("appendChild", this.handle, child.handle) }
    Node.prototype.insertBefore = function(toinsert, reference) { py("insertBefore", this.handle, toinsert.handle, reference.handle) }
    Node.prototype.removeChild = function(toremove) { py("removeChild", this.handle, toremove.handle); return toremove; }
    Node.prototype.addEventListener = function(type, listener) { 
        if (!LISTENERS[this.handle]) LISTENERS[this.handle] = {};
        var dict = LISTENERS[this.handle];
        if (!dict[type]) dict[type] = [];
        var list = dict[type];
        list.push(listener);
    }
    Node.prototype.dispatchEvent = function(event) {
        var type = event.type;
        var handle = this.handle;
        event.eventPhase = Event.AT_TARGET;
        var list = (LISTENERS[handle] && LISTENERS[handle][type]) || []
        for (var i=0; i<list.length; i+=1) {
            list[i].call(this, event)
        }
        if (event.bubbles) {
            event.eventPhase = Event.BUBBLING_PHASE;
            var parent = this.parent;
            while (parent && event.bubbles) {
                var node = parent;
                parent = parent.parent;
                var listenerTypes = LISTENERS[node.handle];
                if (!listenerTypes) continue;
                var list = listenerTypes[type];
                if (!list) continue;
                for (var i=0; i<list.length; i+=1) {
                    list[i].call(node, event);
                }
            }
        }
        if (event.__ret) {
            return event.do_default;
        }
        else if (event.do_default) {
            py("do_default", handle, type);
        }
    }
    Node.prototype.click = function () { this.dispatchEvent(new Event('click')); }
    Object.defineProperties(Node.prototype, {
        'innerHTML': {  get: function() { return py("innerHTML_get", this.handle); }, set: function(s) { py("innerHTML_set", this.handle, s.toString()); }  },
        'outerHTML': {  get: function() { return py("outerHTML_get", this.handle);}  },
        'children': {  get: function() { return py("children_get", this.handle).map(tonode); }  },
        'onload': {  set: function(fn) { this.addEventListener("load", fn); }},
        'parent': {  get: function() { return tonode(py("parent_get", this.handle)) }  },
    })

    function Document() {}
    Document.prototype.querySelectorAll = function(s){ return call_python("querySelectorAll", s).map(tonode) }
    Document.prototype.createElement = function(s){ return tonode(call_python("createElement", s)) }
    Document.prototype.createTextNode = function(s){ return tonode(call_python("createTextNode", s)) }
    Object.defineProperties(Document.prototype, {
        'title': {  get: function() { return py("document_get_title")}, set: function(s) { return py("document_set_title", s.toString()); }  },
        'body': {  get: function() { return tonode(py("document_get_body")) }  },
        'cookie': {  get: function() { return py("document_get_cookie")}, set: function(s) { return py("document_set_cookie", s.toString()); }  },
    })

    window.XMLHttpRequest = function XMLHttpRequest(){}
    XMLHttpRequest.prototype.open = function(method,url,is_async){
        if (is_async) throw Error("Async XHR not supported!");
        this.method = method;
        this.url = url;
    }
    XMLHttpRequest.prototype.send = function(body) {
        this.responseText = py("XHR_send", this.method, this.url, body);
    }

    function tonode(handle) { if (handle >= 0) return new Node(handle); return undefined; }
    function log(){ call_python("log", arr(arguments).join(" ")) }
    function arr(arraylike){ var a=[]; for(var i=0;i<arraylike.length;i+=1) a.push(arraylike[i]); return a }
    window.console = { log:log, warn:log, error:log, info:log, debug:log };
    window.document = new Document();
    window.window = window;
    window.getComputedStyle = function(node) { return py("getComputedStyle", node.handle) }
    __dispatch_event = function (handle, type) { var event=new Event(type); event.isTrusted=true; event.bubbles=true; event.__ret=true; return new Node(handle).dispatchEvent(event) !== false }
    __global_node = function (name, handle) { if (typeof window[name] === 'undefined') window[name] = new Node(handle); }
    __global_node_remove = function (name, handle) { if (typeof window[name] !== 'undefined' && window[name] instanceof Node && window[name].handle === handle) delete window[name]; }
})();